# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for request/response models."""

import pytest
from coa_serve.models import (
    ConfidenceScore,
    InvokeRequest,
    InvokeResponse,
    QueryResult,
    TraceStep,
)
from pydantic import ValidationError


@pytest.mark.unit
class TestInvokeRequest:
    def test_valid_request(self):
        req = InvokeRequest(query="What is revenue?", namespace="demo")
        assert req.query == "What is revenue?"
        assert req.namespace == "demo"
        assert req.profile == {}
        assert req.options == {}

    def test_request_with_all_fields(self):
        req = InvokeRequest(
            query="test",
            namespace="ns1",
            profile={"user_id": "u1"},
            options={"tierOverride": 1},
        )
        assert req.profile == {"user_id": "u1"}
        assert req.options == {"tierOverride": 1}

    def test_query_max_length(self):
        req = InvokeRequest(query="x" * 4000, namespace="demo")
        assert len(req.query) == 4000

    def test_query_exceeds_max_length(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="x" * 4001, namespace="demo")

    def test_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="", namespace="demo")

    def test_whitespace_only_query_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="   ", namespace="demo")

    def test_tabs_and_newlines_only_query_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="\t\n  \r\n", namespace="demo")

    def test_query_with_leading_trailing_whitespace_stripped(self):
        req = InvokeRequest(query="  hello world  ", namespace="demo")
        assert req.query == "hello world"

    def test_missing_query_raises(self):
        with pytest.raises(ValidationError):
            InvokeRequest(namespace="demo")

    def test_missing_namespace_raises(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test")

    def test_empty_namespace_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="")

    def test_namespace_with_spaces_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="bad namespace")

    def test_namespace_with_special_chars_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="ns/../../etc")

    def test_valid_namespace_patterns(self):
        for ns in ["demo", "my-namespace", "ns_123", "Production-01"]:
            req = InvokeRequest(query="test", namespace=ns)
            assert req.namespace == ns

    def test_namespace_at_max_length(self):
        ns = "a" * 128
        req = InvokeRequest(query="test", namespace=ns)
        assert len(req.namespace) == 128

    def test_namespace_exceeds_max_length(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="a" * 129)

    def test_namespace_leading_hyphen_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="-leading")

    def test_namespace_leading_underscore_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="_leading")

    def test_namespace_with_null_byte_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="ns\x00evil")

    def test_namespace_with_unicode_rejected(self):
        with pytest.raises(ValidationError):
            InvokeRequest(query="test", namespace="ns​evil")


@pytest.mark.unit
class TestRetrieverStrategyValidation:
    """Model-layer validation of ``options.retrieverStrategy`` (task 4)."""

    def test_valid_retriever_strategy_accepted(self):
        from coa_serve.lexical.strategies import RetrieverStrategy

        for strategy in RetrieverStrategy:
            req = InvokeRequest(
                query="test",
                namespace="demo",
                options={"retrieverStrategy": strategy.value},
            )
            assert req.options["retrieverStrategy"] == strategy.value

    def test_default_strategy_value_accepted(self):
        req = InvokeRequest(
            query="test",
            namespace="demo",
            options={"retrieverStrategy": "chunk_based_semantic"},
        )
        assert req.options["retrieverStrategy"] == "chunk_based_semantic"

    def test_invalid_retriever_strategy_raises(self):
        with pytest.raises(ValidationError):
            InvokeRequest(
                query="test",
                namespace="demo",
                options={"retrieverStrategy": "not-a-real-strategy"},
            )

    def test_empty_retriever_strategy_raises(self):
        with pytest.raises(ValidationError):
            InvokeRequest(
                query="test",
                namespace="demo",
                options={"retrieverStrategy": ""},
            )

    def test_absent_retriever_strategy_is_valid(self):
        # Key absent entirely -> valid.
        req = InvokeRequest(query="test", namespace="demo", options={})
        assert "retrieverStrategy" not in req.options

    def test_other_options_keys_unaffected(self):
        # Absence of retrieverStrategy among other option keys is still valid,
        # and the key stays inside ``options`` (no new top-level field).
        req = InvokeRequest(
            query="test",
            namespace="demo",
            options={"tierOverride": 3},
        )
        assert req.options == {"tierOverride": 3}


