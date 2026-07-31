# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the cross-repo ontology alignment pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from coa_ontology.inducer.services.alignment_pipeline import (
    AlignmentConfig,
    AlignmentPipeline,
    AlignmentResult,
    build_unified_ontology,
)
from rdflib import OWL, RDF, RDFS, XSD, Namespace
from rdflib.namespace import SKOS

pytestmark = pytest.mark.unit

NS = Namespace("http://ex.org/unified#")


def _pipeline() -> tuple[AlignmentPipeline, MagicMock, MagicMock]:
    gc = MagicMock()
    llm = MagicMock()
    return AlignmentPipeline(graph_client=gc, llm=llm), gc, llm


# ── find_candidates ──────────────────────────────────────────────────


def test_find_candidates_returns_query_results() -> None:
    pipeline, gc, _llm = _pipeline()
    gc.query.return_value = [{"name": "Agreement", "repos": ["a", "b"]}]
    out = pipeline.find_candidates(AlignmentConfig(min_repos=2))
    assert out == [{"name": "Agreement", "repos": ["a", "b"]}]
    # min_repos is threaded into the Cypher query.
    assert ">= 2" in gc.query.call_args[0][0]


# ── gather_context ───────────────────────────────────────────────────


def test_gather_context_assembles_neighborhood() -> None:
    pipeline, gc, _llm = _pipeline()
    gc.query.side_effect = [
        [{"src": "s", "repo": "a", "comment": "c", "sup": "Contract"}],  # instances
        [{"name": "hasParty"}],  # props
        [{"name": "CreditAgreement"}],  # children
        [{"name": "Lease"}],  # siblings for superclass Contract
    ]
    ctx = pipeline.gather_context("Agreement")
    assert ctx["name"] == "Agreement"
    assert ctx["properties"] == ["hasParty"]
    assert ctx["children"] == ["CreditAgreement"]
    assert ctx["siblings"] == ["Lease"]
    assert ctx["superclasses"] == ["Contract"]


def test_gather_context_no_superclass_skips_sibling_query() -> None:
    pipeline, gc, _llm = _pipeline()
    gc.query.side_effect = [
        [{"src": "s", "repo": "a", "comment": "c", "sup": ""}],  # instances (no sup)
        [],  # props
        [],  # children
    ]
    ctx = pipeline.gather_context("Agreement")
    assert ctx["siblings"] == []
    assert ctx["superclasses"] == []
    # Only 3 queries (no sibling lookup) since there is no superclass.
    assert gc.query.call_count == 3


# ── _classify_one ────────────────────────────────────────────────────


async def test_classify_one_returns_result_from_two_repos() -> None:
    pipeline, _gc, llm = _pipeline()
    llm.generate.return_value = "exactMatch|0.9|same concept"
    ctx = {
        "name": "Agreement",
        "instances": [
            {"repo": "a", "comment": "c1", "sup": "Contract"},
            {"repo": "b", "comment": "c2", "sup": "Contract"},
        ],
        "properties": ["hasParty"],
        "children": [],
        "siblings": [],
        "superclasses": ["Contract"],
    }
    result = await pipeline._classify_one(ctx)
    assert result is not None
    assert result.relationship == "exactMatch"
    assert result.confidence == pytest.approx(0.9)
    assert result.reason == "same concept"
    assert result.repo_a == "a"
    assert result.repo_b == "b"


async def test_classify_one_single_repo_returns_none() -> None:
    pipeline, _gc, _llm = _pipeline()
    ctx = {
        "name": "Agreement",
        "instances": [{"repo": "a", "comment": "c1", "sup": ""}],
        "properties": [],
        "children": [],
        "siblings": [],
        "superclasses": [],
    }
    assert await pipeline._classify_one(ctx) is None


async def test_classify_one_llm_failure_returns_none() -> None:
    pipeline, _gc, llm = _pipeline()
    llm.generate.side_effect = RuntimeError("bedrock error")
    ctx = {
        "name": "Agreement",
        "instances": [
            {"repo": "a", "comment": "c1", "sup": "Contract"},
            {"repo": "b", "comment": "c2", "sup": "Contract"},
        ],
        "properties": [],
        "children": [],
        "siblings": [],
        "superclasses": [],
    }
    assert await pipeline._classify_one(ctx) is None


async def test_classify_one_malformed_output_defaults_confidence() -> None:
    pipeline, _gc, llm = _pipeline()
    llm.generate.return_value = "relatedMatch"  # no pipe delimiters
    ctx = {
        "name": "Agreement",
        "instances": [
            {"repo": "a", "comment": "c1", "sup": "Contract"},
            {"repo": "b", "comment": "c2", "sup": "Contract"},
        ],
        "properties": [],
        "children": [],
        "siblings": [],
        "superclasses": [],
    }
    result = await pipeline._classify_one(ctx)
    assert result is not None
    assert result.relationship == "relatedMatch"
    assert result.confidence == 0.5
    assert result.reason == ""


# ── classify_sync ────────────────────────────────────────────────────


