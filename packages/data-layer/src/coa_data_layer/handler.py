# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Data Layer API Lambda handler — thin adapter between API Gateway and Context Manager.

Validates requests, invokes the Context Manager via AgentCore Runtime (HTTP POST
to the VPC endpoint with JWT bearer auth), and maps responses to Smithy output shapes.

Environment:
    AGENTCORE_RUNTIME_ARN: AgentCore Runtime ARN for the Context Manager.
    AWS_REGION: AWS region (used to construct the VPC endpoint hostname).
"""

from __future__ import annotations

import json
import os
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import quote

RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

AGENTCORE_ENDPOINT = f"https://bedrock-agentcore.{REGION}.amazonaws.com"
ENCODED_ARN = quote(RUNTIME_ARN, safe="")
INVOKE_URL = f"{AGENTCORE_ENDPOINT}/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT"

_ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": _ALLOWED_ORIGIN,
}

REST_TIMEOUT_MS = 29_000


def _parse_first_sse_event(raw: str) -> dict:
    r"""Extract the first JSON payload from an SSE response.

    AgentCore's @app.entrypoint async generators produce text/event-stream
    responses where each yielded dict becomes: `data: <json>\\n\\n`
    Ref: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html

    Falls back to plain JSON parsing for local/test environments without SSE framing.
    """
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    # No SSE envelope (local testing or non-generator entrypoint)
    return json.loads(raw)


def _invoke_context_manager(payload: dict, token: str) -> dict:
    """Invoke the Context Manager via AgentCore Runtime HTTP endpoint."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        INVOKE_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=29) as resp:
        raw = resp.read().decode("utf-8")
    return _parse_first_sse_event(raw)


def _error_response(status_code: int, message: str, **extra) -> dict:
    body = {"message": message, **extra}
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def _success_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def _parse_body(event: dict) -> dict | None:
    raw = event.get("body")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _split_csv(value: str) -> list[str]:
    """Split a comma-separated string, stripping whitespace and filtering empty segments."""
    return [s.strip() for s in value.split(",") if s.strip()] if value else []


def _get_caller_profile(event: dict) -> dict:
    """Extract caller profile from authorizer context (set by JWT+Cedar authorizer).

    The authorizer writes groups/roles as comma-separated strings, not JSON.
    """
    context = event.get("requestContext", {}).get("authorizer", {})
    return {
        "userId": context.get("principalId", ""),
        "email": context.get("email", ""),
        "groups": _split_csv(context.get("groups", "")),
        "globalRoles": _split_csv(context.get("globalRoles", "")),
    }


def _get_bearer_token(event: dict) -> str:
    """Extract the raw Bearer token from the Authorization header."""
    headers = event.get("headers") or {}
    auth_header = headers.get("Authorization") or headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    return auth_header


# ── Route handlers ───────────────────────────────────────────────────────────


def _handle_query(namespace: str, event: dict) -> dict:
    body = _parse_body(event)
    if not body or not body.get("query"):
        return _error_response(400, "Missing required field: query")
    query = body["query"].strip()
    if not query:
        return _error_response(400, "Missing required field: query")

    payload = {
        "query": query,
        "namespace": namespace,
        "profile": _get_caller_profile(event),
        "options": {},
    }

    if body.get("execute") is False:
        payload["options"]["execute"] = False
    if body.get("tierOverride") is not None:
        payload["options"]["tierOverride"] = body["tierOverride"]
    if body.get("mode") is not None:
        payload["options"]["mode"] = body["mode"]
    if body.get("dimensions"):
        payload["options"]["dimensions"] = body["dimensions"]
    if body.get("timeoutMs") is not None:
        payload["options"]["timeoutMs"] = min(body["timeoutMs"], REST_TIMEOUT_MS)
    if body.get("includeSupporting") is not None:
        payload["options"]["includeSupporting"] = body["includeSupporting"]
    if body.get("maxResults") is not None:
        payload["options"]["maxResults"] = body["maxResults"]

    result = _invoke_context_manager(payload, _get_bearer_token(event))

    status_code = result.get("statusCode", 200)
    if status_code >= 400:
        return _error_response(status_code, result.get("message", "Internal error"))

    return _success_response(
        200,
        {
            "result": result.get("result", result),
            "requestId": result.get("requestId"),
            "sessionId": result.get("sessionId"),
        },
    )


