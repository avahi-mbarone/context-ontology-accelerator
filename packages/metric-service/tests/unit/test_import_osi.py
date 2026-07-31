# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OSI import handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from coa_metrics.api.import_osi import _osi_metric_to_definition, handler
from coa_metrics.osi_parser import (
    OsiAiContext,
    OsiCustomExtension,
    OsiDialectExpression,
    OsiDocument,
    OsiMetric,
)

pytestmark = pytest.mark.unit


# ── Fixtures ────────────────────────────────────────────────────────────

VALID_OSI_CONTENT = """\
osi_spec_version: "1.0"
datasets:
  - name: orders_db
    data_source_id: ds-abc123
metrics:
  - name: monthly_revenue
    description: "Total revenue"
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: "SELECT SUM(total_amount) FROM orders"
    custom_extensions:
      - vendor_name: COA
        data:
          data_source_id: ds-abc123
          source_table: orders
          unit: currency
"""

MINIMAL_OSI_CONTENT = """\
osi_spec_version: "1.0"
metrics:
  - name: simple_count
    description: "Count of rows"
    expression:
      dialects:
        - dialect: ANSI_SQL
          expression: "SELECT COUNT(*) FROM orders"
    custom_extensions:
      - vendor_name: COA
        data:
          data_source_id: ds-abc123
          source_table: events
"""


def _make_event(content: str, namespace: str = "test-ns") -> dict:
    return {
        "httpMethod": "POST",
        "pathParameters": {"namespaceId": namespace},
        "body": json.dumps({"content": content}),
        "requestContext": {"authorizer": {"email": "test@example.com"}},
    }


# ── Handler Tests ───────────────────────────────────────────────────────


class TestImportOsiHandler:
    """Tests for the import_osi handler function."""

    @patch("coa_metrics.api.import_osi._get_opensearch")
    @patch("coa_metrics.api.import_osi._get_neptune")
    @patch("coa_metrics.api.import_osi._get_lookup")
    def test_successful_import_creates_metric(self, mock_lookup, mock_neptune, mock_opensearch) -> None:
        lookup = MagicMock()
        lookup.data_source_exists.return_value = True
        mock_lookup.return_value = lookup

        neptune = MagicMock()
        neptune.get_metric.return_value = None  # Metric doesn't exist yet
        mock_neptune.return_value = neptune

        opensearch = MagicMock()
        mock_opensearch.return_value = opensearch

        event = _make_event(VALID_OSI_CONTENT)
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["datasetsResolved"] == 1
        assert body["metricsCreated"] == 1
        assert body["metricsUpdated"] == 0

        neptune.create_metric.assert_called_once()

    @patch("coa_metrics.api.import_osi._get_opensearch")
    @patch("coa_metrics.api.import_osi._get_neptune")
    @patch("coa_metrics.api.import_osi._get_lookup")
    def test_import_updates_existing_metric(self, mock_lookup, mock_neptune, mock_opensearch) -> None:
        lookup = MagicMock()
        lookup.data_source_exists.return_value = True
        mock_lookup.return_value = lookup

        neptune = MagicMock()
        neptune.get_metric.return_value = MagicMock()  # Metric exists
        mock_neptune.return_value = neptune

        opensearch = MagicMock()
        mock_opensearch.return_value = opensearch

        event = _make_event(MINIMAL_OSI_CONTENT)
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["metricsCreated"] == 0
        assert body["metricsUpdated"] == 1

        neptune.update_metric.assert_called_once()

    def test_invalid_json_body(self) -> None:
        event = {
            "httpMethod": "POST",
            "pathParameters": {"namespaceId": "test"},
            "body": "not json",
            "requestContext": {"authorizer": {}},
        }
        response = handler(event, None)
        assert response["statusCode"] == 400

    def test_missing_content_field(self) -> None:
        event = {
            "httpMethod": "POST",
            "pathParameters": {"namespaceId": "test"},
            "body": json.dumps({"other": "field"}),
            "requestContext": {"authorizer": {}},
        }
        response = handler(event, None)
        assert response["statusCode"] == 400
        assert "content" in json.loads(response["body"])["message"]

    def test_invalid_osi_yaml(self) -> None:
        event = _make_event("{{invalid yaml")
        response = handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "parse errors" in body["message"]

    @patch("coa_metrics.api.import_osi._get_lookup")
    def test_unresolved_dataset_returns_400(self, mock_lookup) -> None:
        lookup = MagicMock()
        lookup.data_source_exists.return_value = False
        mock_lookup.return_value = lookup

        event = _make_event(VALID_OSI_CONTENT)
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "resolution failed" in body["message"]


