# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for APPROVED-source enforcement."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from coa_metrics.source_status import (
    PERMISSIVE_ENV,
    SourceValidationUnavailableError,
    check_source_approved,
    permissive_lookup_enabled,
)

pytestmark = pytest.mark.unit


def _dao_returning(item: dict | None) -> MagicMock:
    dao = MagicMock()
    dao.get.return_value = item
    return dao


class TestCheckSourceApproved:
    def test_approved_source_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value = _dao_returning({"status": "APPROVED"})
            assert check_source_approved("ns-1", "ds-1") is None

    def test_completed_source_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value = _dao_returning({"status": "COMPLETED"})
            assert check_source_approved("ns-1", "ds-1") is None

    @pytest.mark.parametrize("status", ["PENDING_REVIEW", "SCAN_FAILED", "SCANNING", "REJECTED", ""])
    def test_non_approved_source_rejected(self, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value = _dao_returning({"status": status})
            error = check_source_approved("ns-1", "ds-1")
        assert error is not None
        assert "APPROVED" in error

    def test_missing_source_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value = _dao_returning(None)
            error = check_source_approved("ns-1", "ds-missing")
        assert error is not None
        assert "does not exist" in error

    def test_empty_data_source_id_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        assert check_source_approved("ns-1", "") == "dataSourceId is required"

    def test_missing_table_config_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATA_SOURCES_TABLE", raising=False)
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with pytest.raises(SourceValidationUnavailableError):
            check_source_approved("ns-1", "ds-1")

    def test_ddb_client_error_fails_closed_with_error_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """boto3 API errors surface the AWS error code in the 503 message."""
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value.get.side_effect = ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
                "GetItem",
            )
            with pytest.raises(SourceValidationUnavailableError, match="ProvisionedThroughputExceededException"):
                check_source_approved("ns-1", "ds-1")

    def test_ddb_access_denied_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value.get.side_effect = ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "no"}},
                "GetItem",
            )
            with pytest.raises(SourceValidationUnavailableError, match="AccessDeniedException"):
                check_source_approved("ns-1", "ds-1")

    def test_ddb_connection_error_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BotoCoreError (non-API failures, e.g. connection) also fails closed."""
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value.get.side_effect = EndpointConnectionError(endpoint_url="https://ddb.local")
            with pytest.raises(SourceValidationUnavailableError, match="EndpointConnectionError"):
                check_source_approved("ns-1", "ds-1")

    def test_ddb_unexpected_error_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-boto exceptions still fail closed (503) rather than raw 500."""
        monkeypatch.setenv("DATA_SOURCES_TABLE", "sources")
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with patch("coa_metrics.source_status.DynamoDBDAO") as dao_cls:
            dao_cls.return_value.get.side_effect = RuntimeError("throttled")
            with pytest.raises(SourceValidationUnavailableError):
                check_source_approved("ns-1", "ds-1")

    def test_permissive_mode_skips_enforcement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dev-only escape hatch: no table config needed, everything passes."""
        monkeypatch.delenv("DATA_SOURCES_TABLE", raising=False)
        monkeypatch.setenv(PERMISSIVE_ENV, "true")
        assert check_source_approved("ns-1", "ds-anything") is None


class TestPermissiveLookupEnabled:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        assert permissive_lookup_enabled() is False

    @pytest.mark.parametrize(("value", "expected"), [("true", True), ("TRUE", True), ("false", False), ("1", False)])
    def test_env_values(self, monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
        monkeypatch.setenv(PERMISSIVE_ENV, value)
        assert permissive_lookup_enabled() is expected
