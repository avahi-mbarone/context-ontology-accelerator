# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OntopStrategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from coa_serve.clients.base import VectorHit as BaseVectorHit
from coa_serve.exceptions import AccessDeniedError
from coa_serve.tier2.ontop.strategy import OntopStrategy, _is_retryable_vkg_error
from coa_serve.tier2.strategy import StrategyContext, StrategyOption, StrategyResult
from coa_serve.trace import TraceCollector

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_sparql_result(*, valid: bool = True, sparql: str = "SELECT ?x WHERE { ?x a :Foo }", confidence: float = 0.8):
    """Build a mock TranslationResult."""
    result = MagicMock()
    result.valid = valid
    result.sparql = sparql if valid else None
    result.confidence = confidence
    result.trace_steps = []
    return result


def _make_tier2_result(*, error: str | None = None, firewall_denied: bool = False, has_query_result: bool = True):
    """Build a mock Tier2Result from vkg_translator.resolve."""
    result = MagicMock()
    result.error = error
    # Mirror the real translator: it always records a t2.vkg.compile step
    # (success or error) in trace_steps. On a VKG error, that step is the
    # authoritative record of why translation failed.
    compile_step = MagicMock()
    compile_step.step = "t2.vkg.compile"
    compile_step.status = "error" if error else "success"
    compile_step.duration_ms = 5
    compile_step.detail = {"error": error} if error else {"dialect": "ansi"}
    result.trace_steps = [compile_step]

    # Firewall result
    fw = MagicMock()
    fw.denied = firewall_denied
    fw.reason = "policy violation" if firewall_denied else None
    result.firewall_result = fw

    # VKG result
    vkg = MagicMock()
    vkg.sql = "SELECT col FROM tbl"
    result.vkg_result = vkg

    # Query result
    if has_query_result and not error:
        qr = MagicMock()
        qr.rows = [{"col": "val"}]
        qr.columns = ["col"]
        qr.row_count = 1
        qr.truncated = False
        result.query_result = qr
    else:
        result.query_result = None

    return result


def _make_context(*, embedding: list[float] | None = None) -> StrategyContext:
    return StrategyContext(
        embedding=embedding,
        profile={"userId": "user-1"},
        options={"maxResults": 100, "dataSourceId": "ds-1"},
        trace=TraceCollector(),
    )


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestIsRetryableVkgError:
    def test_retryable_patterns_detected(self):
        assert _is_retryable_vkg_error("Cannot translate the SPARQL fragment")
        assert _is_retryable_vkg_error("Unsupported SPARQL feature detected")
        assert _is_retryable_vkg_error("Parse error at line 5")
        assert _is_retryable_vkg_error("Nested subquery not supported")
        assert _is_retryable_vkg_error("Translation error in WHERE clause")
        assert _is_retryable_vkg_error("Unsupported expression type")
        assert _is_retryable_vkg_error("Illegal aggregate in projection")

    def test_non_retryable_errors_rejected(self):
        assert not _is_retryable_vkg_error("Connection timeout")
        assert not _is_retryable_vkg_error("500 Internal Server Error")
        assert not _is_retryable_vkg_error("Authentication failed")


