# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Query-time guardrail screening for retrieved document chunks.

Evaluates retrieved chunks against the retrieval guardrail (MEDIUM PROMPT_ATTACK
sensitivity) in parallel before they reach the synthesizer prompt. Chunks that
trigger intervention are excluded from context.

This is a thin async wrapper around the shared GuardrailScreener from libs/common.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from coa_common.guardrail_screener import GuardrailScreener, GuardrailScreenerError

from .vector_retriever import ChunkResult

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT_MS = 2000


@dataclass(frozen=True)
class ChunkScreeningOutcome:
    """Result of screening a single retrieved chunk."""

    chunk: ChunkResult
    allowed: bool
    reason: str  # "passed", "intervened", "timeout", "error"


async def screen_chunks(
    screener: GuardrailScreener,
    chunks: list[ChunkResult],
    *,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> list[ChunkScreeningOutcome]:
    """Evaluate all chunks in parallel with per-chunk timeout.

    Total latency is bounded by the single slowest chunk evaluation,
    not the sum of all evaluations.

    Graceful degradation: if the guardrail is entirely unreachable (all
    evaluations fail with connection errors), returns all chunks as allowed
    with a warning log. The other defense layers (spotlighting, primary
    guardrail) still protect against injection.

    Args:
        screener: Shared GuardrailScreener instance.
        chunks: Retrieved chunks from vector search.
        timeout_ms: Per-chunk evaluation timeout in milliseconds.

    Returns:
        ChunkScreeningOutcome per chunk in the same order as input.
    """
    if not chunks:
        return []

    async def _evaluate_one(chunk: ChunkResult, index: int) -> ChunkScreeningOutcome:
        try:
            results = await asyncio.wait_for(
                screener.ascreen_texts([chunk.text]),
                timeout=timeout_ms / 1000,
            )
            result = results[0]
            if result.passed:
                return ChunkScreeningOutcome(chunk=chunk, allowed=True, reason="passed")
            logger.info(
                "chunk_screener_intervened",
                chunk_id=chunk.chunk_id,
                source_doc=chunk.source_doc,
                intervention_reason=result.intervention_reason,
            )
            return ChunkScreeningOutcome(chunk=chunk, allowed=False, reason="intervened")
        except TimeoutError:
            logger.warning("chunk_screener_timeout", chunk_id=chunk.chunk_id, source_doc=chunk.source_doc)
            return ChunkScreeningOutcome(chunk=chunk, allowed=False, reason="timeout")
        except GuardrailScreenerError as e:
            logger.warning("chunk_screener_error", chunk_id=chunk.chunk_id, error=str(e))
            return ChunkScreeningOutcome(chunk=chunk, allowed=True, reason="error")
        except Exception as e:
            logger.warning("chunk_screener_unexpected", chunk_id=chunk.chunk_id, error=str(e))
            return ChunkScreeningOutcome(chunk=chunk, allowed=True, reason="error")

    outcomes = await asyncio.gather(*[_evaluate_one(chunk, i) for i, chunk in enumerate(chunks)])

    # If ALL outcomes are "error" (guardrail entirely unreachable), log warning
    # and allow all chunks through (graceful degradation).
    all_errors = all(o.reason == "error" for o in outcomes)
    if all_errors and len(outcomes) > 0:
        logger.warning("chunk_screener_all_unreachable", chunk_count=len(chunks))

    excluded_count = sum(1 for o in outcomes if not o.allowed)
    if excluded_count > 0:
        logger.info("chunk_screener_summary", total=len(chunks), excluded=excluded_count)

    return list(outcomes)
