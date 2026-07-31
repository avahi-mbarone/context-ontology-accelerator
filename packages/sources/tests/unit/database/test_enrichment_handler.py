# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the enrichment handler status lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from coa_control_plane_server.models.source_status import SourceStatus

ENRICHER_MODULE = "coa_sources.database.enrichment.table_enricher"


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("DATASOURCE_ID", "DS#ds-123")
    monkeypatch.setenv("SCAN_JOB_ID", "SCAN#scan-456")
    monkeypatch.setenv("NAMESPACE_ID", "ns-test")
    monkeypatch.setenv("SCAN_TYPE", "full")
    monkeypatch.setenv("SMUS_DOMAIN_ID", "dz-test-domain")
    monkeypatch.setenv("SOURCES_TABLE", "test-datasources")
    monkeypatch.setenv("SOURCE_SCAN_JOBS_TABLE", "test-scan-jobs")
    monkeypatch.setenv("NAMESPACES_TABLE", "test-namespaces")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


_UNSET = object()


def _build_dao(ns_item=_UNSET, source_item=None):
    """Build a DAO mock that returns different items by key.

    ``ns_dao.get`` is called on the namespace key first, and ``ds_dao.get``
    is called on the source key. The handler instantiates two separate DAO
    instances (one per table); we simulate that by routing ``get`` based on
    the SK value.

    ``ns_item=None`` simulates a missing namespace; pass ``_UNSET`` (the
    default) to use a working namespace stub.
    """
    dao = MagicMock()
    ns = {"dataZoneProjectId": "proj-123"} if ns_item is _UNSET else ns_item

    def _get(key):
        sk = key.get("SK", "")
        if sk == "METADATA":
            return ns
        if sk.startswith("SRC#"):
            return source_item
        return None

    dao.get.side_effect = _get
    return dao


class TestEnrichmentHandlerStatus:
    @patch(
        f"{ENRICHER_MODULE}.run", return_value={"tables_enriched": 5, "tables_failed": 0, "tables_skipped_unchanged": 0}
    )
    @patch("coa_common.dao.DynamoDBDAO")
    def test_sets_enriching_then_pending_review_on_success(self, mock_dao_cls, mock_run):
        # No metadataEnrichmentEnabled key on the source record → enrichment runs.
        mock_dao = _build_dao(source_item={"sourceId": "ds-123"})
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        update_calls = mock_dao.update.call_args_list
        assert len(update_calls) == 2

        # First call: ENRICHING
        assert update_calls[0][1]["update_fields"]["status"] == SourceStatus.ENRICHING
        assert update_calls[0][1]["key"] == {"PK": "NS#ns-test", "SK": "SRC#ds-123"}

        # Second call: PENDING_REVIEW
        assert update_calls[1][1]["update_fields"]["status"] == SourceStatus.PENDING_REVIEW

    @patch(f"{ENRICHER_MODULE}.run")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_skips_enrichment_when_disabled_and_sets_pending_review(self, mock_dao_cls, mock_run):
        mock_dao = _build_dao(source_item={"sourceId": "ds-123", "metadataEnrichmentEnabled": False})
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        # Enrichment runner must not be invoked.
        mock_run.assert_not_called()

        update_calls = mock_dao.update.call_args_list
        assert len(update_calls) == 1
        assert update_calls[0][1]["update_fields"]["status"] == SourceStatus.PENDING_REVIEW
        assert update_calls[0][1]["key"] == {"PK": "NS#ns-test", "SK": "SRC#ds-123"}

    @patch(
        f"{ENRICHER_MODULE}.run", return_value={"tables_enriched": 5, "tables_failed": 0, "tables_skipped_unchanged": 0}
    )
    @patch("coa_common.dao.DynamoDBDAO")
    def test_runs_enrichment_when_explicitly_enabled(self, mock_dao_cls, mock_run):
        mock_dao = _build_dao(source_item={"sourceId": "ds-123", "metadataEnrichmentEnabled": True})
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        mock_run.assert_called_once()
        update_calls = mock_dao.update.call_args_list
        statuses = [c[1]["update_fields"]["status"] for c in update_calls]
        assert SourceStatus.ENRICHING in statuses
        assert SourceStatus.PENDING_REVIEW in statuses

    @patch(f"{ENRICHER_MODULE}.run", side_effect=RuntimeError("Bedrock error"))
    @patch("coa_common.dao.DynamoDBDAO")
    def test_sets_scan_failed_on_error(self, mock_dao_cls, mock_run):
        mock_dao = _build_dao(source_item={"sourceId": "ds-123"})
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        with pytest.raises(RuntimeError, match="Bedrock error"):
            handler()

        update_calls = mock_dao.update.call_args_list
        assert len(update_calls) == 3

        # First call: ENRICHING on data source
        assert update_calls[0][1]["update_fields"]["status"] == SourceStatus.ENRICHING
        # Second call: SCAN_FAILED on data source
        assert update_calls[1][1]["update_fields"]["status"] == SourceStatus.SCAN_FAILED
        # Third call: errorMessage on scan job
        assert "errorMessage" in update_calls[2][1]["update_fields"]
        assert "Bedrock error" in update_calls[2][1]["update_fields"]["errorMessage"]

    @patch("coa_common.dao.DynamoDBDAO")
    def test_raises_if_namespace_not_found(self, mock_dao_cls):
        mock_dao = _build_dao(ns_item=None)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        with pytest.raises(ValueError, match="not found"):
            handler()

    @patch("coa_common.dao.DynamoDBDAO")
    def test_raises_if_source_record_missing(self, mock_dao_cls):
        # Source row missing — concurrent delete or never-created record.
        # The handler must fail loudly so the SFN error chain marks the scan FAILED
        # rather than continuing on a synthesised default and producing a partial write.
        mock_dao = _build_dao(source_item=None)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        with pytest.raises(ValueError, match="Source record not found"):
            handler()