def test_classify_sync_wraps_async() -> None:
    pipeline, _gc, llm = _pipeline()
    llm.generate.return_value = "closeMatch|0.8|similar"
    ctx = {
        "name": "Agreement",
        "instances": [
            {"repo": "a", "comment": "c1", "sup": "Contract"},
            {"repo": "b", "comment": "c2", "sup": "Contract"},
        ],
        "properties": [],
        "children": [],
        "siblings": [],
        "superclasses": [],
    }
    result = pipeline.classify_sync(ctx)
    assert result is not None
    assert result.relationship == "closeMatch"


# ── run ──────────────────────────────────────────────────────────────


def test_run_orchestrates_candidates_context_and_classify() -> None:
    pipeline, gc, llm = _pipeline()
    llm.generate.return_value = "exactMatch|0.95|same"

    def query_side_effect(cypher: str, *a, **k):
        if "MultiClass" in cypher and "collect" in cypher:
            return [{"name": "Agreement", "repos": ["a", "b"]}]  # candidates
        if "localName: 'Agreement'" in cypher and "n.source" in cypher:
            return [
                {"repo": "a", "comment": "c1", "sup": "Contract"},
                {"repo": "b", "comment": "c2", "sup": "Contract"},
            ]
        return []

    gc.query.side_effect = query_side_effect
    results = pipeline.run(AlignmentConfig(min_repos=2, workers=1))
    assert len(results) == 1
    assert results[0].class_name == "Agreement"
    assert results[0].relationship == "exactMatch"


# ── build_unified_ontology ───────────────────────────────────────────


def test_build_unified_ontology_emits_classes_props_and_alignments() -> None:
    gc = MagicMock()

    def query_side_effect(cypher: str, *a, **k):
        if "MultiClass" in cypher:
            return [
                {
                    "name": "Agreement",
                    "label": "Agreement",
                    "comment": "A negotiated deal",
                    "sup": "Contract",
                    "repo": "a",
                },
                {"name": "Agreement", "label": "Agreement", "comment": "", "sup": "Contract", "repo": "b"},
            ]
        if "MultiProp" in cypher:
            return [
                {
                    "name": "hasParty",
                    "label": "has party",
                    "pt": "object",
                    "domain": "Agreement",
                    "rng": "Party",
                    "repo": "a",
                },
                {
                    "name": "amount",
                    "label": "amount",
                    "pt": "datatype",
                    "domain": "Agreement",
                    "rng": "decimal",
                    "repo": "a",
                },
            ]
        return []

    gc.query.side_effect = query_side_effect

    alignments = [
        AlignmentResult(
            class_name="Agreement",
            relationship="exactMatch",
            confidence=0.9,
            reason="same",
            repo_a="a",
            repo_b="b",
        )
    ]
    g = build_unified_ontology(gc, alignments, uri_prefix="http://ex.org/unified#")

    assert (NS["Agreement"], RDF.type, OWL.Class) in g
    assert (NS["Agreement"], RDFS.subClassOf, NS["Contract"]) in g
    # Alignment annotations attached.
    assert list(g.objects(NS["Agreement"], NS["alignmentType"]))
    # Object property with class range.
    assert (NS["hasParty"], RDF.type, OWL.ObjectProperty) in g
    assert (NS["hasParty"], RDFS.range, NS["Party"]) in g
    # Datatype property with XSD range.
    assert (NS["amount"], RDF.type, OWL.DatatypeProperty) in g
    assert (NS["amount"], RDFS.range, XSD.decimal) in g
    # Party referenced as an object-property range but never emitted as a class
    # → closure auto-declares it as a class.
    assert (NS["Party"], RDF.type, OWL.Class) in g


def test_build_unified_ontology_skips_names_with_spaces() -> None:
    gc = MagicMock()

    def query_side_effect(cypher: str, *a, **k):
        if "MultiClass" in cypher:
            return [{"name": "bad name", "label": "x", "comment": "", "sup": "", "repo": "a"}]
        return []

    gc.query.side_effect = query_side_effect
    g = build_unified_ontology(gc, [], uri_prefix="http://ex.org/unified#")
    # No class emitted for a name containing a space.
    assert (NS["bad name"], RDF.type, OWL.Class) not in g


def test_build_unified_ontology_declares_annotation_properties() -> None:
    gc = MagicMock()
    gc.query.return_value = []
    g = build_unified_ontology(gc, [], uri_prefix="http://ex.org/unified#")
    assert (NS["alignmentType"], RDF.type, OWL.AnnotationProperty) in g
    assert (NS["alignmentConfidence"], RDF.type, OWL.AnnotationProperty) in g
    assert (NS["alignmentType"], RDFS.label, None) in [(s, p, None) for s, p, _o in g]


def test_build_unified_ontology_binds_skos_namespace() -> None:
    gc = MagicMock()
    gc.query.return_value = []
    g = build_unified_ontology(gc, [], uri_prefix="http://ex.org/unified#")
    prefixes = dict(g.namespaces())
    assert str(prefixes["skos"]) == str(SKOS)
