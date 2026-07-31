# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tier 2 pluggable strategy architecture for structured query resolution.

Provides a Protocol-based extension point so the orchestrator can run
multiple structured-query strategies (Ontop VKG, direct NL-to-SQL, future
strategies) with configurable execution policies (sequential, parallel).

Usage::

    tier = StructuredQueryTier(strategies=[NLtoSQLStrategy(...), OntopStrategy(...)])
    result = await tier.resolve(query, namespace, context, option="best")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import structlog

from ..exceptions import AccessDeniedError
from ..step_ids import StepId
from ..trace import TraceCollector

logger = structlog.get_logger(__name__)


# ── Enums ────────────────────────────────────────────────────────────────


class StrategyOption(StrEnum):
    """Strategy selection values — used by client (options.strategy) and internally."""

    BEST = "best"  # Parallel: run both, return highest confidence
    ONTOP = "ontop"  # Only Ontop / identifies ontop strategy
    NL_TO_SQL = "nl_to_sql"  # Only NL→SQL / identifies nl_to_sql strategy
    ONTOP_FIRST = "ontop_first"  # Sequential: Ontop → NL→SQL fallback
    NL_TO_SQL_FIRST = "nl_to_sql_first"  # Sequential: NL→SQL → Ontop fallback


DEFAULT_STRATEGY = StrategyOption.NL_TO_SQL_FIRST


# ── Data classes ─────────────────────────────────────────────────────────


@dataclass
class StrategyResult:
    """Unified result from any Tier 2 strategy."""

    sql: str
    rows: list[dict]
    columns: list[str]
    confidence: float
    strategy_name: str  # StrategyOption value: "ontop" | "nl_to_sql"
    trace_steps: list[dict]
    ontop_assembly: bool = False  # True = use ontop assembler (includes sparql, ontology_version)
    data_source_id: str = ""
    row_count: int = 0
    truncated: bool = False
    sparql: str = ""  # SPARQL generated (ontop path); empty for NL→SQL
    retrieved_tables: list[str] = field(default_factory=list)
    expanded_tables: list[str] = field(default_factory=list)


@dataclass
class StrategyContext:
    """Shared context passed to all strategies during resolution."""

    embedding: list[float] | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    trace: TraceCollector = field(default_factory=TraceCollector)
    model_id: str | None = None


# ── Protocol ─────────────────────────────────────────────────────────────


@runtime_checkable
class StructuredQueryStrategy(Protocol):
    """Protocol for a pluggable Tier 2 strategy."""

    name: str

    async def resolve(self, query: str, namespace: str, context: StrategyContext) -> StrategyResult | None:
        """Resolve a query with this strategy, returning a result or None on miss."""
        ...


# ── Strategy runner ──────────────────────────────────────────────────────


_PARALLEL_STRATEGY_TIMEOUT_S = 90
MAX_RESULT_ROWS = 1000

# A strategy result with zero rows is accepted as a truthful "no data" answer
# ONLY when the strategy was confident in its query. Below this confidence, an
# empty result is more likely a bad query than a genuinely empty answer, so we
# fall through to the next strategy (and ultimately Tier 3) instead of stopping.
EMPTY_RESULT_CONFIDENCE_FLOOR = 0.3


def capped_max_rows(options: dict[str, Any]) -> int:
    """Cap maxResults to the system maximum."""
    return min(options.get("maxResults", MAX_RESULT_ROWS), MAX_RESULT_ROWS)


def is_low_confidence_empty(result: StrategyResult) -> bool:
    """True when a result returned no rows AND the strategy had low confidence.

    Such a result is treated as a miss (fall through to the next strategy /
    Tier 3) rather than a final answer, since a low-confidence query that
    returns nothing is more likely wrong than genuinely empty. A confident
    empty result (>= floor) is kept as a valid "no data found" answer.
    """
    return result.row_count == 0 and result.confidence < EMPTY_RESULT_CONFIDENCE_FLOOR