# ── Conversion Tests ────────────────────────────────────────────────────


class TestOsiMetricToDefinition:
    """Tests for _osi_metric_to_definition helper."""

    def test_converts_ansi_sql_to_postgresql(self) -> None:
        osi_metric = OsiMetric(
            name="revenue",
            description="Total revenue",
            expression=[OsiDialectExpression(dialect="ANSI_SQL", expression="SELECT SUM(x) FROM t")],
            custom_extensions=OsiCustomExtension(data_source_id="ds-1", source_table="orders"),
        )
        doc = OsiDocument(metrics=[osi_metric])

        result = _osi_metric_to_definition(osi_metric, doc, "user@test.com")

        assert result.expression_dialects[0].dialect == "POSTGRESQL"
        assert result.data_source_id == "ds-1"
        assert result.source_table == "orders"
        assert result.defined_by == "user@test.com"

    def test_converts_snowflake_dialect(self) -> None:
        osi_metric = OsiMetric(
            name="count",
            description="Count",
            expression=[OsiDialectExpression(dialect="SNOWFLAKE", expression="SELECT COUNT(*) FROM t")],
            custom_extensions=OsiCustomExtension(data_source_id="ds-1", source_table="t"),
        )
        doc = OsiDocument(metrics=[osi_metric])

        result = _osi_metric_to_definition(osi_metric, doc, "user")

        assert result.expression_dialects[0].dialect == "SNOWFLAKE"

    def test_raises_without_data_source_id(self) -> None:
        osi_metric = OsiMetric(
            name="bad",
            description="No source",
            expression=[OsiDialectExpression(dialect="ANSI_SQL", expression="SELECT 1")],
        )
        doc = OsiDocument(metrics=[osi_metric])

        with pytest.raises(ValueError, match="No data_source_id"):
            _osi_metric_to_definition(osi_metric, doc, "user")

    def test_maps_time_dimension(self) -> None:
        osi_metric = OsiMetric(
            name="monthly",
            description="Monthly",
            expression=[OsiDialectExpression(dialect="ANSI_SQL", expression="SELECT SUM(x) FROM t")],
            custom_extensions=OsiCustomExtension(data_source_id="ds-1", source_table="t", time_dimension="month"),
        )
        doc = OsiDocument(metrics=[osi_metric])

        result = _osi_metric_to_definition(osi_metric, doc, "user")

        assert result.default_time_grain == "MONTH"


# ── AI Context Tests ─────────────────────────────────────────────────────


