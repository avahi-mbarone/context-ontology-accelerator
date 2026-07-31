# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Uniform Tool contract and result for the Agentic Retriever (Req 2, Req 11).

Every retrieval capability the reasoning agent can invoke — Retrieval_Strategy
tools, the Graph_Traversal tool, the Vector_Search tool, the Ontology_Lookup
tool — implements the single :class:`Tool` Protocol defined here and returns a
:class:`ToolResult`. The uniform contract is what lets the registry enumerate
tools for the planner and the controller invoke any tool the same way
(Req 11.1).

Import discipline (Requirement 12.3): this module is dependency-free — it uses
only the standard library and ``typing`` and never imports ``graphrag_toolkit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolResult:
    """Uniform output of every Tool invocation (Req 11.1).

    A Tool never raises out of ``invoke`` for an expected retrieval failure
    (timeouts, backend errors); it returns a ``ToolResult`` whose ``detail``
    records the degradation so the controller can incorporate a degraded,
    non-fatal outcome and continue (Req 9.1-9.2). The passthrough ``chunks`` /
    ``entities`` carry the native retrieval objects forward for final synthesis,
    while ``items`` holds their normalized dict form for accumulation/dedupe.

    Attributes:
        items: Normalized retrieval items (chunks / entities / ontology facts)
            as plain dicts, used for accumulation and de-duplication.
        chunks: Native chunk objects (e.g. ``ChunkResult``) passed through
            untouched for the final Synthesizer.
        entities: Native entity objects (e.g. ``GraphEntity``) passed through
            untouched for the final Synthesizer.
        rows: Structured result rows (e.g. from NL→SQL / metric resolution) as
            plain dicts, passed through to the final Synthesizer. This is the
            channel structured tools produce on: chunks/entities are for
            document/graph retrieval, whereas a SQL or metric answer is tabular.
            ``AccumulatedContext.add`` counts new rows toward progress, so a
            successful structured tool is not mis-scored as no-progress.
        detail: Human-readable trace detail for this invocation, including any
            degradation reason.
        produced_directions: Candidate sub-question seeds this result surfaced
            (e.g. one per discovered competitor) that the controller may open as
            Exploration_Branches subject to the fan-out cap (Req 13.4).
    """

    items: tuple[dict, ...] = ()
    chunks: tuple[Any, ...] = ()
    entities: tuple[Any, ...] = ()
    rows: tuple[dict, ...] = ()
    detail: str = ""
    produced_directions: tuple[str, ...] = ()


@runtime_checkable
class Tool(Protocol):
    """Uniform tool contract (Req 2, Req 11).

    The four interface fields — ``name``, ``description``, ``input_schema``,
    ``output_schema`` — are all REQUIRED and must be present on every registered
    Tool (Req 11.1). ``input_schema`` declares the accepted input fields and
    their types; ``output_schema`` declares the produced output fields and their
    types. The async ``invoke`` performs the retrieval and returns a
    :class:`ToolResult`, always scoped to the request ``namespace``.

    ``@runtime_checkable`` lets the registry perform a structural presence check;
    the registry additionally validates the field values (non-empty name and
    description, dict schemas) because a Protocol ``isinstance`` check only
    confirms attribute presence, not that the values satisfy the contract.
    """

    name: str
    description: str
    input_schema: dict
    output_schema: dict

    async def invoke(self, *, namespace: str, **kwargs: Any) -> ToolResult:
        """Run the tool against ``namespace`` and return a :class:`ToolResult`."""
        ...
