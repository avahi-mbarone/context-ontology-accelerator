# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Execution tools — query, translate_sparql, rag_retrieval, graph_traversal.

These tools delegate to the Context Manager via its AgentCore HTTP invocation
endpoint. The MCP server is a thin protocol adapter: it handles MCP framing,
auth extraction, and tool dispatch, but all orchestration (SQL generation,
Cedar authorization, DB access, LLM calls) happens in the Context Manager.

Identity propagation: the caller's JWT is forwarded to the CM, which validates
it independently and resolves roles from the same Cognito pool.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..clients.context_manager import ContextManagerClient

logger = structlog.get_logger(__name__)


def _build_cm_profile(profile: dict) -> dict:
    """Build the profile dict the CM entrypoint expects.

    The CM strips globalRoles/resourceRoles (security) but reads userId
    and groups to resolve roles authoritatively from its own RRM table.
    We pass the original IdP groups (not the already-resolved globalRoles)
    so the CM can query Group::<idp_group> in the RRM table.
    """
    return {
        "userId": profile.get("userId", ""),
        "groups": profile.get("idpGroups") or profile.get("globalRoles", []),
        "namespace": profile.get("namespace", ""),
    }


async def execute_query(
    cm_client: ContextManagerClient,
    query_text: str,
    namespace_id: str,
    profile: dict,
    bearer_token: str,
    *,
    tier_override: int | None = None,
    mode: str | None = None,
    max_results: int = 1000,
    include_supporting: bool = True,
) -> dict[str, Any]:
    """End-to-end NL query with tiered resolution.

    Forwards to Context Manager which runs the full pipeline:
    Tier 1 (metric) → Tier 2 (NL-to-SQL) → Tier 3 (agentic fallback).
    """
    payload: dict[str, Any] = {
        "query": query_text,
        "namespace": namespace_id,
        "profile": _build_cm_profile(profile),
        "options": {"maxResults": min(max_results, 10000)},
    }
    if tier_override is not None:
        payload["options"]["tierOverride"] = tier_override
    if mode is not None:
        payload["options"]["mode"] = mode
    if not include_supporting:
        payload["options"]["includeSupporting"] = False

    result = await cm_client.invoke(payload, bearer_token)
    return _unwrap_result(result)


async def execute_translate_sparql(
    cm_client: ContextManagerClient,
    query_text: str,
    namespace_id: str,
    profile: dict,
    bearer_token: str,
) -> dict[str, Any]:
    """Translate NL to SPARQL using the published ontology.

    Forwards to Context Manager with action=translate.
    """
    payload: dict[str, Any] = {
        "action": "translate",
        "query": query_text,
        "namespace": namespace_id,
        "profile": _build_cm_profile(profile),
    }

    result = await cm_client.invoke(payload, bearer_token)
    unwrapped = _unwrap_result(result)

    return {
        "sparqlQuery": unwrapped.get("sparql_generated") or unwrapped.get("queryUsed", ""),
        "confidence": unwrapped.get("confidence", {"score": 0.0, "rationale": ""}),
        "trace": unwrapped.get("trace", []),
        "namespace": namespace_id,
    }


async def execute_rag_retrieval(
    cm_client: ContextManagerClient,
    query_text: str,
    namespace_id: str,
    profile: dict,
    bearer_token: str,
    *,
    top_k: int = 10,
    min_score: float | None = None,
) -> dict[str, Any]:
    """Retrieve semantically similar document chunks from the knowledge base.

    Forwards to Context Manager with action=kbSearch.
    """
    payload: dict[str, Any] = {
        "action": "kbSearch",
        "query": query_text,
        "namespace": namespace_id,
        "profile": _build_cm_profile(profile),
        "options": {"topK": min(top_k, 100)},
    }
    if min_score is not None:
        payload["options"]["minScore"] = min_score

    result = await cm_client.invoke(payload, bearer_token)
    unwrapped = _unwrap_result(result)

    return {
        "chunks": unwrapped.get("supportingContent") or unwrapped.get("chunks", []),
        "trace": unwrapped.get("trace", []),
        "namespace": namespace_id,
    }


async def execute_graph_traversal(
    cm_client: ContextManagerClient,
    start_uri: str,
    namespace_id: str,
    profile: dict,
    bearer_token: str,
    *,
    max_depth: int = 2,
    direction: str = "both",
    max_results: int = 100,
) -> dict[str, Any]:
    """Traverse the semantic graph for entity relationships and context.

    Forwards to Context Manager with action=graphTraverse.
    """
    _VALID_DIRECTIONS = ("outgoing", "incoming", "both")
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(f"Invalid direction '{direction}': must be one of {_VALID_DIRECTIONS}")

    payload: dict[str, Any] = {
        "action": "graphTraverse",
        "startUri": start_uri,
        "namespace": namespace_id,
        "profile": _build_cm_profile(profile),
        "options": {
            "maxDepth": min(max_depth, 5),
            "direction": direction,
            "maxResults": min(max_results, 1000),
        },
    }

    result = await cm_client.invoke(payload, bearer_token)
    unwrapped = _unwrap_result(result)

    graph_context = unwrapped.get("graphContext") or unwrapped.get("graph_context") or {}
    return {
        "entities": graph_context.get("entities", []),
        "relationships": graph_context.get("relationships", []),
        "trace": unwrapped.get("trace", []),
        "namespace": namespace_id,
    }


def _unwrap_result(response: dict) -> dict[str, Any]:
    """Unwrap the CM response envelope.

    The CM @app.entrypoint may wrap the result in {"result": {...}} or
    return it flat depending on the invocation path.
    """
    if "result" in response and isinstance(response["result"], dict):
        return response["result"]
    return response
