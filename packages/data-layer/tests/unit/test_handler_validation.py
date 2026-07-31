# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for data-layer handler input validation."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

# The handler module reads env vars at import time.
with patch.dict(
    "os.environ",
    {
        "AGENTCORE_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test",
        "AWS_REGION": "us-east-1",
        "ALLOWED_ORIGIN": "https://app.example.com",
    },
):
    from coa_data_layer import handler as handler_module
    from coa_data_layer.handler import handler


def _api_event(method: str, resource: str, body: dict | None = None, namespace: str = "demo") -> dict:
    """Build a minimal API Gateway proxy event."""
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": {"namespaceId": namespace},
        "body": json.dumps(body) if body else None,
        "headers": {"Authorization": "Bearer test-token"},
        "requestContext": {
            "authorizer": {
                "principalId": "user@example.com",
                "email": "user@example.com",
                "groups": "",
                "globalRoles": "",
            }
        },
    }


@pytest.mark.unit
class TestQueryValidation:
    """Validate that the /query endpoint rejects invalid inputs before invoking AgentCore."""

    def test_missing_body_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body=None)
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: query" in result["body"]

    def test_empty_query_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": ""})
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: query" in result["body"]

    def test_whitespace_only_query_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "   "})
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: query" in result["body"]

    def test_tabs_newlines_only_query_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "\t\n  "})
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: query" in result["body"]

    def test_missing_namespace_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hello"})
        event["pathParameters"] = {}
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "namespace" in result["body"].lower()


@pytest.mark.unit
class TestTranslateValidation:
    """Validate that the /translate endpoint rejects invalid inputs."""

    def test_whitespace_only_query_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/translate", body={"query": "   "})
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: query" in result["body"]


@pytest.mark.unit
class TestKbSearchValidation:
    """Validate that the /kb/search endpoint rejects invalid inputs."""

    def test_whitespace_only_query_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/kb/search", body={"query": "   "})
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: query" in result["body"]


@pytest.mark.unit
class TestCorsHeaders:
    """Test that CORS headers are set from ALLOWED_ORIGIN environment variable."""

    def test_cors_header_in_error_response(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body=None)
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert result["headers"]["Access-Control-Allow-Origin"] == "https://app.example.com"

    def test_cors_header_content_type(self):
        """Ensure CORS_HEADERS includes both CORS and Content-Type."""
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": ""})
        result = handler(event, None)
        assert result["headers"]["Access-Control-Allow-Origin"] == "https://app.example.com"
        assert result["headers"]["Content-Type"] == "application/json"

    def test_missing_allowed_origin_defaults_to_empty(self):
        """Missing ALLOWED_ORIGIN defaults to empty string (doesn't crash at import)."""
        with patch.dict("os.environ", {"AGENTCORE_RUNTIME_ARN": "arn:test", "AWS_REGION": "us-east-1"}, clear=True):
            import importlib

            from coa_data_layer import handler as h

            importlib.reload(h)
            assert h.CORS_HEADERS["Access-Control-Allow-Origin"] == ""