@pytest.mark.unit
class TestConfidenceScore:
    def test_valid_score(self):
        cs = ConfidenceScore(score=0.85, rationale="NL-to-SPARQL")
        assert cs.score == 0.85

    def test_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            ConfidenceScore(score=1.5, rationale="too high")

    def test_negative_score_rejected(self):
        with pytest.raises(ValidationError):
            ConfidenceScore(score=-0.1, rationale="negative")

    def test_boundary_scores(self):
        assert ConfidenceScore(score=0.0, rationale="").score == 0.0
        assert ConfidenceScore(score=1.0, rationale="").score == 1.0


@pytest.mark.unit
class TestTraceStep:
    def test_minimal_trace(self):
        ts = TraceStep(step="metric_match", status="success")
        assert ts.duration_ms == 0
        assert ts.detail is None

    def test_full_trace(self):
        ts = TraceStep(
            step="llm_call",
            status="success",
            duration_ms=1500,
            detail="confidence=0.85",
            tool_used="bedrock_converse",
        )
        assert ts.duration_ms == 1500
        assert ts.tool_used == "bedrock_converse"

    def test_alias_serialization(self):
        ts = TraceStep(step="test", status="ok", duration_ms=10)
        data = ts.model_dump(by_alias=True)
        assert "durationMs" in data


@pytest.mark.unit
class TestQueryResult:
    def test_minimal_result(self):
        result = QueryResult(
            tier=1,
            confidence=ConfidenceScore(score=1.0, rationale="exact match"),
            trace=[TraceStep(step="metric_match", status="success", duration_ms=5)],
        )
        assert result.tier == 1
        assert result.partial is False

    def test_tier2_result_with_all_fields(self):
        result = QueryResult(
            tier=2,
            confidence=ConfidenceScore(score=0.85, rationale="NL-to-SPARQL"),
            result_rows=[{"id": "1", "amount": "5000"}],
            query_used="SELECT id, amount FROM claims",
            sparql_generated="SELECT ?x WHERE { ?x a :Claim }",
            trace=[TraceStep(step="vkg", status="success")],
            ontology_version="v1",
            data_sources=["claims"],
        )
        assert result.result_rows == [{"id": "1", "amount": "5000"}]
        assert result.ontology_version == "v1"

    def test_tier3_result_with_synthesis(self):
        result = QueryResult(
            tier=3,
            confidence=ConfidenceScore(score=0.7, rationale="agentic synthesis"),
            synthesized_answer="The SLA is 10 days.",
            supporting_content=[{"chunkId": "c1", "text": "..."}],
            graph_context={"entities": []},
            trace=[TraceStep(step="synthesize", status="success")],
        )
        assert result.synthesized_answer == "The SLA is 10 days."

    def test_populate_by_name(self):
        result = QueryResult(
            tier=2,
            confidence=ConfidenceScore(score=0.9),
            resultRows=[{"a": "b"}],
            queryUsed="SELECT 1",
            trace=[TraceStep(step="t", status="s")],
        )
        assert result.result_rows == [{"a": "b"}]
        assert result.query_used == "SELECT 1"


@pytest.mark.unit
class TestInvokeResponse:
    def test_response_wraps_result(self):
        result = QueryResult(
            tier=0,
            confidence=ConfidenceScore(score=0.0),
            trace=[TraceStep(step="stub", status="success")],
        )
        response = InvokeResponse(result=result, requestId="req-123")
        assert response.requestId == "req-123"
        assert response.result.tier == 0

    def test_optional_fields_default_none(self):
        result = QueryResult(
            tier=0,
            confidence=ConfidenceScore(score=0.0),
            trace=[],
        )
        response = InvokeResponse(result=result)
        assert response.requestId is None
        assert response.sessionId is None