def _failed_step_id(strategy_name: str) -> str:
    """Trace step ID for an abandoned strategy, namespaced by its family."""
    family = "sql" if strategy_name == StrategyOption.NL_TO_SQL else "vkg"
    return f"t2.{family}.failed"


class StructuredQueryTier:
    """Runs registered strategies with sequential fallback or parallel execution.

    Constructed once with the full strategy list. Call ``resolve()`` with an
    option to control per-request behavior (which strategies, sequential vs parallel).
    """

    def __init__(self, strategies: list[StructuredQueryStrategy]):
        """Store the ordered strategy list used for fallback/parallel resolution.

        Args:
            strategies: Registered Tier-2 strategies, in fallback priority order.
        """
        self._strategies = list(strategies)

    async def resolve(
        self,
        query: str,
        namespace: str,
        context: StrategyContext,
        *,
        option: str | StrategyOption = DEFAULT_STRATEGY,
    ) -> StrategyResult | None:
        """Execute strategies for the given option. Returns first successful result, or None."""
        strategies = self._strategies_for(option)
        if option == StrategyOption.BEST:
            return await self._resolve_parallel(query, namespace, context, strategies)
        return await self._resolve_sequential(query, namespace, context, strategies)

    def _strategies_for(self, option: str) -> list[StructuredQueryStrategy]:
        """Select and order strategies based on the option."""
        if option == StrategyOption.ONTOP:
            return [s for s in self._strategies if s.name == StrategyOption.ONTOP]
        if option == StrategyOption.NL_TO_SQL:
            return [s for s in self._strategies if s.name == StrategyOption.NL_TO_SQL]
        if option == StrategyOption.ONTOP_FIRST:
            # Stable sort: matching strategy moves to front; others keep insertion order.
            return sorted(self._strategies, key=lambda s: s.name != StrategyOption.ONTOP)
        if option == StrategyOption.NL_TO_SQL_FIRST:
            return sorted(self._strategies, key=lambda s: s.name != StrategyOption.NL_TO_SQL)
        # "best" or unrecognized — use all in configured order
        if option != StrategyOption.BEST:
            logger.debug("strategy_option_passthrough", option=option)
        return list(self._strategies)

    async def _resolve_sequential(
        self, query: str, namespace: str, context: StrategyContext, strategies: list[StructuredQueryStrategy]
    ) -> StrategyResult | None:
        attempted: list[str] = []
        for strategy in strategies:
            attempted.append(strategy.name)
            try:
                result = await strategy.resolve(query, namespace, context)
                if result is not None:
                    # Confidence-gated empty result (option C): a zero-row result
                    # from a low-confidence query is more likely a bad query than
                    # a true empty answer — fall through to the next strategy /
                    # Tier 3 rather than returning it as the final answer.
                    if is_low_confidence_empty(result):
                        logger.info(
                            "strategy_low_confidence_empty",
                            strategy=strategy.name,
                            confidence=result.confidence,
                            attempted=attempted,
                        )
                        context.trace.record(
                            _failed_step_id(strategy.name),
                            "failed",
                            0,
                            detail={
                                "strategy": strategy.name,
                                "reason": "empty_low_confidence",
                                "confidence": result.confidence,
                            },
                        )
                        continue
                    logger.info(
                        "strategy_resolved",
                        strategy=strategy.name,
                        confidence=result.confidence,
                        row_count=result.row_count,
                        attempted=attempted,
                    )
                    return result
            except Exception as e:
                logger.warning(
                    "strategy_failed",
                    strategy=strategy.name,
                    error=type(e).__name__,
                    message=str(e)[:200],
                )
                if isinstance(e, AccessDeniedError):
                    raise
                # Record a visible step so the trace explains why this strategy
                # was abandoned and the next one tried (avoids silent transitions
                # when a strategy raises before recording its own failure step).
                context.trace.record(
                    _failed_step_id(strategy.name),
                    "failed",
                    0,
                    detail={"strategy": strategy.name, "error": type(e).__name__, "message": str(e)[:200]},
                )
                continue
        logger.info("strategy_all_failed", attempted=attempted)
        return None

    async def _resolve_parallel(
        self, query: str, namespace: str, context: StrategyContext, strategies: list[StructuredQueryStrategy]
    ) -> StrategyResult | None:
        # Each parallel strategy gets isolated context to avoid shared-state races.
        per_strategy_contexts = [
            StrategyContext(
                embedding=context.embedding,
                profile=dict(context.profile),
                options=dict(context.options),
                trace=TraceCollector(),
                model_id=context.model_id,
            )
            for _ in strategies
        ]

        async def _run_with_timeout(strategy: StructuredQueryStrategy, ctx: StrategyContext) -> StrategyResult | None:
            return await asyncio.wait_for(strategy.resolve(query, namespace, ctx), timeout=_PARALLEL_STRATEGY_TIMEOUT_S)

        results = await asyncio.gather(
            *[_run_with_timeout(s, ctx) for s, ctx in zip(strategies, per_strategy_contexts, strict=True)],
            return_exceptions=True,
        )

        # Re-raise terminal exceptions (AccessDenied, cancellation, system exit)
        for r in results:
            if isinstance(r, (AccessDeniedError, asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise r
            if isinstance(r, BaseException) and not isinstance(r, Exception):
                raise r

        # Log any strategy errors (timeouts, exceptions) for observability
        errors = [
            (s.name, type(r).__name__, str(r)[:100])
            for s, r in zip(strategies, results, strict=True)
            if isinstance(r, Exception)
        ]
        if errors:
            logger.warning(
                "tier2_parallel_errors",
                errors=[{"strategy": n, "error": t, "message": m} for n, t, m in errors],
            )

        valid_with_ctx = [
            (r, ctx) for r, ctx in zip(results, per_strategy_contexts, strict=True) if isinstance(r, StrategyResult)
        ]
        # Confidence-gated empty result (option C): prefer results that aren't a
        # low-confidence empty. If every candidate is one, fall through to Tier 3
        # rather than returning a likely-wrong empty answer.
        acceptable = [(r, ctx) for r, ctx in valid_with_ctx if not is_low_confidence_empty(r)]
        if not acceptable:
            if valid_with_ctx:
                logger.info(
                    "tier2_parallel_all_low_confidence_empty",
                    candidates=[r.strategy_name for r, _ in valid_with_ctx],
                )
                # Record a visible failure step per abandoned candidate so the
                # trace explains why Tier 2 fell through (mirrors the sequential
                # path); the per-strategy isolated traces are otherwise dropped.
                for r, _ in valid_with_ctx:
                    context.trace.record(
                        _failed_step_id(r.strategy_name),
                        "failed",
                        0,
                        detail={
                            "strategy": r.strategy_name,
                            "reason": "empty_low_confidence",
                            "confidence": r.confidence,
                        },
                    )
            return None
        # Pick highest confidence among acceptable results
        acceptable.sort(key=lambda pair: pair[0].confidence, reverse=True)
        winner, winner_ctx = acceptable[0]
        # Merge winner's trace steps into caller's trace (via record() so on_record callback fires for UI)
        for step in winner_ctx.trace.steps:
            context.trace.record(
                step.step,
                step.status,
                step.duration_ms,
                detail=step.detail,
                tool_used=step.tool_used,
                parallel_group=step.parallel_group,
                wall_ms=step.wall_ms,
            )
        # Emit a synthetic step so the UI knows which strategy was chosen (E9)
        context.trace.record(StepId.T2_STRATEGY_SELECTED, "success", 0, detail={"strategy": winner.strategy_name})
        # Log all candidates for observability (winner + losers)
        logger.info(
            "tier2_parallel_resolved",
            winner=winner.strategy_name,
            winner_confidence=winner.confidence,
            candidates=[
                {"strategy": r.strategy_name, "confidence": r.confidence, "row_count": r.row_count}
                for r, _ in valid_with_ctx
            ],
        )
        return winner