def _handle_translate(namespace: str, event: dict) -> dict:
    body = _parse_body(event)
    if not body or not body.get("query"):
        return _error_response(400, "Missing required field: query")
    query = body["query"].strip()
    if not query:
        return _error_response(400, "Missing required field: query")

    payload = {
        "action": "translate",
        "query": query,
        "namespace": namespace,
        "profile": _get_caller_profile(event),
    }

    result = _invoke_context_manager(payload, _get_bearer_token(event))

    status_code = result.get("statusCode", 200)
    if status_code >= 400:
        return _error_response(status_code, result.get("message", "Internal error"))

    return _success_response(
        200,
        {
            "sparqlQuery": result.get("sparqlQuery", ""),
            "confidence": result.get("confidence", {"score": 0.0}),
            "trace": result.get("trace", []),
            "ontologyVersion": result.get("ontologyVersion"),
        },
    )


def _handle_kb_search(namespace: str, event: dict) -> dict:
    body = _parse_body(event)
    if not body or not body.get("query"):
        return _error_response(400, "Missing required field: query")
    query = body["query"].strip()
    if not query:
        return _error_response(400, "Missing required field: query")

    payload = {
        "action": "kbSearch",
        "query": query,
        "namespace": namespace,
        "profile": _get_caller_profile(event),
        "options": {
            "topK": body.get("topK", 10),
        },
    }

    result = _invoke_context_manager(payload, _get_bearer_token(event))

    status_code = result.get("statusCode", 200)
    if status_code >= 400:
        return _error_response(status_code, result.get("message", "Internal error"))

    return _success_response(
        200,
        {
            "chunks": result.get("chunks", []),
            "trace": result.get("trace", []),
            "queryEmbeddingModel": result.get("queryEmbeddingModel"),
        },
    )


def _handle_graph_traverse(namespace: str, event: dict) -> dict:
    body = _parse_body(event)
    if not body or not body.get("startUri"):
        return _error_response(400, "Missing required field: startUri")

    options: dict = {
        "startUri": body["startUri"],
        "maxDepth": body.get("maxDepth", 2),
        "direction": body.get("direction", "both"),
        "maxResults": body.get("maxResults", 100),
    }
    if body.get("relationshipFilter"):
        options["relationshipFilter"] = body["relationshipFilter"]

    payload = {
        "action": "graphTraverse",
        "namespace": namespace,
        "profile": _get_caller_profile(event),
        "options": options,
    }

    result = _invoke_context_manager(payload, _get_bearer_token(event))

    status_code = result.get("statusCode", 200)
    if status_code >= 400:
        return _error_response(status_code, result.get("message", "Internal error"))

    return _success_response(
        200,
        {
            "entities": result.get("entities", []),
            "relationships": result.get("relationships", []),
            "trace": result.get("trace", []),
        },
    )


# ── Main handler ─────────────────────────────────────────────────────────────

_ROUTE_MAP = {
    ("POST", "/namespaces/{namespaceId}/query"): _handle_query,
    ("POST", "/namespaces/{namespaceId}/translate"): _handle_translate,
    ("POST", "/namespaces/{namespaceId}/kb/search"): _handle_kb_search,
    ("POST", "/namespaces/{namespaceId}/graph/traverse"): _handle_graph_traverse,
}


def handler(event: dict, context) -> dict:
    """API Gateway Lambda proxy handler — routes to operation-specific handlers."""
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")
    path_params = event.get("pathParameters") or {}
    namespace = path_params.get("namespaceId", "")

    if not namespace:
        return _error_response(400, "Missing namespace path parameter")

    route_handler = _ROUTE_MAP.get((method, resource))
    if not route_handler:
        return _error_response(501, f"Not implemented: {method} {resource}")

    try:
        return route_handler(namespace, event)
    except HTTPError as e:
        resp_body = e.read().decode("utf-8") if e.fp else ""
        try:
            detail = json.loads(resp_body)
            msg = detail.get("message", resp_body[:200])
            error = detail.get("error")
        except (json.JSONDecodeError, TypeError):
            msg = resp_body[:200] or str(e)
            error = None
        return _error_response(e.code, msg, **({"error": error} if error else {}))
    except URLError as e:
        return _error_response(502, f"Cannot reach Context Manager: {e.reason}")
    except Exception as e:
        return _error_response(502, f"Context Manager invocation failed: {type(e).__name__}")
