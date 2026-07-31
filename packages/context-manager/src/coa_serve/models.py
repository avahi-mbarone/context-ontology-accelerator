# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Request/response models matching LLD QueryResult Smithy schema."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_serializer, field_validator

_MAX_DETAIL_LENGTH = 500  # Matches trace.py centralized truncation


class ConfidenceScore(BaseModel):
    """A resolution confidence score in [0, 1] with an optional rationale."""

    score: float = Field(..., ge=0.0, le=1.0)
    rationale: str = ""


class TraceStep(BaseModel):
    """One step in a query's processing trace, with timing and optional detail."""

    step: str
    status: str
    duration_ms: int = Field(0, alias="durationMs")
    detail: str | dict | None = None
    tool_used: str | None = Field(None, alias="toolUsed")
    parallel_group: str | None = Field(
        None, alias="parallelGroup", description="Groups concurrent children under a parent step"
    )
    wall_ms: int | None = Field(
        None, alias="wallMs", description="Wall-clock time for a parallel group (elapsed, not summed)"
    )
    graph_seed_mode: str | None = Field(
        None,
        alias="graphSeedMode",
        description="How the graph_traverse step got its seeds: 'uri_hop' (ontology URIs) or 'keyword' (ASCII labels)",
    )

    model_config = {"populate_by_name": True}

    @field_serializer("detail")
    def _truncate_detail(self, value: str | dict | None) -> str | dict | None:
        """Truncate detail values in client-facing serialization (CloudWatch gets full)."""
        if isinstance(value, str) and len(value) > _MAX_DETAIL_LENGTH:
            return value[:_MAX_DETAIL_LENGTH] + "..."
        if isinstance(value, dict):
            return {
                k: (v[:_MAX_DETAIL_LENGTH] + "..." if isinstance(v, str) and len(v) > _MAX_DETAIL_LENGTH else v)
                for k, v in value.items()
            }
        return value


class InvokeRequest(BaseModel):
    """Inbound query request: the question, namespace, auth profile, and options."""

    query: str = Field(..., min_length=1, max_length=4000)

    @field_validator("query", mode="before")
    @classmethod
    def _strip_query(cls, v: str) -> str:
        """Strip whitespace so whitespace-only queries are rejected by min_length."""
        return v.strip() if isinstance(v, str) else v

    namespace: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    profile: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)

    @field_validator("options", mode="after")
    @classmethod
    def _validate_retriever_strategy(cls, options: dict) -> dict:
        """Validate ``options.retrieverStrategy`` against :class:`RetrieverStrategy`.

        When the ``retrieverStrategy`` key is present, its value must be a valid
        ``RetrieverStrategy`` member; an invalid value raises ``ValidationError``
        (surfaced as the existing 400 path in ``main.py``).
        Absence of the key is valid, and the key stays inside ``options`` (no new
        top-level field). The import is local so this module does not eagerly pull
        in the strategy registry / graphrag import chain.
        """
        if "retrieverStrategy" in options:
            # Lazy import: validating against enum members does not import
            # graphrag_toolkit (the registry's build_engine imports are lazy).
            from .lexical.strategies import RetrieverStrategy

            value = options["retrieverStrategy"]
            try:
                RetrieverStrategy(value)
            except ValueError:
                valid = ", ".join(s.value for s in RetrieverStrategy)
                raise ValueError(f"Invalid retrieverStrategy {value!r}; must be one of: {valid}") from None
        return options

    @field_validator("options", mode="after")
    @classmethod
    def _validate_exclude_tools(cls, options: dict) -> dict:
        """Validate ``options.excludeTools`` — per-request agentic tool ablation.

        A list of agentic Tool names to WITHHOLD from the planner for this request,
        on top of the automatic composition gating. A tool the planner never sees
        cannot be selected, so this isolates one tool's contribution (e.g. run the
        loop without ``vector_search`` to measure whether it is redundant with the
        chunk-based strategies).

        Names are not validated against the live registry — the registry is built
        per deployment and an unknown name is a harmless no-op (``specs(exclude=)``
        simply matches nothing) — but the value must be a list of strings so a
        malformed request fails fast rather than silently ablating nothing.
        """
        if "excludeTools" in options:
            value = options["excludeTools"]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"Invalid excludeTools {value!r}; must be a list of tool-name strings")
        return options

    @field_validator("options", mode="after")
    @classmethod
    def _validate_mode(cls, options: dict) -> dict:
        """Validate ``options.mode`` — the per-request EXECUTION mode selector.

        Mode is orthogonal to the tier cascade (it selects HOW a request is
        executed, not which answer-shape wins), so the field is ``mode``, not
        ``tier3Mode``. Accepted values:

        * ``"agentic"``  — force the multi-step reasoning loop for this request.
        * ``"standard"`` — force the original single-shot path
          (``KnowledgeRetriever``: parallel retrieve + one synthesis).

        Absence follows the deployment default (``TIER3_STRATEGY``), which ships as
        ``lexical-baseline`` — so standard is the default and agentic is opt-in.
        ``"standard"`` stays an explicit opt-OUT for deployments that set
        ``TIER3_STRATEGY=agentic``.
        """
        if "mode" in options:
            value = options["mode"]
            if value not in ("agentic", "standard"):
                raise ValueError(f"Invalid mode {value!r}; must be 'agentic' or 'standard'")
        return options


class QueryResult(BaseModel):
    """Resolution result: answer tier, confidence, payloads, and processing trace."""

    tier: float
    confidence: ConfidenceScore
    result_rows: list[dict] | None = Field(None, alias="resultRows")
    synthesized_answer: str | None = Field(None, alias="synthesizedAnswer")
    query_used: str | None = Field(None, alias="queryUsed")
    sparql_generated: str | None = Field(None, alias="sparqlGenerated")
    supporting_content: list[dict] | None = Field(None, alias="supportingContent")
    graph_context: dict | None = Field(None, alias="graphContext")
    trace: list[TraceStep]
    ontology_version: str | None = Field(None, alias="ontologyVersion")
    data_sources: list[str] | None = Field(None, alias="dataSources")
    guardrail_blocked: bool = Field(False, alias="guardrailBlocked")
    # OUT OF SCOPE (flag, do not implement here): `partial` stays unpopulated.
    # The partial/504-timeout flag is owned by the Data Layer and is set
    # on the timeout path (see main.py); this model does not touch it.
    partial: bool = False
    metadata: dict | None = None
    # OUT OF SCOPE (flag, do not implement here): no `conformanceWarnings`
    # field. SHACL conformance warnings are P1 and are intentionally absent
    # from this model; do NOT add a conformanceWarnings field here.
    model_config = {"populate_by_name": True}


class InvokeResponse(BaseModel):
    """Outbound API envelope wrapping a QueryResult with request/session ids."""

    result: QueryResult
    requestId: str | None = None
    sessionId: str | None = None
