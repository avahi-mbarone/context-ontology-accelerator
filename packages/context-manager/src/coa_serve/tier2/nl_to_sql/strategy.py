# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""NL-to-SQL strategy — retrieval-grounded LLM SQL generation + firewall + execution.

Two-shot self-correction: the first shot generates SQL from retrieved schema and
executes it. If execution raises a database error (e.g. a type mismatch or an
unknown column), the strategy hands the verbatim engine error back to the LLM for
ONE corrective regeneration against the same retrieved schema, then re-executes.
The retry is capped (``SERVE_NL2SQL_MAX_SHOTS``, default 2) so worst-case latency
is bounded at two LLM calls + two executions — recovering the accuracy of an
agentic self-correction loop without its open-ended turn count. Retrieval and
embedding happen once (first shot only); the correction reuses that context.
"""

from __future__ import annotations

import os
import time

import structlog
from coa_common import ontology_vector_index_name

from ...clients.base import QueryExecutor
from ...exceptions import AccessDeniedError
from ...step_ids import StepId
from ..sql_firewall import FirewallResult, SQLFirewall, UnsafeSQLError
from ..strategy import StrategyContext, StrategyOption, StrategyResult, capped_max_rows
from .sql_generator import SQLGenerator

logger = structlog.get_logger(__name__)

# Total NL→SQL attempts per query, INCLUDING the first shot. 2 = one generate +
# one execution-error-driven correction. 1 disables self-correction (pure
# one-shot). Capped so latency stays bounded (see module docstring).
_DEFAULT_MAX_SHOTS = 2


def _resolve_max_shots() -> int:
    try:
        return max(1, int(os.environ.get("SERVE_NL2SQL_MAX_SHOTS", str(_DEFAULT_MAX_SHOTS))))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_SHOTS


class NLtoSQLStrategy:
    """StructuredQueryStrategy implementation for direct NL-to-SQL generation."""

    name: str = StrategyOption.NL_TO_SQL

    def __init__(
        self,
        sql_generator: SQLGenerator,
        firewall: SQLFirewall,
        query_executor: QueryExecutor | None,
        oss_ontology_index: str = "",
        max_shots: int | None = None,
    ):
        """Wire the SQL generator, firewall, executor, and ontology index.

        Args:
            sql_generator: Retrieval-grounded LLM SQL generator.
            firewall: SQLFirewall enforcing safety and authorization.
            query_executor: Executor that runs authorized SQL; None disables execution.
            oss_ontology_index: OpenSearch ontology index used for class retrieval.
            max_shots: Maximum generation+execution attempts (1 = no self-correction).
                Defaults to the NL_TO_SQL_MAX_SHOTS env var or 2.
        """
        self._sql_generator = sql_generator
        self._firewall = firewall
        self._query_executor = query_executor
        self._oss_ontology_index = oss_ontology_index
        self._max_shots = max_shots if max_shots is not None else _resolve_max_shots()

    async def resolve(self, query: str, namespace: str, context: StrategyContext) -> StrategyResult | None:
        """Generate SQL from the query, enforce the firewall, and execute it.

        Args:
            query: The natural-language query to answer.
            namespace: Namespace the query targets.
            context: Shared strategy context (embedding, profile, options, trace).

        Returns:
            A StrategyResult on success, or None when this strategy should be
            skipped so the next strategy can try.

        Raises:
            AccessDeniedError: If the firewall denies the generated SQL (terminal).
        """
        trace = context.trace
        profile = context.profile
        options = context.options
        embedding = context.embedding

        t_start = time.perf_counter()
        index_name = (
            ontology_vector_index_name(self._oss_ontology_index, namespace) if self._oss_ontology_index else None
        )

        # Resolve the target SQL dialect from the namespace's sources so the LLM
        # generates SQL in the correct dialect for the target engine. This avoids
        # generating Trino SQL for a PostgreSQL-only source, which would fail or
        # produce incorrect results after transpilation.
        dialect = "athena"
        data_source_id = options.get("dataSourceId", "")
        if self._query_executor and hasattr(self._query_executor, "resolve_target_dialect"):
            try:
                dialect = await self._query_executor.resolve_target_dialect(namespace, data_source_id)
            except Exception as e:
                logger.warning("dialect_resolution_failed", error=str(e), fallback="athena")

        evidence = options.get("evidence", "")[:500]
        nl_to_sql_result = await self._sql_generator.generate(
            query,
            namespace=namespace,
            index=index_name,
            evidence=evidence,
            embedding=embedding,
            model_id=context.model_id,
            dialect=dialect,
        )

        t_ms = int((time.perf_counter() - t_start) * 1000)

        if nl_to_sql_result.error or not nl_to_sql_result.sql:
            # Consolidate all sub-steps into a single t2.sql.generate step (E10).
            # A retrieval-backend failure (e.g. the vector proxy/index being
            # unavailable) means this strategy could not even start — that's a
            # graceful SKIP with fallthrough to the next strategy (VKG/Ontop),
            # not an error. Reserve "error" for a genuine generation failure so
            # the trace doesn't show a red step on every query when only the
            # optional NL→SQL retrieval path is degraded.
            err = nl_to_sql_result.error or "empty_sql"
            skipped = isinstance(err, str) and err.startswith("retrieve_failed")
            trace.record(
                StepId.T2_SQL_GENERATE,
                "skipped" if skipped else "error",
                t_ms,
                detail=err,
                tool_used="bedrock",
            )
            logger.warning("nl_to_sql_failed", error=nl_to_sql_result.error, duration_ms=t_ms)
            return None

        # Consolidate sub-steps into single t2.sql.generate/success step (E10)
        confidence = nl_to_sql_result.confidence
        tables = nl_to_sql_result.expanded_tables or nl_to_sql_result.retrieved_tables or []
        trace.record(
            StepId.T2_SQL_GENERATE,
            "success",
            t_ms,
            detail={"confidence": confidence, "tables": tables},
            tool_used="bedrock",
        )

        if not self._query_executor:
            # Firewall-check the SQL so an unsafe/denied first shot is still
            # surfaced, then skip (no executor configured — e.g. Tier-3 reuse).
            self._firewall_check(nl_to_sql_result.sql, profile, namespace, trace)
            trace.record(StepId.T2_SQL_EXECUTE, "skipped", 0, detail="no query_executor configured")
            return None

        # ── Two-shot loop: generate → firewall → execute; on execution error,
        # regenerate ONCE against the same schema with the error fed back. ──────
        sql = nl_to_sql_result.sql
        confidence = nl_to_sql_result.confidence
        data_source_id = nl_to_sql_result.data_source_id or options.get("dataSourceId", "")
        last_error: str | None = None

        # Best empty-but-valid result seen so far. A query that executes cleanly
        # but returns zero rows is a WEAK signal — it may be the true answer, or
        # (far more often in text-to-SQL) a subtly wrong query (bad JOIN, wrong
        # literal casing, over-restrictive filter). We spend the correction shot
        # trying to do better, but keep this as a fallback so we never downgrade a
        # clean empty result to a hard miss.
        empty_fallback: StrategyResult | None = None

        for shot in range(1, self._max_shots + 1):
            # Firewall (unsafe → skip strategy; denied → 403). Re-run per shot
            # because each shot produces distinct SQL that must be authorized.
            fw_result = self._firewall_check(sql, profile, namespace, trace)
            if fw_result is None:
                return empty_fallback  # unsafe SQL — keep any prior clean result

            exec_start = time.perf_counter()
            try:
                exec_result = await self._query_executor.execute(
                    fw_result.authorized_sql,
                    namespace=namespace,
                    data_source_id=data_source_id,
                    max_rows=capped_max_rows(options),
                    timeout_seconds=35,
                )
                exec_ms = int((time.perf_counter() - exec_start) * 1000)
                trace.record(
                    StepId.T2_SQL_EXECUTE,
                    "success",
                    exec_ms,
                    detail={
                        "rowCount": exec_result.row_count,
                        "tables": nl_to_sql_result.expanded_tables or nl_to_sql_result.retrieved_tables or [],
                        "truncated": getattr(exec_result, "truncated", False),
                        "shot": shot,
                        # Executing engine — athena | redshift | jdbc.
                        "engine": getattr(exec_result, "engine", "") or "unknown",
                    },
                )
                result = StrategyResult(
                    sql=fw_result.authorized_sql,
                    rows=exec_result.rows,
                    columns=exec_result.columns,
                    confidence=confidence,
                    strategy_name=StrategyOption.NL_TO_SQL,
                    trace_steps=nl_to_sql_result.trace_steps,
                    row_count=exec_result.row_count,
                    truncated=getattr(exec_result, "truncated", False),
                    retrieved_tables=nl_to_sql_result.retrieved_tables,
                    expanded_tables=nl_to_sql_result.expanded_tables,
                    data_source_id=nl_to_sql_result.data_source_id or "",
                )
                # Non-empty → done. Empty → stash as fallback and, if shots
                # remain, attempt one corrective regeneration (the empty result
                # is the "error signal" fed back to the model).
                if exec_result.row_count > 0 or shot >= self._max_shots:
                    return result if exec_result.row_count > 0 else (empty_fallback or result)
                empty_fallback = empty_fallback or result
                last_error = (
                    "The query executed successfully but returned ZERO rows. For this question a "
                    "non-empty answer is expected, so the query is likely wrong — e.g. an over-restrictive "
                    "WHERE filter, a string literal with the wrong case/spelling, or an incorrect JOIN. "
                    "Reconsider the filters and joins and produce a corrected query."
                )
            except Exception as e:
                exec_ms = int((time.perf_counter() - exec_start) * 1000)
                last_error = f"{type(e).__name__}: {e}"
                trace.record(
                    StepId.T2_SQL_EXECUTE,
                    "error",
                    exec_ms,
                    detail={"error": type(e).__name__, "message": str(e)[:120], "shot": shot},
                )
                logger.warning(
                    "nl_to_sql_execute_failed",
                    error=type(e).__name__,
                    duration_ms=exec_ms,
                    shot=shot,
                    max_shots=self._max_shots,
                )
                if shot >= self._max_shots:
                    break

            # A shot remains: ask the LLM to correct the SQL from the feedback
            # (verbatim engine error, or the empty-result signal) — model-driven,
            # no rule catalogue — reusing the already-retrieved schema context.
            correct_start = time.perf_counter()
            try:
                sql, confidence = await self._sql_generator.correct(
                    query,
                    nl_to_sql_result.ddl_context,
                    failed_sql=fw_result.authorized_sql,
                    execution_error=last_error,
                    evidence=evidence,
                    model_id=context.model_id,
                )
                correct_ms = int((time.perf_counter() - correct_start) * 1000)
                if not sql:
                    logger.warning("nl_to_sql_correction_empty", shot=shot)
                    break
                trace.record(
                    StepId.T2_SQL_GENERATE,
                    "success",
                    correct_ms,
                    detail={"confidence": confidence, "correction_shot": shot + 1},
                    tool_used="bedrock",
                )
            except Exception as e:
                logger.warning("nl_to_sql_correction_failed", error=type(e).__name__, shot=shot)
                break

        # Every shot failed to execute; return any clean empty result we saw.
        return empty_fallback

    def _firewall_check(self, sql: str, profile: dict, namespace: str, trace) -> FirewallResult | None:
        """Run the SQL firewall + Cedar gate for one candidate statement.

        Returns the FirewallResult on allow. Returns None (caller abandons the
        strategy) when the SQL is structurally unsafe. Raises AccessDeniedError
        on a policy denial (terminal 403) — matching the original behavior.
        """
        fw_start = time.perf_counter()
        try:
            fw_result = self._firewall.evaluate(sql, profile, namespace=namespace)
        except UnsafeSQLError as e:
            fw_ms = int((time.perf_counter() - fw_start) * 1000)
            trace.record(
                StepId.T2_SQL_FIREWALL,
                "error",
                fw_ms,
                detail={"error": "unsafe_sql", "message": str(e)[:200]},
                tool_used="sql-firewall",
            )
            logger.warning("nl_to_sql_unsafe_sql", message=str(e), security_event="unsafe_sql_attempt")
            return None
        fw_ms = int((time.perf_counter() - fw_start) * 1000)
        principal_id = profile.get("userId", "unknown")
        if fw_result.denied:
            trace.record(
                StepId.T2_SQL_AUTHORIZE,
                "denied",
                fw_ms,
                detail={"principal": principal_id, "decision": "deny"},
                tool_used="cedar",
            )
            trace.record(
                StepId.T2_SQL_FIREWALL,
                "denied",
                fw_ms,
                detail={"reason": fw_result.reason},
                tool_used="sql-firewall",
            )
            logger.warning("nl_to_sql_firewall_denied", namespace=namespace, reason=fw_result.reason)
            raise AccessDeniedError(fw_result.reason)
        trace.record(
            StepId.T2_SQL_AUTHORIZE,
            "allow",
            fw_ms,
            detail={"principal": principal_id, "decision": "allow"},
            tool_used="cedar",
        )
        trace.record(
            StepId.T2_SQL_FIREWALL,
            "success",
            fw_ms,
            detail={"decision": "authorized"},
            tool_used="sql-firewall",
        )
        return fw_result
