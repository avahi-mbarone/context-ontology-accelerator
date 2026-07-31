# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests that drive the REAL grounding pipeline end-to-end.

Unlike ``test_grounding_service.py`` (which patches ``_recall`` and
``_llm_rerank`` to isolate the classification branches), these tests exercise
the recall + dedup + exact-name + LLM-rerank code paths for real, mocking only
the external boundaries: the ontology-catalog ``search_embeddings`` call and the
Bedrock ``converse`` client. This asserts observable behavior (the returned
``GroundingResult`` / ``ConceptMatch``), not internal state.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from coa_ontology.inducer.services.grounding import (
    GroundingService,
    classify_score_tier,
)

pytestmark = pytest.mark.unit


def _make_service(hits: list[dict]) -> GroundingService:
    """Build a GroundingService whose catalog returns ``hits`` from recall."""
    catalog = MagicMock()
    catalog.search_embeddings.return_value = hits
    svc = GroundingService(
        ontology_catalog=catalog,
        embedding_generator=MagicMock(),
        llm_region="us-east-1",
        llm_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        namespace="ns1",
    )
    return svc


def _bedrock_returning(text: str) -> MagicMock:
    client = MagicMock()
    client.converse.return_value = {"output": {"message": {"content": [{"text": text}]}}}
    return client


# ── STANDARD mode: real recall + exact-name match ───────────────────────


class TestStandardExactMatch:
    def test_single_exact_name_match_auto_grounds_with_confidence_one(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.88, "text": "Agreement a deal"},
            {"entity_uri": "http://fibo/Party", "ontology_id": "fibo", "score": 0.40, "text": "Party a person"},
        ]
        svc = _make_service(hits)
        result = svc.ground_table(
            table_name="agreement",
            table_description="a contract",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="STANDARD",
            ontology_ids=["fibo"],
        )
        assert result.match_type == "exact"
        assert result.chosen is not None
        assert result.chosen.entity_uri == "http://fibo/Agreement"
        assert result.confidence == 1.0
        assert result.relationship == "exactMatch"
        assert result.mode == "STANDARD"

    def test_multiple_exact_matches_picks_highest_embedding_score(self):
        # Two candidates share local name "Agreement" but come from different
        # ontologies (so they survive dedup); STANDARD picks the higher score.
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.91, "text": "Agreement deal"},
            {"entity_uri": "http://dc/Agreement", "ontology_id": "dublincore", "score": 0.72, "text": "Agreement x"},
        ]
        svc = _make_service(hits)
        result = svc.ground_table(
            table_name="Agreement",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="STANDARD",
            ontology_ids=["fibo"],
        )
        assert result.match_type == "high_confidence"
        assert result.relationship == "closeMatch"
        assert result.chosen.entity_uri == "http://fibo/Agreement"
        assert result.confidence == pytest.approx(0.91)

    def test_no_exact_match_classifies_on_embedding_score(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.55, "text": "Agreement deal"},
        ]
        svc = _make_service(hits)
        result = svc.ground_table(
            table_name="policy",
            table_description="insurance policy",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="STANDARD",
            ontology_ids=["fibo"],
        )
        # 0.55 → ambiguous tier (>=0.50, <0.80) in STANDARD (no rerank)
        assert result.match_type == "ambiguous"
        assert result.relationship == "relatedMatch"
        assert result.mode == "STANDARD"


# ── Recall internals: dedup, cosine fallback, definition extraction ─────