class TestAiContextMapping:
    """Tests for structured ai_context mapping from OsiAiContext to MetricAiContext."""

    def test_structured_ai_context_maps_directly(self) -> None:
        osi_metric = OsiMetric(
            name="test_metric",
            description="Test",
            expression=[OsiDialectExpression(dialect="ANSI_SQL", expression="SELECT COUNT(*) FROM t")],
            ai_context=OsiAiContext(
                synonyms=["total sales", "revenue"],
                instructions="Use with order_date. Do not use for forecasting.",
                examples=["Q1 revenue", "monthly totals"],
            ),
            custom_extensions=OsiCustomExtension(data_source_id="ds-123", source_table="orders"),
        )
        doc = OsiDocument(datasets=[], metrics=[osi_metric])
        result = _osi_metric_to_definition(osi_metric, doc, "test@example.com")

        assert result.ai_context is not None
        assert result.ai_context.synonyms == ["total sales", "revenue"]
        assert result.ai_context.instructions == "Use with order_date. Do not use for forecasting."
        assert result.ai_context.examples == ["Q1 revenue", "monthly totals"]

    def test_none_ai_context_maps_to_none(self) -> None:
        osi_metric = OsiMetric(
            name="test_metric",
            description="Test",
            expression=[OsiDialectExpression(dialect="ANSI_SQL", expression="SELECT COUNT(*) FROM t")],
            ai_context=None,
            custom_extensions=OsiCustomExtension(data_source_id="ds-123", source_table="orders"),
        )
        doc = OsiDocument(datasets=[], metrics=[osi_metric])
        result = _osi_metric_to_definition(osi_metric, doc, "test@example.com")

        assert result.ai_context is None

    def test_ai_context_preserves_periods_in_instructions(self) -> None:
        """Regression test: periods in instructions must not cause data loss."""
        instructions = (
            "Use this metric when the user asks about revenue. Do not use for forecasting. Always filter by status."
        )
        osi_metric = OsiMetric(
            name="test_metric",
            description="Test",
            expression=[OsiDialectExpression(dialect="ANSI_SQL", expression="SELECT COUNT(*) FROM t")],
            ai_context=OsiAiContext(instructions=instructions),
            custom_extensions=OsiCustomExtension(data_source_id="ds-123", source_table="orders"),
        )
        doc = OsiDocument(datasets=[], metrics=[osi_metric])
        result = _osi_metric_to_definition(osi_metric, doc, "test@example.com")

        assert result.ai_context is not None
        assert result.ai_context.instructions == instructions


# ── SQL shape enforcement on import ──────────────────────────────


class TestImportSqlShapeEnforcement:
    """Fragment expressions are rejected per-metric at import time."""

    def test_fragment_expression_raises(self) -> None:
        osi_metric = OsiMetric(
            name="frag",
            description="Fragment metric",
            expression=[OsiDialectExpression(dialect="ANSI_SQL", expression="COUNT(*)")],
            custom_extensions=OsiCustomExtension(data_source_id="ds-1", source_table="t"),
        )
        doc = OsiDocument(metrics=[osi_metric])
        with pytest.raises(ValueError, match="full SELECT statement"):
            _osi_metric_to_definition(osi_metric, doc, "user")


# ── Fail-closed data source lookup ───────────────────────────────


class TestGetLookupFailClosed:
    """_get_lookup must not silently degrade to the permissive fallback."""

    def _clear_cache(self) -> None:
        from coa_metrics.api import import_osi

        import_osi._lookups.clear()

    def test_lookup_unavailable_raises_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from coa_metrics.api.import_osi import _get_lookup
        from coa_metrics.source_status import (
            PERMISSIVE_ENV,
            SourceValidationUnavailableError,
        )

        self._clear_cache()
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with (
            patch("coa_metrics.api.import_osi.build_data_source_lookup", return_value=None),
            pytest.raises(SourceValidationUnavailableError),
        ):
            _get_lookup("ns-fail-closed")

    def test_lookup_init_error_raises_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from coa_metrics.api.import_osi import _get_lookup
        from coa_metrics.source_status import (
            PERMISSIVE_ENV,
            SourceValidationUnavailableError,
        )

        self._clear_cache()
        monkeypatch.delenv(PERMISSIVE_ENV, raising=False)
        with (
            patch(
                "coa_metrics.api.import_osi.build_data_source_lookup",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(SourceValidationUnavailableError),
        ):
            _get_lookup("ns-fail-closed-2")

    def test_permissive_env_enables_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from coa_metrics.api.import_osi import _get_lookup, _PermissiveLookup
        from coa_metrics.source_status import PERMISSIVE_ENV

        self._clear_cache()
        monkeypatch.setenv(PERMISSIVE_ENV, "true")
        with patch("coa_metrics.api.import_osi.build_data_source_lookup", return_value=None):
            lookup = _get_lookup("ns-permissive")
        assert isinstance(lookup, _PermissiveLookup)
        assert lookup.data_source_exists("anything") is True