@pytest.mark.unit
class TestOntopStrategyResolve:
    @pytest.fixture
    def nl_to_sparql(self):
        return AsyncMock()

    @pytest.fixture
    def vkg_translator(self):
        return AsyncMock()

    @pytest.fixture
    def vector_client(self):
        return AsyncMock()

    @pytest.fixture
    def strategy(self, nl_to_sparql, vkg_translator, vector_client):
        return OntopStrategy(
            nl_to_sparql=nl_to_sparql,
            vkg_translator=vkg_translator,
            vector_client=vector_client,
            oss_ontology_index="test-index",
        )

    @pytest.mark.asyncio
    async def test_success_path_returns_strategy_result_with_ontop_assembly(
        self, strategy, nl_to_sparql, vkg_translator
    ):
        nl_to_sparql.translate.return_value = _make_sparql_result()
        vkg_translator.resolve.return_value = _make_tier2_result()
        context = _make_context()

        result = await strategy.resolve("How many orders?", "ns1", context)

        assert result is not None
        assert isinstance(result, StrategyResult)
        assert result.ontop_assembly is True
        assert result.strategy_name == StrategyOption.ONTOP
        assert result.sql == "SELECT col FROM tbl"
        assert result.rows == [{"col": "val"}]
        assert result.columns == ["col"]
        assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_sparql_translation_substeps_replayed(self, strategy, nl_to_sparql, vkg_translator):
        """The NL→SPARQL sub-steps (context/translate/validate) must be replayed
        into the outer trace so the VKG pipeline is fully visible."""
        sparql = _make_sparql_result()
        sparql.trace_steps = [
            {"step": "t2.vkg.context", "status": "success", "durationMs": 30, "detail": "12 classes"},
            {"step": "t2.vkg.translate", "status": "success", "durationMs": 200, "detail": "confidence=0.80"},
            {"step": "t2.vkg.validate", "status": "success", "durationMs": 5, "detail": "passed"},
        ]
        nl_to_sparql.translate.return_value = sparql
        vkg_translator.resolve.return_value = _make_tier2_result()
        context = _make_context()

        await strategy.resolve("How many orders?", "ns1", context)

        replayed = {s.step for s in context.trace.steps}
        assert {"t2.vkg.context", "t2.vkg.translate", "t2.vkg.validate"}.issubset(replayed)

    @pytest.mark.asyncio
    async def test_sparql_invalid_returns_none(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result(valid=False)
        context = _make_context()

        result = await strategy.resolve("nonsense query", "ns1", context)

        assert result is None
        vkg_translator.resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_vkg_exception_retryable_retries_and_succeeds(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result()

        # First VKG call raises retryable error
        vkg_translator.resolve.side_effect = [
            Exception("Cannot translate the SPARQL fragment"),
            _make_tier2_result(),
        ]
        # Retry re-translation also valid
        nl_to_sparql.translate.side_effect = [
            _make_sparql_result(),
            _make_sparql_result(sparql="SELECT ?y WHERE { ?y a :Bar }"),
        ]
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is not None
        assert result.ontop_assembly is True
        # Verify retry was invoked (translate called twice)
        assert nl_to_sparql.translate.call_count == 2

    @pytest.mark.asyncio
    async def test_vkg_exception_non_retryable_returns_none_immediately(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result()
        vkg_translator.resolve.side_effect = Exception("Connection timeout")
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        # Only the initial translate call, no retry
        assert nl_to_sparql.translate.call_count == 1

    @pytest.mark.asyncio
    async def test_vkg_result_based_error_with_vkg_keyword_triggers_retry(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result()

        # First call returns result with VKG error
        first_result = _make_tier2_result(error="VKG translation failed: unsupported join")
        # Second call (retry) succeeds
        second_result = _make_tier2_result()
        vkg_translator.resolve.side_effect = [first_result, second_result]

        # Re-translation for retry also valid; its sub-steps must be replayed.
        retry_sparql = _make_sparql_result(sparql="SELECT ?z WHERE { ?z a :Baz }")
        retry_sparql.trace_steps = [
            {"step": "t2.vkg.context", "status": "success", "durationMs": 25, "detail": "retry ctx"},
            {"step": "t2.vkg.translate", "status": "success", "durationMs": 180, "detail": "confidence=0.70"},
            {"step": "t2.vkg.validate", "status": "success", "durationMs": 4, "detail": "passed"},
        ]
        nl_to_sparql.translate.side_effect = [_make_sparql_result(), retry_sparql]
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is not None
        assert result.ontop_assembly is True
        assert nl_to_sparql.translate.call_count == 2
        assert vkg_translator.resolve.call_count == 2
        # The first (result-based) failure must be visible as an explicit error
        # step so the retry isn't shown in the trace without its cause. It is the
        # Ontop compile step (t2.vkg.compile), distinct from the LLM translate step.
        first_fail = [s for s in context.trace.steps if s.step == "t2.vkg.compile" and s.status == "error"]
        assert first_fail, "expected a t2.vkg.compile/error step for the first attempt"
        # The retry's re-translation sub-steps are replayed into the outer trace
        # (only the retry sparql carries trace_steps in this test).
        validate_steps = [s for s in context.trace.steps if s.step == "t2.vkg.validate"]
        assert len(validate_steps) == 1, "expected the retry's validate sub-step to be replayed"

    @pytest.mark.asyncio
    async def test_retry_also_fails_surfaces_both_compile_steps(self, strategy, nl_to_sparql, vkg_translator):
        """When the retry's VKG translation also fails, BOTH compile failures
        must be visible — the first attempt's and the retry's — so the trace
        explains the whole retry loop (regression for the dropped-retry-compile bug)."""
        nl_to_sparql.translate.return_value = _make_sparql_result()
        # Both attempts return a VKG translation error.
        vkg_translator.resolve.side_effect = [
            _make_tier2_result(error="vkg_translation_error"),
            _make_tier2_result(error="vkg_translation_error"),
        ]
        nl_to_sparql.translate.side_effect = [
            _make_sparql_result(),
            _make_sparql_result(sparql="SELECT ?z WHERE { ?z a :Baz }"),
        ]
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        compile_errors = [s for s in context.trace.steps if s.step == "t2.vkg.compile" and s.status == "error"]
        # Two compile failures: first attempt + retry attempt.
        assert len(compile_errors) == 2, f"expected 2 compile/error steps, got {len(compile_errors)}"
        retry_failed = [s for s in context.trace.steps if s.step == "t2.vkg.retry" and s.status == "failed"]
        assert retry_failed, "expected a t2.vkg.retry/failed step"

    @pytest.mark.asyncio
    async def test_retry_retranslation_fails_validation_returns_none(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result()
        vkg_translator.resolve.side_effect = Exception("Cannot translate the fragment")

        # Retry translation returns invalid result
        nl_to_sparql.translate.side_effect = [
            _make_sparql_result(),
            _make_sparql_result(valid=False),
        ]
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None

    @pytest.mark.asyncio
    async def test_retry_second_vkg_call_also_fails_returns_none(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result()

        # First VKG call raises retryable error
        # Second VKG call also raises
        vkg_translator.resolve.side_effect = [
            Exception("Cannot translate the SPARQL fragment"),
            Exception("Still cannot translate"),
        ]
        # Retry translation valid
        nl_to_sparql.translate.side_effect = [
            _make_sparql_result(),
            _make_sparql_result(sparql="SELECT ?y WHERE { ?y a :Bar }"),
        ]
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None

    @pytest.mark.asyncio
    async def test_firewall_denied_raises_access_denied_error(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result()
        vkg_translator.resolve.return_value = _make_tier2_result(firewall_denied=True)
        context = _make_context()

        with pytest.raises(AccessDeniedError):
            await strategy.resolve("query", "ns1", context)

    @pytest.mark.asyncio
    async def test_vkg_returns_query_result_with_error_returns_none(self, strategy, nl_to_sparql, vkg_translator):
        nl_to_sparql.translate.return_value = _make_sparql_result()
        # Has query_result but also has a non-vkg error
        tier2 = _make_tier2_result()
        tier2.error = "execution timeout"
        context = _make_context()

        vkg_translator.resolve.return_value = tier2

        result = await strategy.resolve("query", "ns1", context)

        assert result is None


@pytest.mark.unit
class TestOntopStrategyVectorHits:
    @pytest.fixture
    def nl_to_sparql(self):
        return AsyncMock()

    @pytest.fixture
    def vkg_translator(self):
        return AsyncMock()

    @pytest.fixture
    def vector_client(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_vector_hits_returned_and_filtered(self, nl_to_sparql, vkg_translator, vector_client):
        strategy = OntopStrategy(
            nl_to_sparql=nl_to_sparql,
            vkg_translator=vkg_translator,
            vector_client=vector_client,
            oss_ontology_index="test-index",
        )

        # Vector search returns mixed entity types
        vector_client.search.return_value = [
            BaseVectorHit(id="1", text="ClassA", score=0.9, metadata={"entity_type": "class", "entity_uri": "uri:A"}),
            BaseVectorHit(
                id="2", text="PropB", score=0.85, metadata={"entity_type": "property", "entity_uri": "uri:B"}
            ),
            BaseVectorHit(id="3", text="MetricC", score=0.8, metadata={"entity_type": "metric", "entity_uri": "uri:C"}),
            BaseVectorHit(id="4", text="Unknown", score=0.7, metadata={"entity_type": "unknown"}),
        ]
        nl_to_sparql.translate.return_value = _make_sparql_result(valid=False)

        context = _make_context(embedding=[0.1] * 10)

        await strategy.resolve("query", "ns1", context)

        # Verify translate was called with filtered vector_hits
        call_kwargs = nl_to_sparql.translate.call_args[1]
        hits = call_kwargs["vector_hits"]
        # Only class, property, metric are kept; "unknown" is filtered out
        assert len(hits) == 3
        assert hits[0].type == "ontology_class"
        assert hits[1].type == "ontology_property"
        assert hits[2].type == "metric"

    @pytest.mark.asyncio
    async def test_vector_search_exception_returns_none_gracefully(self, nl_to_sparql, vkg_translator, vector_client):
        strategy = OntopStrategy(
            nl_to_sparql=nl_to_sparql,
            vkg_translator=vkg_translator,
            vector_client=vector_client,
            oss_ontology_index="test-index",
        )

        vector_client.search.side_effect = Exception("OpenSearch unavailable")
        nl_to_sparql.translate.return_value = _make_sparql_result(valid=False)

        context = _make_context(embedding=[0.1] * 10)

        # Should not raise — just returns None from invalid sparql
        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        # translate was still called (with vector_hits=None fallback)
        nl_to_sparql.translate.assert_called_once()
        call_kwargs = nl_to_sparql.translate.call_args[1]
        assert call_kwargs["vector_hits"] is None

    @pytest.mark.asyncio
    async def test_no_vector_client_vector_hits_is_none(self, nl_to_sparql, vkg_translator):
        strategy = OntopStrategy(
            nl_to_sparql=nl_to_sparql,
            vkg_translator=vkg_translator,
            vector_client=None,
            oss_ontology_index="test-index",
        )

        nl_to_sparql.translate.return_value = _make_sparql_result()
        vkg_translator.resolve.return_value = _make_tier2_result()
        context = _make_context(embedding=[0.1] * 10)

        result = await strategy.resolve("query", "ns1", context)

        assert result is not None
        # translate should be called with vector_hits=None
        call_kwargs = nl_to_sparql.translate.call_args[1]
        assert call_kwargs["vector_hits"] is None

    @pytest.mark.asyncio
    async def test_no_embedding_skips_vector_fetch(self, nl_to_sparql, vkg_translator, vector_client):
        strategy = OntopStrategy(
            nl_to_sparql=nl_to_sparql,
            vkg_translator=vkg_translator,
            vector_client=vector_client,
            oss_ontology_index="test-index",
        )

        nl_to_sparql.translate.return_value = _make_sparql_result()
        vkg_translator.resolve.return_value = _make_tier2_result()
        context = _make_context(embedding=None)

        result = await strategy.resolve("query", "ns1", context)

        assert result is not None
        vector_client.search.assert_not_called()
        call_kwargs = nl_to_sparql.translate.call_args[1]
        assert call_kwargs["vector_hits"] is None
