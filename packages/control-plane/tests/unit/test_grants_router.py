# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Grants API router."""

from __future__ import annotations

import json
import os

import pytest

os.environ.update(
    {
        "ROLES_TABLE": "test-roles",
        "RESOURCE_ROLE_MAPPINGS_TABLE": "test-mappings",
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
    }
)

from coa_control_plane.grants.grants_handler import handler  # noqa: E402

pytestmark = pytest.mark.unit

VALID_NS_ID = "550e8400-e29b-41d4-a716-446655440000"


def _event(resource: str, method: str = "GET", path_params: dict | None = None) -> dict:
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params or {},
        "queryStringParameters": None,
        "requestContext": {"authorizer": {"claims": {"email": "admin@example.com"}}},
    }


class TestGrantsRouter:
    def test_unknown_route_returns_404(self):
        resp = handler(_event("/unknown", "GET"), None)
        assert resp["statusCode"] == 404

    def test_post_on_grants_collection_routes_to_create(self):
        event = _event("/namespaces/{namespaceId}/grants", "POST", {"namespaceId": "invalid!"})
        event["body"] = json.dumps({"principalType": "User", "principalId": "alice", "role": "analyst"})
        resp = handler(event, None)
        assert resp["statusCode"] == 400

    def test_delete_on_grants_item_routes_to_delete(self):
        event = _event(
            "/namespaces/{namespaceId}/grants/{grantId}", "DELETE", {"namespaceId": "invalid!", "grantId": "x"}
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 400

    def test_get_on_principals_routes_to_list_principal(self):
        event = _event("/principals/{principalId}/grants", "GET", {"principalId": ""})
        resp = handler(event, None)
        assert resp["statusCode"] == 400

    def test_method_not_allowed_on_grants_collection(self):
        event = _event("/namespaces/{namespaceId}/grants", "DELETE", {"namespaceId": VALID_NS_ID})
        resp = handler(event, None)
        assert resp["statusCode"] == 405

    def test_method_not_allowed_on_grants_item(self):
        event = _event(
            "/namespaces/{namespaceId}/grants/{grantId}", "POST", {"namespaceId": VALID_NS_ID, "grantId": "x"}
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 405

    def test_method_not_allowed_on_principals(self):
        event = _event("/principals/{principalId}/grants", "POST", {"principalId": "User::alice"})
        resp = handler(event, None)
        assert resp["statusCode"] == 405
