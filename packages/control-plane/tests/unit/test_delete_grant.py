# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Delete Grant handler."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.update(
    {
        "RESOURCE_ROLE_MAPPINGS_TABLE": "test-mappings",
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
    }
)

from coa_control_plane.grants.delete_handler import handler  # noqa: E402
from coa_control_plane.grants.grant_id import encode_grant_id  # noqa: E402

pytestmark = pytest.mark.unit

VALID_NS_ID = "550e8400-e29b-41d4-a716-446655440000"
VALID_PK = f"Namespace::{VALID_NS_ID}#User::alice@company.com"
VALID_SK = "ROLE#analyst"
VALID_GRANT_ID = encode_grant_id(VALID_PK, VALID_SK)


def _event(namespace_id: str = VALID_NS_ID, grant_id: str = VALID_GRANT_ID) -> dict:
    return {
        "httpMethod": "DELETE",
        "resource": "/namespaces/{namespaceId}/grants/{grantId}",
        "pathParameters": {"namespaceId": namespace_id, "grantId": grant_id},
    }


class TestDeleteGrant:
    @patch("coa_control_plane.grants.delete_handler.DynamoDBDAO")
    def test_deletes_grant_successfully(self, mock_dao_cls):
        mock_dao = MagicMock()
        mock_dao_cls.return_value = mock_dao

        resp = handler(_event(), None)
        assert resp["statusCode"] == 200
        mock_dao.delete.assert_called_once_with({"PK": VALID_PK, "SK": VALID_SK})

    def test_invalid_namespace_id_returns_400(self):
        resp = handler(_event(namespace_id="bad!"), None)
        assert resp["statusCode"] == 400

    def test_missing_grant_id_returns_400(self):
        resp = handler(_event(grant_id=""), None)
        assert resp["statusCode"] == 400

    def test_invalid_grant_id_format_returns_400(self):
        resp = handler(_event(grant_id="not!valid!base64!!!"), None)
        assert resp["statusCode"] == 400

    def test_grant_id_for_wrong_namespace_returns_404(self):
        other_ns = "660e8400-e29b-41d4-a716-446655440000"
        other_pk = f"Namespace::{other_ns}#User::alice@company.com"
        other_grant_id = encode_grant_id(other_pk, VALID_SK)

        resp = handler(_event(grant_id=other_grant_id), None)
        assert resp["statusCode"] == 404

    @patch.dict(os.environ, {"ALLOWED_ORIGIN": "https://test.example.com"}, clear=True)
    def test_missing_env_vars_returns_500(self):
        resp = handler(_event(), None)
        assert resp["statusCode"] == 500