class TestEnrichmentHandlerConditionalWrites:
    """All DDB updates must guard against a concurrently-deleted source row
    so the handler never re-creates a zombie record (matches discovery_handler).
    """

    @patch(
        f"{ENRICHER_MODULE}.run", return_value={"tables_enriched": 5, "tables_failed": 0, "tables_skipped_unchanged": 0}
    )
    @patch("coa_common.dao.DynamoDBDAO")
    def test_success_path_updates_are_conditional(self, mock_dao_cls, mock_run):
        mock_dao = _build_dao(source_item={"sourceId": "ds-123"})
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        # Every source-record update (ENRICHING + PENDING_REVIEW) must carry
        # the attribute_exists(PK) guard.
        for call in mock_dao.update.call_args_list:
            assert call[1].get("condition") == "attribute_exists(PK)"

    @patch(f"{ENRICHER_MODULE}.run")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_disabled_path_update_is_conditional(self, mock_dao_cls, mock_run):
        mock_dao = _build_dao(source_item={"sourceId": "ds-123", "metadataEnrichmentEnabled": False})
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        assert mock_dao.update.call_args_list[0][1].get("condition") == "attribute_exists(PK)"

    @patch(f"{ENRICHER_MODULE}.run", side_effect=RuntimeError("Bedrock error"))
    @patch("coa_common.dao.DynamoDBDAO")
    def test_failure_path_updates_are_conditional_and_non_raising(self, mock_dao_cls, mock_run):
        mock_dao = _build_dao(source_item={"sourceId": "ds-123"})
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        with pytest.raises(RuntimeError, match="Bedrock error"):
            handler()

        # Calls: [0]=ENRICHING (success-style), [1]=SCAN_FAILED, [2]=errorMessage.
        scan_failed_call = mock_dao.update.call_args_list[1]
        error_msg_call = mock_dao.update.call_args_list[2]

        for failure_call in (scan_failed_call, error_msg_call):
            assert failure_call[1].get("condition") == "attribute_exists(PK)"
            # Cleanup writes must not raise over a deleted row — that would mask
            # the original enrichment exception.
            assert failure_call[1].get("raise_on_error") is False


