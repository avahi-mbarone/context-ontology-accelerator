# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Update and Delete Metric handlers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from coa_metrics.api.delete_metric import handler as delete_handler
from coa_metrics.api.update_metric import handler as update_handler
from coa_metrics.neptune_client import MetricDefinition, MetricDialect
from coa_metrics.source_status import PERMISSIVE_ENV, SourceValidationUnavailableError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _permissive_source_lookup(monkeypatch: pytest.MonkeyPatch):
    """Skip APPROVED-source enforcement in handler tests.

    Tests that exercise the enforcement itself opt out with
    ``monkeypatch.delenv(PERMISSIVE_ENV, raising=False)`` — see
    ``TestUpdateSourceApprovalEnforcement``.
    """
    monkeypatch.setenv(PERMISSIVE_ENV, "true")
    yield


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_update_event(body: dict | None = None, namespace: str = "test-ns", name: str = "revenue") -> dict:
    return {
        "httpMethod": "PUT",
        "pathParameters": {"namespaceId": namespace, "name": name},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": {"email": "updater@example.com"}}},
    }


def _make_delete_event(namespace: str = "test-ns", name: str = "revenue") -> dict:
    return {
        "httpMethod": "DELETE",
        "pathParameters": {"namespaceId": namespace, "name": name},
        "requestContext": {"authorizer": {"claims": {"email": "deleter@example.com"}}},
    }


def _valid_update_body() -> dict:
    return {
        "description": "Updated description",
        "expression": {"dialects": [{"dialect": "TRINO", "expression": "SELECT SUM(new_amount) FROM orders"}]},
        "dataSourceId": "ds-abc123",
        "sourceTable": "orders",
    }


def _existing_metric() -> MetricDefinition:
    return MetricDefinition(
        name="revenue",
        description="Old description",
        expression_dialects=[MetricDialect(dialect="TRINO", expression="SELECT SUM(x) FROM t")],
        data_source_id="ds-abc123",
        source_table="orders",
        defined_by="original@example.com",
        effective_from="2026-01-01",
    )


# ── Update tests ────────────────────────────────────────────────────────


