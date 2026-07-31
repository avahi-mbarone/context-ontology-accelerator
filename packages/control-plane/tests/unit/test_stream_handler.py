# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the cache invalidation stream handler."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def env_vars(monkeypatch):
    monkeypatch.setenv("CACHE_INVALIDATION_TABLE_NAME", "coa-cache-invalidation")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.fixture()
def stream_event() -> dict[str, Any]:
    return {
        "Records": [
            {
                "eventID": "1",
                "eventName": "MODIFY",
                "dynamodb": {
                    "Keys": {"PK": {"S": "ROLE#admin"}, "SK": {"S": "POLICY#1"}},
                },
            }
        ]
    }


class TestStreamHandler:
    @patch("coa_control_plane.authorization.stream_handler.DynamoDBDAO")
    def test_bumps_version_atomically(self, mock_dao_cls, env_vars, stream_event):
        from coa_control_plane.authorization.stream_handler import handler

        mock_dao = MagicMock()
        mock_dao_cls.return_value = mock_dao

        handler(stream_event, None)

        mock_dao.atomic_increment.assert_called_once_with(
            key={"PK": "CACHE_VERSION", "SK": "CURRENT"},
            attribute="version",
        )

    def test_no_records_is_noop(self, env_vars):
        from coa_control_plane.authorization.stream_handler import handler

        with patch("coa_control_plane.authorization.stream_handler.DynamoDBDAO") as mock_dao_cls:
            handler({"Records": []}, None)
            mock_dao_cls.assert_not_called()

    def test_missing_table_name_logs_error(self, monkeypatch):
        monkeypatch.setenv("CACHE_INVALIDATION_TABLE_NAME", "")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        from coa_control_plane.authorization.stream_handler import handler

        handler({"Records": [{"eventName": "INSERT"}]}, None)

    @patch("coa_control_plane.authorization.stream_handler.DynamoDBDAO")
    def test_raises_on_dynamodb_error(self, mock_dao_cls, env_vars, stream_event):
        from coa_control_plane.authorization.stream_handler import handler

        mock_dao = MagicMock()
        mock_dao.atomic_increment.side_effect = Exception("DDB error")
        mock_dao_cls.return_value = mock_dao

        with pytest.raises(Exception, match="DDB error"):
            handler(stream_event, None)