class TestEnrichmentMetricEmission:
    """Verify the handler emits the expected metrics during enrichment."""

    @patch(
        f"{ENRICHER_MODULE}.run",
        return_value={"tables_enriched": 3, "tables_failed": 1, "tables_skipped_unchanged": 2},
    )
    @patch("coa_sources.database.pipeline.enrichment_metrics.emit_metric")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_emits_job_level_metrics_on_success(self, mock_dao_cls, mock_emit, mock_run):
        source_item = {"sourceId": "ds-123", "configuration": '{"engine": "POSTGRESQL"}'}
        mock_dao = _build_dao(source_item=source_item)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        # Collect all emitted metric names
        emitted_names = [call[0][0] for call in mock_emit.call_args_list]

        assert "EnrichmentJobDurationMs" in emitted_names
        assert "TablesEnriched" in emitted_names
        assert "TablesFailed" in emitted_names
        assert "TablesSkippedUnchanged" in emitted_names
        assert "EnrichmentEstimatedCostUsd" in emitted_names

    @patch(
        f"{ENRICHER_MODULE}.run",
        return_value={"tables_enriched": 3, "tables_failed": 1, "tables_skipped_unchanged": 2},
    )
    @patch("coa_sources.database.pipeline.enrichment_metrics.emit_metric")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_metrics_include_engine_and_namespace_dimensions(self, mock_dao_cls, mock_emit, mock_run):
        source_item = {"sourceId": "ds-123", "configuration": '{"engine": "MYSQL"}'}
        mock_dao = _build_dao(source_item=source_item)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        # Every emitted metric should include Engine and NamespaceId
        for call in mock_emit.call_args_list:
            kwargs = call[1]
            assert kwargs.get("Engine") == "mysql", f"Missing Engine on {call[0][0]}"
            assert kwargs.get("NamespaceId") == "ns-test", f"Missing NamespaceId on {call[0][0]}"

    @patch(
        f"{ENRICHER_MODULE}.run",
        return_value={"tables_enriched": 5, "tables_failed": 0, "tables_skipped_unchanged": 0},
    )
    @patch("coa_sources.database.pipeline.enrichment_metrics.emit_metric")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_glue_source_emits_glue_engine_dimension(self, mock_dao_cls, mock_emit, mock_run):
        # Glue source: no "engine" in configuration
        source_item = {"sourceId": "ds-123", "configuration": '{"databaseName": "my_glue_db"}'}
        mock_dao = _build_dao(source_item=source_item)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        for call in mock_emit.call_args_list:
            assert call[1].get("Engine") == "glue"

    @patch(
        f"{ENRICHER_MODULE}.run",
        return_value={"tables_enriched": 2, "tables_failed": 0, "tables_skipped_unchanged": 0},
    )
    @patch("coa_sources.database.pipeline.enrichment_metrics.emit_metric")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_tables_enriched_value_matches_run_result(self, mock_dao_cls, mock_emit, mock_run):
        source_item = {"sourceId": "ds-123", "configuration": '{"engine": "POSTGRESQL"}'}
        mock_dao = _build_dao(source_item=source_item)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        tables_enriched_calls = [call for call in mock_emit.call_args_list if call[0][0] == "TablesEnriched"]
        assert len(tables_enriched_calls) == 1
        assert tables_enriched_calls[0][0][1] == 2  # value

    @patch(
        f"{ENRICHER_MODULE}.run",
        return_value={"tables_enriched": 0, "tables_failed": 3, "tables_skipped_unchanged": 0},
    )
    @patch("coa_sources.database.pipeline.enrichment_metrics.emit_metric")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_tables_failed_value_matches_run_result(self, mock_dao_cls, mock_emit, mock_run):
        source_item = {"sourceId": "ds-123", "configuration": '{"engine": "POSTGRESQL"}'}
        mock_dao = _build_dao(source_item=source_item)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        tables_failed_calls = [call for call in mock_emit.call_args_list if call[0][0] == "TablesFailed"]
        assert len(tables_failed_calls) == 1
        assert tables_failed_calls[0][0][1] == 3

    @patch(
        f"{ENRICHER_MODULE}.run",
        return_value={"tables_enriched": 1, "tables_failed": 0, "tables_skipped_unchanged": 4},
    )
    @patch("coa_sources.database.pipeline.enrichment_metrics.emit_metric")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_tables_skipped_unchanged_value_matches_run_result(self, mock_dao_cls, mock_emit, mock_run):
        source_item = {"sourceId": "ds-123", "configuration": '{"engine": "POSTGRESQL"}'}
        mock_dao = _build_dao(source_item=source_item)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        skipped_calls = [call for call in mock_emit.call_args_list if call[0][0] == "TablesSkippedUnchanged"]
        assert len(skipped_calls) == 1
        assert skipped_calls[0][0][1] == 4

    @patch(
        f"{ENRICHER_MODULE}.run",
        return_value={"tables_enriched": 1, "tables_failed": 0, "tables_skipped_unchanged": 0},
    )
    @patch("coa_sources.database.pipeline.enrichment_metrics.emit_metric")
    @patch("coa_common.dao.DynamoDBDAO")
    def test_enrichment_duration_is_positive_milliseconds(self, mock_dao_cls, mock_emit, mock_run):
        source_item = {"sourceId": "ds-123", "configuration": '{"engine": "POSTGRESQL"}'}
        mock_dao = _build_dao(source_item=source_item)
        mock_dao_cls.return_value = mock_dao

        from coa_sources.database.pipeline.enrichment_handler import handler

        handler()

        duration_calls = [call for call in mock_emit.call_args_list if call[0][0] == "EnrichmentJobDurationMs"]
        assert len(duration_calls) == 1
        assert duration_calls[0][0][1] > 0  # duration must be positive
        assert duration_calls[0][0][2] == "Milliseconds"
