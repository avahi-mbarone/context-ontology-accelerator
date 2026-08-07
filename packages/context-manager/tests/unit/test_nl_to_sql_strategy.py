# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for NLtoSQLStrategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from coa_serve.exceptions import AccessDeniedError
from coa_serve.tier2.nl_to_sql.strategy import NLtoSQLStrategy
from coa_serve.tier2.strategy import MAX_RESULT_ROWS, StrategyContext, StrategyOption, StrategyResult
from coa_serve.trace import TraceCollector

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_nl_to_sql_result(
    *,
    sql: str = "SELECT count(*) FROM orders",
    error: str | None = None,
    confidence: float = 0.85,
    retrieved_tables: list[str] | None = None,
    expanded_tables: list[str] | None = None,
    data_source_id: str = "ds-1",
):
    """Build a mock NLtoSQLResult."""
    result = MagicMock()
    result.sql = sql
    result.error = error
    result.confidence = confidence
    result.retrieved_tables = retrieved_tables or ["orders"]
    result.expanded_tables = expanded_tables or ["orders", "customers"]
    result.trace_steps = []
    result.data_source_id = data_source_id
    result.ddl_context = "CREATE TABLE orders (id int);"
    return result


def _make_firewall_result(*, denied: bool = False, authorized_sql: str = "", reason: str | None = None):
    """Build a mock FirewallResult."""
    result = MagicMock()
    result.denied = denied
    result.authorized_sql = authorized_sql or "SELECT count(*) FROM orders"
    result.reason = reason
    return result


def _make_exec_result(*, rows: list[dict] | None = None, columns: list[str] | None = None, row_count: int = 1):
    """Build a mock QueryResult."""
    result = MagicMock()
    result.rows = rows or [{"count": 42}]
    result.columns = columns or ["count"]
    result.row_count = row_count
    result.truncated = False
    return result