class TestUpdateMetric:
    @patch("coa_metrics.api.update_metric._get_eventbridge")
    @patch("coa_metrics.api.update_metric._get_opensearch")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_update_success_returns_200(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_eventbridge.return_value.put_events.return_value = {}

        resp = update_handler(_make_update_event(body=_valid_update_body()), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["metric"]["description"] == "Updated description"
        assert body["metric"]["definedBy"] == "updater@example.com"
        # effectiveFrom preserved from existing
        assert body["metric"]["effectiveFrom"] == "2026-01-01"

    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_update_not_found_returns_404(self, mock_neptune: MagicMock) -> None:
        mock_neptune.return_value.get_metric.return_value = None

        resp = update_handler(_make_update_event(body=_valid_update_body()), None)

        assert resp["statusCode"] == 404

    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_update_missing_body_returns_400(self, mock_neptune: MagicMock) -> None:
        event = _make_update_event()
        event["body"] = None

        resp = update_handler(event, None)

        assert resp["statusCode"] == 400

    @patch("coa_metrics.api.update_metric._get_eventbridge")
    @patch("coa_metrics.api.update_metric._get_opensearch")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_update_calls_neptune_atomically(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_eventbridge.return_value.put_events.return_value = {}

        update_handler(_make_update_event(body=_valid_update_body()), None)

        mock_neptune.return_value.update_metric.assert_called_once()

    @patch("coa_metrics.api.update_metric._get_eventbridge")
    @patch("coa_metrics.api.update_metric._get_opensearch")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_update_neptune_failure_returns_500(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_neptune.return_value.update_metric.side_effect = RuntimeError("fail")

        resp = update_handler(_make_update_event(body=_valid_update_body()), None)

        assert resp["statusCode"] == 500

    @patch("coa_metrics.api.update_metric._get_eventbridge")
    @patch("coa_metrics.api.update_metric._get_opensearch")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_update_scopes_neptune_calls_to_path_namespace(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        """The namespace must come from the path, not a hardcoded or spoofable value."""
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_eventbridge.return_value.put_events.return_value = {}

        update_handler(_make_update_event(body=_valid_update_body(), namespace="ns-alpha"), None)

        assert mock_neptune.return_value.get_metric.call_args[0][0] == "ns-alpha"
        assert mock_neptune.return_value.update_metric.call_args[0][0] == "ns-alpha"

    @patch("coa_metrics.api.update_metric._get_eventbridge")
    @patch("coa_metrics.api.update_metric._get_opensearch")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_update_emits_update_action(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_eventbridge.return_value.put_events.return_value = {}

        update_handler(_make_update_event(body=_valid_update_body(), namespace="ns-alpha"), None)

        entry = mock_eventbridge.return_value.put_events.call_args[1]["Entries"][0]
        detail = json.loads(entry["Detail"])
        assert detail["action"] == "UPDATE"
        assert detail["namespace"] == "ns-alpha"
        assert detail["metricName"] == "revenue"


# ── APPROVED-source enforcement on update (#564) ────────────────────────


class TestUpdateSourceApprovalEnforcement:
    """Edit must enforce the same APPROVED/COMPLETED source gate as create."""

    @patch("coa_metrics.api.update_metric.check_source_approved")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_non_approved_source_returns_400(
        self, mock_neptune: MagicMock, mock_check: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_check.return_value = (
            "Data source 'ds-abc123' has status 'PENDING_REVIEW' — "
            "metrics can only reference APPROVED or COMPLETED sources"
        )

        resp = update_handler(_make_update_event(body=_valid_update_body()), None)

        assert resp["statusCode"] == 400
        assert "PENDING_REVIEW" in json.loads(resp["body"])["message"]
        mock_neptune.return_value.update_metric.assert_not_called()

    @patch("coa_metrics.api.update_metric.check_source_approved")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_validation_unavailable_returns_503(
        self, mock_neptune: MagicMock, mock_check: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail closed: an unverifiable source must not be silently accepted."""
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_check.side_effect = SourceValidationUnavailableError("table read failed")

        resp = update_handler(_make_update_event(body=_valid_update_body()), None)

        assert resp["statusCode"] == 503
        mock_neptune.return_value.update_metric.assert_not_called()

    @patch("coa_metrics.api.update_metric.check_source_approved")
    @patch("coa_metrics.api.update_metric._get_eventbridge")
    @patch("coa_metrics.api.update_metric._get_opensearch")
    @patch("coa_metrics.api.update_metric._get_neptune")
    def test_source_checked_against_path_namespace(
        self,
        mock_neptune: MagicMock,
        mock_opensearch: MagicMock,
        mock_eventbridge: MagicMock,
        mock_check: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The approval check must use the path namespace, not a default or spoofed one."""
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        mock_neptune.return_value.get_metric.return_value = _existing_metric()
        mock_eventbridge.return_value.put_events.return_value = {}
        mock_check.return_value = None

        update_handler(_make_update_event(body=_valid_update_body(), namespace="ns-alpha"), None)

        assert mock_check.call_args[0][0] == "ns-alpha"


# ── Delete tests ────────────────────────────────────────────────────────


class TestDeleteMetric:
    @patch("coa_metrics.api.delete_metric._get_eventbridge")
    @patch("coa_metrics.api.delete_metric._get_opensearch")
    @patch("coa_metrics.api.delete_metric._get_neptune")
    def test_delete_success_returns_204(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.delete_metric.return_value = True
        mock_eventbridge.return_value.put_events.return_value = {}

        resp = delete_handler(_make_delete_event(), None)

        assert resp["statusCode"] == 204

    @patch("coa_metrics.api.delete_metric._get_eventbridge")
    @patch("coa_metrics.api.delete_metric._get_opensearch")
    @patch("coa_metrics.api.delete_metric._get_neptune")
    def test_delete_scoped_to_path_namespace(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        """Neptune deletion must be confined to the namespace in the path.

        Deliberately asserts on the *Neptune* call, not OpenSearch: the graph
        write is the destructive one, so it needs its own guard rather than
        relying on the embedding-delete assertion elsewhere in this class.
        """
        mock_neptune.return_value.delete_metric.return_value = True
        mock_eventbridge.return_value.put_events.return_value = {}

        delete_handler(_make_delete_event(namespace="ns-alpha"), None)

        assert mock_neptune.return_value.delete_metric.call_args[0][0] == "ns-alpha"

    @patch("coa_metrics.api.delete_metric._get_neptune")
    def test_delete_not_found_returns_404(self, mock_neptune: MagicMock) -> None:
        mock_neptune.return_value.delete_metric.return_value = False

        resp = delete_handler(_make_delete_event(name="nonexistent"), None)

        assert resp["statusCode"] == 404

    @patch("coa_metrics.api.delete_metric._get_eventbridge")
    @patch("coa_metrics.api.delete_metric._get_opensearch")
    @patch("coa_metrics.api.delete_metric._get_neptune")
    def test_delete_removes_opensearch_embedding(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.delete_metric.return_value = True
        mock_eventbridge.return_value.put_events.return_value = {}

        delete_handler(_make_delete_event(), None)

        mock_opensearch.return_value.delete_metric_embedding.assert_called_once_with("test-ns", "revenue")

    @patch("coa_metrics.api.delete_metric._get_eventbridge")
    @patch("coa_metrics.api.delete_metric._get_opensearch")
    @patch("coa_metrics.api.delete_metric._get_neptune")
    def test_delete_emits_event(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.delete_metric.return_value = True
        mock_eventbridge.return_value.put_events.return_value = {}

        delete_handler(_make_delete_event(), None)

        entry = mock_eventbridge.return_value.put_events.call_args[1]["Entries"][0]
        detail = json.loads(entry["Detail"])
        assert detail["action"] == "DELETE"
        assert detail["metricName"] == "revenue"

    @patch("coa_metrics.api.delete_metric._get_eventbridge")
    @patch("coa_metrics.api.delete_metric._get_opensearch")
    @patch("coa_metrics.api.delete_metric._get_neptune")
    def test_delete_opensearch_failure_still_succeeds(
        self, mock_neptune: MagicMock, mock_opensearch: MagicMock, mock_eventbridge: MagicMock
    ) -> None:
        mock_neptune.return_value.delete_metric.return_value = True
        mock_opensearch.return_value.delete_metric_embedding.side_effect = RuntimeError("OSS down")
        mock_eventbridge.return_value.put_events.return_value = {}

        resp = delete_handler(_make_delete_event(), None)

        assert resp["statusCode"] == 204