def _fake_urlopen(response_body: dict):
    """Build a urlopen replacement whose context-manager yields JSON bytes."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(response_body).encode("utf-8")
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm)


@pytest.mark.unit
class TestRouting:
    """Routing behavior: unknown routes and missing namespace."""

    def test_missing_namespace_path_param_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hi"})
        event["pathParameters"] = None
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing namespace path parameter" in result["body"]

    def test_unknown_route_returns_501(self):
        event = _api_event("DELETE", "/namespaces/{namespaceId}/query", body={"query": "hi"})
        result = handler(event, None)
        assert result["statusCode"] == 501
        assert "Not implemented" in result["body"]


@pytest.mark.unit
class TestQuerySuccess:
    """Query endpoint success path, option passthrough, and profile extraction."""

    def test_query_success_returns_200_with_result_shape(self):
        upstream = {
            "statusCode": 200,
            "result": {"answer": "42"},
            "requestId": "req-1",
            "sessionId": "sess-1",
        }
        with patch.object(handler_module, "urllib_request") as mock_req:
            mock_req.urlopen = _fake_urlopen(upstream)
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hello"})
            result = handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["result"] == {"answer": "42"}
        assert body["requestId"] == "req-1"
        assert body["sessionId"] == "sess-1"

    def test_query_forwards_all_options_and_caps_timeout(self):
        captured: dict = {}

        def _fake_invoke(payload: dict, token: str) -> dict:
            captured["payload"] = payload
            captured["token"] = token
            return {"statusCode": 200, "result": {}}

        body = {
            "query": "  spaced  ",
            "execute": False,
            "tierOverride": "premium",
            "mode": "standard",
            "dimensions": ["a", "b"],
            "timeoutMs": 999_999,
            "includeSupporting": True,
            "maxResults": 5,
        }
        with patch.object(handler_module, "_invoke_context_manager", side_effect=_fake_invoke):
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body=body, namespace="ns1")
            event["requestContext"]["authorizer"]["groups"] = "g1, g2"
            event["requestContext"]["authorizer"]["globalRoles"] = "admin"
            result = handler(event, None)

        assert result["statusCode"] == 200
        payload = captured["payload"]
        assert payload["query"] == "spaced"  # stripped
        assert payload["namespace"] == "ns1"
        assert payload["options"]["execute"] is False
        assert payload["options"]["tierOverride"] == "premium"
        assert payload["options"]["mode"] == "standard"
        assert payload["options"]["dimensions"] == ["a", "b"]
        assert payload["options"]["timeoutMs"] == handler_module.REST_TIMEOUT_MS  # capped
        assert payload["options"]["includeSupporting"] is True
        assert payload["options"]["maxResults"] == 5
        assert payload["profile"]["groups"] == ["g1", "g2"]
        assert payload["profile"]["globalRoles"] == ["admin"]
        assert captured["token"] == "test-token"

    def test_query_upstream_error_status_is_propagated(self):
        with patch.object(
            handler_module,
            "_invoke_context_manager",
            return_value={"statusCode": 503, "message": "downstream down"},
        ):
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hi"})
            result = handler(event, None)
        assert result["statusCode"] == 503
        assert "downstream down" in result["body"]


@pytest.mark.unit
class TestTranslateSuccess:
    """Translate endpoint success path shape."""

    def test_translate_success_returns_sparql_shape(self):
        upstream = {
            "statusCode": 200,
            "sparqlQuery": "SELECT ?s WHERE {}",
            "confidence": {"score": 0.9},
            "trace": ["step1"],
            "ontologyVersion": "v2",
        }
        with patch.object(handler_module, "_invoke_context_manager", return_value=upstream):
            event = _api_event("POST", "/namespaces/{namespaceId}/translate", body={"query": "hi"})
            result = handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["sparqlQuery"] == "SELECT ?s WHERE {}"
        assert body["confidence"] == {"score": 0.9}
        assert body["ontologyVersion"] == "v2"


@pytest.mark.unit
class TestKbSearchSuccess:
    """KB search endpoint success path and topK passthrough."""

    def test_kb_search_success_returns_chunks(self):
        captured: dict = {}

        def _fake_invoke(payload: dict, token: str) -> dict:
            captured["payload"] = payload
            return {"statusCode": 200, "chunks": [{"id": "c1"}], "trace": [], "queryEmbeddingModel": "m1"}

        with patch.object(handler_module, "_invoke_context_manager", side_effect=_fake_invoke):
            event = _api_event("POST", "/namespaces/{namespaceId}/kb/search", body={"query": "hi", "topK": 3})
            result = handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["chunks"] == [{"id": "c1"}]
        assert body["queryEmbeddingModel"] == "m1"
        assert captured["payload"]["options"]["topK"] == 3


@pytest.mark.unit
class TestGraphTraverse:
    """Graph traverse validation and success behavior."""

    def test_missing_start_uri_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/graph/traverse", body={"maxDepth": 3})
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: startUri" in result["body"]

    def test_graph_traverse_success_forwards_options(self):
        captured: dict = {}

        def _fake_invoke(payload: dict, token: str) -> dict:
            captured["payload"] = payload
            return {"statusCode": 200, "entities": [{"uri": "x"}], "relationships": [], "trace": []}

        body = {
            "startUri": "urn:node:1",
            "maxDepth": 4,
            "direction": "out",
            "maxResults": 50,
            "relationshipFilter": ["knows"],
        }
        with patch.object(handler_module, "_invoke_context_manager", side_effect=_fake_invoke):
            event = _api_event("POST", "/namespaces/{namespaceId}/graph/traverse", body=body)
            result = handler(event, None)
        assert result["statusCode"] == 200
        opts = captured["payload"]["options"]
        assert opts["startUri"] == "urn:node:1"
        assert opts["maxDepth"] == 4
        assert opts["direction"] == "out"
        assert opts["relationshipFilter"] == ["knows"]
        assert json.loads(result["body"])["entities"] == [{"uri": "x"}]


@pytest.mark.unit
class TestBodyParsing:
    """Malformed request bodies are treated as missing."""

    def test_invalid_json_body_returns_400(self):
        event = _api_event("POST", "/namespaces/{namespaceId}/query")
        event["body"] = "{not valid json"
        result = handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required field: query" in result["body"]


@pytest.mark.unit
class TestBearerToken:
    """Authorization header parsing forwards the correct raw token."""

    def test_non_bearer_authorization_forwarded_verbatim(self):
        captured: dict = {}

        def _fake_invoke(payload: dict, token: str) -> dict:
            captured["token"] = token
            return {"statusCode": 200, "result": {}}

        with patch.object(handler_module, "_invoke_context_manager", side_effect=_fake_invoke):
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hi"})
            event["headers"] = {"authorization": "raw-token-value"}
            handler(event, None)
        assert captured["token"] == "raw-token-value"


@pytest.mark.unit
class TestUpstreamErrorHandling:
    """Downstream transport errors map to appropriate HTTP responses."""

    def test_http_error_maps_code_and_error_field(self):
        detail = json.dumps({"message": "boom", "error": "ValidationError"}).encode("utf-8")
        err = HTTPError(
            url="http://x",
            code=422,
            msg="Unprocessable",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(detail),
        )
        with patch.object(handler_module, "_invoke_context_manager", side_effect=err):
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hi"})
            result = handler(event, None)
        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["message"] == "boom"
        assert body["error"] == "ValidationError"

    def test_http_error_non_json_body_truncated(self):
        err = HTTPError(
            url="http://x",
            code=500,
            msg="Server Error",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(b"plain text failure"),
        )
        with patch.object(handler_module, "_invoke_context_manager", side_effect=err):
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hi"})
            result = handler(event, None)
        assert result["statusCode"] == 500
        assert "plain text failure" in result["body"]

    def test_url_error_maps_to_502(self):
        with patch.object(handler_module, "_invoke_context_manager", side_effect=URLError("connection refused")):
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hi"})
            result = handler(event, None)
        assert result["statusCode"] == 502
        assert "Cannot reach Context Manager" in result["body"]

    def test_unexpected_exception_maps_to_502(self):
        with patch.object(handler_module, "_invoke_context_manager", side_effect=ValueError("oops")):
            event = _api_event("POST", "/namespaces/{namespaceId}/query", body={"query": "hi"})
            result = handler(event, None)
        assert result["statusCode"] == 502
        assert "ValueError" in result["body"]