def _make_context() -> StrategyContext:
    return StrategyContext(
        embedding=[0.1] * 10,
        profile={"userId": "user-1"},
        options={"maxResults": 100, "dataSourceId": "ds-1", "evidence": "some evidence text"},
        trace=TraceCollector(),
    )


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestNLtoSQLStrategyResolve:
    @pytest.fixture
    def sql_generator(self):
        return AsyncMock()

    @pytest.fixture
    def firewall(self):
        return MagicMock()

    @pytest.fixture
    def query_executor(self):
        return AsyncMock()

    @pytest.fixture
    def strategy(self, sql_generator, firewall, query_executor):
        return NLtoSQLStrategy(
            sql_generator=sql_generator,
            firewall=firewall,
            query_executor=query_executor,
            oss_ontology_index="test-index",
        )

    @pytest.mark.asyncio
    async def test_success_path_returns_strategy_result(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.return_value = _make_exec_result()
        context = _make_context()

        result = await strategy.resolve("How many orders?", "ns1", context)

        assert result is not None
        assert isinstance(result, StrategyResult)
        assert result.strategy_name == StrategyOption.NL_TO_SQL
        assert result.sql == "SELECT count(*) FROM orders"
        assert result.rows == [{"count": 42}]
        assert result.columns == ["count"]
        assert result.confidence == 0.85
        assert result.row_count == 1
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_correct_strategy_result_fields(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result(
            retrieved_tables=["orders", "products"],
            expanded_tables=["orders", "products", "categories"],
            data_source_id="my-ds",
        )
        firewall.evaluate.return_value = _make_firewall_result(authorized_sql="SELECT 1 FROM orders")
        query_executor.execute.return_value = _make_exec_result(row_count=5)
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result.retrieved_tables == ["orders", "products"]
        assert result.expanded_tables == ["orders", "products", "categories"]
        assert result.data_source_id == "my-ds"
        assert result.row_count == 5

    @pytest.mark.asyncio
    async def test_sql_generation_error_returns_none(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result(sql="", error="LLM timeout")
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        firewall.evaluate.assert_not_called()
        query_executor.execute.assert_not_called()
        # A genuine generation failure is an error step.
        gen = [s for s in context.trace.steps if s.step == "t2.sql.generate"]
        assert gen and gen[0].status == "error"

    @pytest.mark.asyncio
    async def test_retrieve_failed_is_skipped_not_error(self, strategy, sql_generator, firewall, query_executor):
        # A retrieval-backend failure (vector proxy/index unavailable) means the
        # NL→SQL strategy could not start — it's a graceful SKIP with fallthrough
        # to VKG, not an error. Otherwise every query shows a red step when only
        # the optional NL→SQL retrieval path is degraded.
        sql_generator.generate.return_value = _make_nl_to_sql_result(
            sql="", error="retrieve_failed: Vector search proxy returned an error"
        )
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        gen = [s for s in context.trace.steps if s.step == "t2.sql.generate"]
        assert gen and gen[0].status == "skipped", "retrieve_failed should record a skipped step, not error"

    @pytest.mark.asyncio
    async def test_empty_sql_generated_returns_none(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result(sql="", error=None)
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        firewall.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_firewall_denied_raises_access_denied_error(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result(denied=True, reason="Table not in allowlist")
        context = _make_context()

        with pytest.raises(AccessDeniedError):
            await strategy.resolve("query", "ns1", context)

        query_executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsafe_sql_records_firewall_error_and_returns_none(
        self, strategy, sql_generator, firewall, query_executor
    ):
        from coa_serve.tier2.sql_firewall import UnsafeSQLError

        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.side_effect = UnsafeSQLError("Only SELECT statements are allowed, got: Union")
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        # Falls through (returns None) so the next strategy can try, but the
        # failure must be visible in the trace as an error firewall step.
        assert result is None
        query_executor.execute.assert_not_called()
        fw_err = [s for s in context.trace.steps if s.step == "t2.sql.firewall" and s.status == "error"]
        assert fw_err, "expected a t2.sql.firewall/error step for unsafe SQL"

    @pytest.mark.asyncio
    async def test_firewall_allows_with_rewritten_sql_executes_authorized_sql(
        self, strategy, sql_generator, firewall, query_executor
    ):
        sql_generator.generate.return_value = _make_nl_to_sql_result(sql="SELECT * FROM orders")
        rewritten_sql = "SELECT id, total FROM orders"
        firewall.evaluate.return_value = _make_firewall_result(authorized_sql=rewritten_sql)
        query_executor.execute.return_value = _make_exec_result()
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        # The executor should receive the rewritten (authorized) SQL
        execute_call_args = query_executor.execute.call_args
        assert execute_call_args[0][0] == rewritten_sql
        # The result should also contain the authorized SQL
        assert result.sql == rewritten_sql

    @pytest.mark.asyncio
    async def test_no_query_executor_returns_none(self, sql_generator, firewall):
        strategy = NLtoSQLStrategy(
            sql_generator=sql_generator,
            firewall=firewall,
            query_executor=None,
        )
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None

    @pytest.mark.asyncio
    async def test_execution_failure_returns_none(self, strategy, sql_generator, firewall, query_executor):
        # Both shots fail to execute → strategy falls through (returns None). With
        # the default 2-shot cap, the corrective regeneration is attempted once.
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        sql_generator.correct.return_value = ("SELECT count(*) FROM orders", 0.8)
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.side_effect = Exception("Database connection lost")
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        # First shot failed → one corrective regeneration attempted.
        sql_generator.correct.assert_called_once()
        # Two execution attempts total (shot 1 + shot 2), bounded by max_shots.
        assert query_executor.execute.call_count == 2

    # ── Two-shot self-correction ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_correction_recovers_after_execution_error(self, strategy, sql_generator, firewall, query_executor):
        # Shot 1 SQL raises a DB error; the LLM correction produces valid SQL that
        # executes on shot 2 → the strategy returns the corrected result.
        sql_generator.generate.return_value = _make_nl_to_sql_result(sql="SELECT bad FROM orders")
        sql_generator.correct.return_value = ("SELECT count(*) FROM orders", 0.9)
        firewall.evaluate.side_effect = [
            _make_firewall_result(authorized_sql="SELECT bad FROM orders"),
            _make_firewall_result(authorized_sql="SELECT count(*) FROM orders"),
        ]
        query_executor.execute.side_effect = [
            Exception('column "bad" does not exist'),
            _make_exec_result(row_count=7),
        ]
        context = _make_context()

        result = await strategy.resolve("How many orders?", "ns1", context)

        assert result is not None
        assert result.sql == "SELECT count(*) FROM orders"
        assert result.row_count == 7
        # correct() got the verbatim engine error + prior SQL + reused schema.
        args, kwargs = sql_generator.correct.call_args
        assert "does not exist" in kwargs["execution_error"]
        assert kwargs["failed_sql"] == "SELECT bad FROM orders"
        # question + ddl_context are passed positionally.
        assert args[0] == "How many orders?"
        assert args[1] == "CREATE TABLE orders (id int);"

    @pytest.mark.asyncio
    async def test_no_correction_when_first_shot_succeeds(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.return_value = _make_exec_result()
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is not None
        sql_generator.correct.assert_not_called()
        assert query_executor.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_result_triggers_correction_and_recovers(
        self, strategy, sql_generator, firewall, query_executor
    ):
        # Shot 1 executes cleanly but returns ZERO rows (weak "likely wrong"
        # signal in text-to-SQL) → correction shot produces SQL that returns
        # rows. The non-empty corrected result wins.
        sql_generator.generate.return_value = _make_nl_to_sql_result(sql="SELECT * FROM orders WHERE region='xx'")
        sql_generator.correct.return_value = ("SELECT * FROM orders WHERE region='XX'", 0.8)
        firewall.evaluate.side_effect = [
            _make_firewall_result(authorized_sql="SELECT * FROM orders WHERE region='xx'"),
            _make_firewall_result(authorized_sql="SELECT * FROM orders WHERE region='XX'"),
        ]
        query_executor.execute.side_effect = [
            _make_exec_result(rows=[], row_count=0),
            _make_exec_result(rows=[{"id": 1}], row_count=3),
        ]
        context = _make_context()

        result = await strategy.resolve("orders in XX?", "ns1", context)

        assert result is not None
        assert result.row_count == 3
        sql_generator.correct.assert_called_once()
        # The empty-result feedback (not a DB exception) was fed to correct().
        _, kwargs = sql_generator.correct.call_args
        assert "ZERO rows" in kwargs["execution_error"]

    @pytest.mark.asyncio
    async def test_empty_result_kept_as_fallback_when_correction_still_empty(
        self, strategy, sql_generator, firewall, query_executor
    ):
        # Both shots return zero rows → the clean empty result is preserved
        # (never downgraded to a hard miss), so a genuinely-empty answer stands.
        sql_generator.generate.return_value = _make_nl_to_sql_result(sql="SELECT * FROM orders WHERE 1=0")
        sql_generator.correct.return_value = ("SELECT * FROM orders WHERE 2=0", 0.7)
        firewall.evaluate.side_effect = [
            _make_firewall_result(authorized_sql="SELECT * FROM orders WHERE 1=0"),
            _make_firewall_result(authorized_sql="SELECT * FROM orders WHERE 2=0"),
        ]
        query_executor.execute.side_effect = [
            _make_exec_result(rows=[], row_count=0),
            _make_exec_result(rows=[], row_count=0),
        ]
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is not None
        assert result.row_count == 0
        assert query_executor.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_result_no_correction_when_max_shots_one(self, sql_generator, firewall, query_executor):
        # max_shots=1: an empty result is returned as-is (no correction attempt).
        strategy = NLtoSQLStrategy(
            sql_generator=sql_generator,
            firewall=firewall,
            query_executor=query_executor,
            oss_ontology_index="test-index",
            max_shots=1,
        )
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.return_value = _make_exec_result(rows=[], row_count=0)
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is not None
        assert result.row_count == 0
        sql_generator.correct.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_shots_one_disables_correction(self, sql_generator, firewall, query_executor):
        # max_shots=1 → pure one-shot; a failed execution returns None with no
        # correction attempt (backwards-compatible with the pre-two-shot path).
        strategy = NLtoSQLStrategy(
            sql_generator=sql_generator,
            firewall=firewall,
            query_executor=query_executor,
            oss_ontology_index="test-index",
            max_shots=1,
        )
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.side_effect = Exception("boom")
        context = _make_context()

        result = await strategy.resolve("query", "ns1", context)

        assert result is None
        sql_generator.correct.assert_not_called()
        assert query_executor.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_execution_passes_correct_parameters(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result(data_source_id="custom-ds")
        authorized_sql = "SELECT 1 FROM t"
        firewall.evaluate.return_value = _make_firewall_result(authorized_sql=authorized_sql)
        query_executor.execute.return_value = _make_exec_result()
        context = _make_context()
        context.options["maxResults"] = 500

        await strategy.resolve("query", "ns1", context)

        query_executor.execute.assert_called_once_with(
            authorized_sql,
            namespace="ns1",
            data_source_id="custom-ds",
            max_rows=500,
            timeout_seconds=35,
        )

    @pytest.mark.asyncio
    async def test_max_rows_capped_at_system_max(self, strategy, sql_generator, firewall, query_executor):
        """Cap is MAX_RESULT_ROWS (raised 1000 -> 10_000 once Athena results paginate)."""
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.return_value = _make_exec_result()
        context = _make_context()
        context.options["maxResults"] = 5000  # below the new cap -> passes through

        await strategy.resolve("query", "ns1", context)

        call_kwargs = query_executor.execute.call_args[1]
        assert call_kwargs["max_rows"] == 5000

    @pytest.mark.asyncio
    async def test_max_rows_capped_above_system_max(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.return_value = _make_exec_result()
        context = _make_context()
        context.options["maxResults"] = MAX_RESULT_ROWS * 10

        await strategy.resolve("query", "ns1", context)

        call_kwargs = query_executor.execute.call_args[1]
        assert call_kwargs["max_rows"] == MAX_RESULT_ROWS

    @pytest.mark.asyncio
    async def test_evidence_truncated_to_500_chars(self, strategy, sql_generator, firewall, query_executor):
        sql_generator.generate.return_value = _make_nl_to_sql_result()
        firewall.evaluate.return_value = _make_firewall_result()
        query_executor.execute.return_value = _make_exec_result()
        context = _make_context()
        context.options["evidence"] = "x" * 1000  # Longer than 500

        await strategy.resolve("query", "ns1", context)

        generate_kwargs = sql_generator.generate.call_args[1]
        assert len(generate_kwargs["evidence"]) == 500
