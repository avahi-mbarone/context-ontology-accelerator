# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Validate Metric handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from coa_metrics.api.validate_metric import handler

pytestmark = pytest.mark.unit


# ── Test helpers ────────────────────────────────────────────────────────


def _make_event(body: dict | None = None, namespace: str = "test-ns") -> dict:
    """Build a minimal API Gateway proxy event for POST /namespaces/{ns}/metrics/validate."""
    path_params = {"namespaceId": namespace} if namespace else {}
    return {
        "httpMethod": "POST",
        "resource": "/namespaces/{namespaceId}/metrics/validate",
        "path": f"/namespaces/{namespace}/metrics/validate",
        "pathParameters": path_params,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": {"email": "test@example.com"}}},
    }


def _valid_body() -> dict:
    """Return a valid validate-metric request body (no SQL syntax errors)."""
    return {
        "name": "monthly_revenue",
        "description": "Total revenue from all orders in a calendar month",
        "expression": {"dialects": [{"dialect": "TRINO", "expression": "SELECT SUM(total_amount) FROM orders"}]},
        "dataSourceId": "ds-abc123",
        "sourceTable": "orders",
        "ontologyConcepts": ["ind:Order"],
    }


# Patch lookups to None so only Check 1 (SQL syntax) runs — keeps tests hermetic.
_no_lookups = patch.multiple(
    "coa_metrics.api.validate_metric",
    _get_data_source_lookup=MagicMock(return_value=None),
    _get_ontology_lookup=MagicMock(return_value=None),
)


# ── Request validation tests ────────────────────────────────────────────


class TestRequestValidation:
    def test_missing_namespace_returns_400(self) -> None:
        resp = handler(_make_event(body=_valid_body(), namespace=""), None)
        assert resp["statusCode"] == 400
        assert "namespace" in json.loads(resp["body"])["message"]

    def test_missing_body_returns_400(self) -> None:
        event = _make_event(body=None)
        resp = handler(event, None)
        assert resp["statusCode"] == 400
        assert "required" in json.loads(resp["body"])["message"]

    def test_invalid_json_returns_400(self) -> None:
        event = _make_event()
        event["body"] = "not json {"
        resp = handler(event, None)
        assert resp["statusCode"] == 400
        assert "Invalid JSON" in json.loads(resp["body"])["message"]

    def test_missing_required_field_returns_400(self) -> None:
        body = _valid_body()
        del body["name"]
        resp = handler(_make_event(body=body), None)
        assert resp["statusCode"] == 400


# ── Success tests ───────────────────────────────────────────────────────


class TestSuccess:
    def test_valid_metric_returns_200_no_warnings(self) -> None:
        with _no_lookups:
            resp = handler(_make_event(body=_valid_body()), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body == {"warnings": []}

    def test_bad_sql_returns_200_with_warning(self) -> None:
        body = _valid_body()
        body["expression"] = {"dialects": [{"dialect": "TRINO", "expression": "SELECT FROM WHERE )("}]}
        with _no_lookups:
            resp = handler(_make_event(body=body), None)
        assert resp["statusCode"] == 200
        warnings = json.loads(resp["body"])["warnings"]
        assert len(warnings) >= 1
        warning = warnings[0]
        assert warning["field"] == "sql_syntax"
        assert warning["severity"] == "WARNING"
        assert "message" in warning

    def test_response_shape_only_has_warnings(self) -> None:
        with _no_lookups:
            resp = handler(_make_event(body=_valid_body()), None)
        body = json.loads(resp["body"])
        assert list(body.keys()) == ["warnings"]


# ── Error handling tests ────────────────────────────────────────────────


class TestErrorHandling:
    @patch("coa_metrics.api.validate_metric.validate_metric")
    def test_validation_exception_returns_500(self, mock_validate: MagicMock) -> None:
        mock_validate.side_effect = RuntimeError("boom")
        with _no_lookups:
            resp = handler(_make_event(body=_valid_body()), None)
        assert resp["statusCode"] == 500
        assert "Internal error" in json.loads(resp["body"])["message"]

    @patch("coa_metrics.api.validate_metric.validate_metric")
    def test_soft_findings_map_to_info_severity(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = MagicMock(
            valid=False,
            errors=[{"check": "sql_syntax", "message": "bad sql"}],
            warnings=[{"check": "ontology_linkage", "message": "class not found"}],
        )
        with _no_lookups:
            resp = handler(_make_event(body=_valid_body()), None)
        warnings = json.loads(resp["body"])["warnings"]
        by_field = {w["field"]: w["severity"] for w in warnings}
        assert by_field["sql_syntax"] == "WARNING"
        assert by_field["ontology_linkage"] == "INFO"