class TestRecall:
    def test_dedupes_http_variants_keeping_highest_score(self):
        # Same URI up to trailing slash → collapse to one, keep higher score.
        hits = [
            {"entity_uri": "http://fibo/Claim", "ontology_id": "fibo", "score": 0.60, "text": "Claim demand"},
            {"entity_uri": "http://fibo/Claim/", "ontology_id": "fibo", "score": 0.80, "text": "Claim demand"},
        ]
        svc = _make_service(hits)
        result = svc.ground_table(
            table_name="ledger",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="STANDARD",
            ontology_ids=["fibo"],
        )
        # Only one candidate survives dedup, carrying the higher score.
        assert len(result.candidates) == 1
        assert result.candidates[0].lexical_sim == pytest.approx(0.80)

    def test_cosine_fallback_used_when_score_absent(self):
        # No 'score' key but a raw vector present → local cosine is computed.
        hits = [
            {"entity_uri": "http://fibo/Thing", "ontology_id": "fibo", "vector": [1.0] * 8, "text": "Thing"},
        ]
        svc = _make_service(hits)
        result = svc.ground_table(
            table_name="whatever",
            table_description="",
            columns=[],
            concept_vector=[1.0] * 8,
            model_id="titan",
            grounding_mode="STANDARD",
            ontology_ids=["fibo"],
        )
        # Identical unit vectors → cosine 1.0.
        assert result.candidates[0].lexical_sim == pytest.approx(1.0)

    def test_definition_strips_label_prefix_from_text(self):
        hits = [
            {
                "entity_uri": "http://fibo/Agreement",
                "ontology_id": "fibo",
                "score": 0.9,
                "text": "Agreement a negotiated understanding between parties",
            },
        ]
        svc = _make_service(hits)
        result = svc.ground_table(
            table_name="ledger",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="STANDARD",
            ontology_ids=["fibo"],
        )
        cand = result.candidates[0]
        assert cand.label == "Agreement"
        # Label prefix stripped from the embedded text to yield the definition.
        assert cand.definition == "a negotiated understanding between parties"

    def test_recall_propagates_per_ontology_search_failure(self):
        """Corrected contract: a per-ontology recall failure must RE-RAISE,
        not be logged-and-skipped into a partial candidate set. Continuing with
        partial recall silently drops the broken ontology's classes → the subject
        is misclassified 'novel' (reason "No candidates returned from embedding
        search") with no signal. A loud, re-runnable failure beats a silently
        incomplete all-novel grounding. Previously this swallowed the raise and
        returned only the surviving ontology's hit."""
        catalog = MagicMock()
        catalog.search_embeddings.side_effect = [
            RuntimeError("AOSS down"),
            [{"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.9, "text": "Agreement"}],
        ]
        svc = GroundingService(ontology_catalog=catalog, embedding_generator=MagicMock())
        with pytest.raises(RuntimeError, match="AOSS down"):
            svc.ground_table(
                table_name="ledger",
                table_description="",
                columns=[],
                concept_vector=[0.5] * 8,
                model_id="titan",
                grounding_mode="STANDARD",
                ontology_ids=["broken-ont", "fibo"],
            )

    def test_exclude_entity_uri_drops_self_from_candidates(self):
        hits = [
            {"entity_uri": "http://ns/Foo", "ontology_id": "ns", "score": 0.99, "text": "Foo"},
            {"entity_uri": "http://ns/Bar", "ontology_id": "ns", "score": 0.70, "text": "Bar"},
        ]
        svc = _make_service(hits)
        result = svc.ground_table(
            table_name="something",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="STANDARD",
            ontology_ids=["ns"],
            exclude_entity_uri="http://ns/Foo",
        )
        uris = [c.entity_uri for c in result.candidates]
        assert "http://ns/Foo" not in uris
        assert "http://ns/Bar" in uris


# ── ENHANCED mode: real _llm_rerank via mocked Bedrock converse ─────────


class TestEnhancedRerank:
    def test_llm_picks_candidate_and_parses_confidence(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement a deal"},
            {"entity_uri": "http://fibo/Party", "ontology_id": "fibo", "score": 0.5, "text": "Party a person"},
        ]
        svc = _make_service(hits)
        svc._bedrock = _bedrock_returning(
            json.dumps({"choice": "Agreement", "relationship": "closeMatch", "confidence": 0.9, "reason": "matches"})
        )
        result = svc.ground_table(
            table_name="agr_records",
            table_description="agreement records",
            columns=[{"name": "id", "dataType": "int", "description": "pk", "constraint": "PK"}],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        assert result.chosen is not None
        assert result.chosen.entity_uri == "http://fibo/Agreement"
        assert result.relationship == "closeMatch"
        assert result.confidence == pytest.approx(0.9)
        assert result.match_type == "exact"  # 0.9 >= 0.85 with rerank
        # The chosen candidate carries the reranker annotations.
        assert result.chosen.rerank_score == pytest.approx(0.9)
        assert result.chosen.rerank_reason == "matches"

    def test_llm_abstains_none_returns_novel(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement"},
        ]
        svc = _make_service(hits)
        svc._bedrock = _bedrock_returning(
            json.dumps({"choice": "NONE", "relationship": "none", "confidence": 0.0, "reason": "no fit"})
        )
        result = svc.ground_table(
            table_name="occurrence",
            table_description="events",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        assert result.match_type == "novel"
        assert result.chosen is None
        assert result.reason == "no fit"

    def test_llm_choice_not_in_candidates_returns_novel(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement"},
        ]
        svc = _make_service(hits)
        svc._bedrock = _bedrock_returning(
            json.dumps({"choice": "Nonexistent", "relationship": "exactMatch", "confidence": 0.9, "reason": "x"})
        )
        result = svc.ground_table(
            table_name="ledger",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        assert result.match_type == "novel"
        assert result.chosen is None
        assert "not in candidates" in result.reason

    def test_llm_missing_confidence_and_relationship_use_defaults(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement"},
        ]
        svc = _make_service(hits)
        # Neither confidence nor relationship keys present in the LLM response.
        svc._bedrock = _bedrock_returning(json.dumps({"choice": "Agreement", "reason": "x"}))
        result = svc.ground_table(
            table_name="agr_x",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        # Missing confidence → 0.5 → ambiguous tier; missing relationship → relatedMatch.
        assert result.confidence == pytest.approx(0.5)
        assert result.match_type == "ambiguous"
        assert result.relationship == "relatedMatch"

    def test_rerank_parses_markdown_fenced_json(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement"},
        ]
        svc = _make_service(hits)
        fenced = (
            "```json\n"
            + json.dumps({"choice": "Agreement", "relationship": "exactMatch", "confidence": 0.95, "reason": "y"})
            + "\n```"
        )
        svc._bedrock = _bedrock_returning(fenced)
        result = svc.ground_table(
            table_name="agr_x",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        assert result.chosen.entity_uri == "http://fibo/Agreement"
        assert result.confidence == pytest.approx(0.95)

    def test_rerank_non_json_response_returns_novel(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement"},
        ]
        svc = _make_service(hits)
        svc._bedrock = _bedrock_returning("this is not json at all")
        result = svc.ground_table(
            table_name="agr_x",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        assert result.match_type == "novel"
        assert result.reason == "LLM call failed"

    def test_rerank_converse_exception_returns_novel(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement"},
        ]
        svc = _make_service(hits)
        broken = MagicMock()
        broken.converse.side_effect = RuntimeError("bedrock throttled")
        svc._bedrock = broken
        result = svc.ground_table(
            table_name="agr_x",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        assert result.match_type == "novel"

    def test_to_concept_match_after_real_pipeline(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement a deal"},
        ]
        svc = _make_service(hits)
        svc._bedrock = _bedrock_returning(
            json.dumps({"choice": "Agreement", "relationship": "exactMatch", "confidence": 0.92, "reason": "z"})
        )
        result = svc.ground_table(
            table_name="agr_x",
            table_description="",
            columns=[],
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        cm = svc.to_concept_match(result)
        assert cm.matched_class_uri == "http://fibo/Agreement"
        assert cm.matched_ontology_id == "fibo"
        assert cm.similarity == pytest.approx(0.92)
        assert cm.scoring_strategy == "grounding_enhanced"
        assert cm.candidates and cm.candidates[0].entity_uri == "http://fibo/Agreement"


class TestGroundClassPromptFraming:
    def test_ground_class_omits_columns_and_labels_source_class(self):
        hits = [
            {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "score": 0.6, "text": "Agreement"},
        ]
        svc = _make_service(hits)
        captured: dict[str, str] = {}

        def _converse(**kwargs):
            captured["prompt"] = kwargs["messages"][0]["content"][0]["text"]
            captured["system"] = kwargs["system"][0]["text"]
            return {
                "output": {
                    "message": {"content": [{"text": json.dumps({"choice": "NONE", "confidence": 0.0, "reason": "x"})}]}
                }
            }

        svc._bedrock = MagicMock(converse=_converse)
        svc.ground_class(
            class_label="agreement",
            class_description="a mutual understanding",
            concept_vector=[0.5] * 8,
            model_id="titan",
            grounding_mode="ENHANCED",
            ontology_ids=["fibo"],
        )
        assert "SOURCE CLASS:" in captured["prompt"]
        assert "Columns:" not in captured["prompt"]
        assert "source ontology class" in captured["system"].lower()


class TestClassifyScoreTier:
    def test_public_wrapper_reranked_ladder(self):
        assert classify_score_tier(0.9) == "exact"
        assert classify_score_tier(0.7) == "high_confidence"
        assert classify_score_tier(0.5) == "ambiguous"
        assert classify_score_tier(0.2) == "novel"

    def test_none_score_is_novel(self):
        assert classify_score_tier(None) == "novel"

    def test_embedding_ladder_when_no_rerank(self):
        assert classify_score_tier(0.97, has_rerank=False) == "exact"
        assert classify_score_tier(0.85, has_rerank=False, confidence_threshold=0.80) == "high_confidence"
