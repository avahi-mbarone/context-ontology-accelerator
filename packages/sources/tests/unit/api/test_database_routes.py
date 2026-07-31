# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for database_routes.py — DATABASE source route handlers.

Because database_routes.py has a circular import with sources_handler.py,
we import via sources_handler (the Lambda entry point) and patch using
full module path strings so the patches apply to the correct namespace.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError
from coa_control_plane_server.models.source_type import SourceType

# ---------------------------------------------------------------------------
# Environment setup — must happen before module import
# ---------------------------------------------------------------------------
os.environ.setdefault("SOURCES_TABLE", "test-sources")
os.environ.setdefault("SOURCE_SCAN_JOBS_TABLE", "test-scan-jobs")
os.environ.setdefault("NAMESPACES_TABLE", "test-namespaces")
os.environ.setdefault("SCAN_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/scan-queue")
os.environ.setdefault("SMUS_DOMAIN_ID", "test-domain-id")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

_NAMESPACE_ID = "550e8400-e29b-41d4-a716-446655440000"
_SOURCE_ID = "src-db-001"

# Import sources_handler FIRST to resolve circular import, then database_routes
import coa_sources.api.sources_handler  # noqa: F401, I001
import coa_sources.api.database_routes as _dr  # noqa: E402, I001

_DR = "coa_sources.api.database_routes"
_SH = "coa_sources.api.sources_handler"


@pytest.fixture(autouse=True)
def reset_lazy_clients():
    """Reset module-level lazy client globals between tests to prevent cross-test pollution."""
    import coa_sources.api.namespace_counters as nc
    import coa_sources.api.sources_handler as sh

    sh._dao = None
    sh._sqs = None
    sh._s3 = None
    sh._sfn = None
    sh._scan_dao = None
    sh._ns_dao = None
    nc._ns_dao = None
    with patch("coa_sources.api.database_routes.adjust_namespace_source_count"):
        yield
    sh._dao = None
    sh._sqs = None
    sh._s3 = None
    sh._sfn = None
    sh._scan_dao = None
    sh._ns_dao = None
    nc._ns_dao = None


def _parse(result):
    return result["statusCode"], json.loads(result["body"]) if result.get("body") else {}


def _make_glue_db_req(athena_data_catalog_name=None):
    req = MagicMock()
    req.name = "my-glue-db"
    req.glue_configuration = MagicMock()
    req.glue_configuration.to_dict.return_value = {"databaseName": "mydb", "region": "us-east-1"}
    req.glue_configuration.database_name = "mydb"
    req.glue_configuration.region = "us-east-1"
    req.glue_configuration.catalog_id = "123456789012"
    req.glue_configuration.athena_data_catalog_name = athena_data_catalog_name
    req.jdbc_configuration = None
    req.metadata_enrichment_enabled = None
    return req


def _make_jdbc_db_req(engine="POSTGRESQL"):
    req = MagicMock()
    req.name = "my-jdbc-db"
    req.jdbc_configuration = MagicMock()
    req.jdbc_configuration.engine = engine
    req.jdbc_configuration.to_dict.return_value = {"jdbcUrl": "jdbc:mysql://host/db"}
    req.glue_configuration = None
    req.metadata_enrichment_enabled = None
    return req


# ===================================================================
# _create_database_source
# ===================================================================


@pytest.mark.unit
class TestCreateDatabaseSource:
    def test_create_glue_source_happy_path(self):
        mock_dao = MagicMock()
        mock_scan_dao = MagicMock()
        mock_sqs = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
            patch(f"{_DR}._get_sqs", return_value=mock_sqs),
        ):
            status, body = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 202
        assert "sourceId" in body
        assert body["status"] == "REGISTERED"
        assert "scanJobId" in body
        mock_dao.put.assert_called_once()
        mock_sqs.send_message.assert_called_once()

    def test_create_glue_source_persists_athena_data_catalog_name(self):
        """Glue federated-backed sources record the user-supplied catalog name
        at the top level so the query layer can resolve it (record-only flow —
        no federation is provisioned for Glue sources)."""
        mock_dao = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_glue_db_req(athena_data_catalog_name="my_cat"), _NAMESPACE_ID)

        put_item = mock_dao.put.call_args[0][0]
        assert put_item["athenaDataCatalogName"] == "my_cat"

    def test_create_glue_source_persists_query_metadata(self):
        mock_dao = MagicMock()
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID)

        put_item = mock_dao.put.call_args[0][0]
        assert put_item["athenaCatalog"] == "AwsDataCatalog"
        assert put_item["athenaDatabase"] == "mydb"
        assert put_item["region"] == "us-east-1"
        assert put_item["queryable"] is False
        assert put_item["queryEngine"] == "ATHENA"

    def test_glue_nested_catalog_id_resolves_to_nested_catalog_name(self):
        mock_dao = MagicMock()
        req = _make_glue_db_req()
        req.glue_configuration.catalog_id = "999999999999:salescat"
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(req, _NAMESPACE_ID)
        assert mock_dao.put.call_args[0][0]["athenaCatalog"] == "salescat"

    def test_glue_explicit_athena_catalog_name_wins(self):
        mock_dao = MagicMock()
        req = _make_glue_db_req(athena_data_catalog_name="explicit_cat")
        req.glue_configuration.catalog_id = "999999999999:ignored"
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(req, _NAMESPACE_ID)
        assert mock_dao.put.call_args[0][0]["athenaCatalog"] == "explicit_cat"

    def test_create_jdbc_source_persists_query_metadata(self):
        mock_dao = MagicMock()
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_jdbc_db_req(), _NAMESPACE_ID)

        put_item = mock_dao.put.call_args[0][0]
        assert put_item["athenaCatalog"] == "AwsDataCatalog"
        assert put_item["queryable"] is False
        assert put_item["region"]  # deployment region
        assert put_item["queryEngine"] == "JDBC"  # direct single-source execution
        # JDBC schema is resolved per-table, so no single athenaDatabase.
        assert "athenaDatabase" not in put_item

    def test_create_jdbc_source_mysql_uses_direct_jdbc(self):
        # MySQL now has a direct-JDBC serve adapter (aiomysql), so it routes to
        # the direct path rather than Athena federation.
        mock_dao = MagicMock()
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_jdbc_db_req(engine="MYSQL"), _NAMESPACE_ID)

        assert mock_dao.put.call_args[0][0]["queryEngine"] == "JDBC"

    def test_create_jdbc_source_sqlserver_uses_direct_jdbc(self):
        # SQL Server now has a direct-JDBC serve adapter (python-tds).
        mock_dao = MagicMock()
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_jdbc_db_req(engine="SQLSERVER"), _NAMESPACE_ID)

        assert mock_dao.put.call_args[0][0]["queryEngine"] == "JDBC"

    def test_create_jdbc_source_without_direct_dialect_uses_athena(self):
        # An engine with no direct dialect yet (e.g. Snowflake) must fall back to
        # Athena, not claim a direct JDBC path that isn't implemented.
        mock_dao = MagicMock()
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_jdbc_db_req(engine="SNOWFLAKE"), _NAMESPACE_ID)

        assert mock_dao.put.call_args[0][0]["queryEngine"] == "ATHENA"

    def test_create_glue_source_omits_catalog_name_when_absent(self):
        mock_dao = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID)

        assert "athenaDataCatalogName" not in mock_dao.put.call_args[0][0]
        mock_dao = MagicMock()
        mock_scan_dao = MagicMock()
        mock_sqs = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
            patch(f"{_DR}._get_sqs", return_value=mock_sqs),
        ):
            status, body = _parse(_dr._create_database_source(_make_jdbc_db_req(), _NAMESPACE_ID))

        assert status == 202
        assert "sourceId" in body
        mock_dao.put.assert_called_once()
        put_item = mock_dao.put.call_args[0][0]
        assert put_item["sourceSubType"] == "JDBC_DATABASE"

    def test_create_omits_metadata_enrichment_when_unset(self):
        """When the caller does not specify the enrichment toggle, the field
        is absent from the persisted item — readers treat this as 'enabled'
        (the historical default). Round-trips never persist a synthetic value."""
        mock_dao = MagicMock()
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID)

        assert "metadataEnrichmentEnabled" not in mock_dao.put.call_args[0][0]

    def test_create_persists_metadata_enrichment_disabled(self):
        mock_dao = MagicMock()
        req = _make_glue_db_req()
        req.metadata_enrichment_enabled = False
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(req, _NAMESPACE_ID)

        assert mock_dao.put.call_args[0][0]["metadataEnrichmentEnabled"] is False

    def test_create_persists_metadata_enrichment_enabled_explicitly(self):
        mock_dao = MagicMock()
        req = _make_jdbc_db_req()
        req.metadata_enrichment_enabled = True
        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
        ):
            _dr._create_database_source(req, _NAMESPACE_ID)

        assert mock_dao.put.call_args[0][0]["metadataEnrichmentEnabled"] is True

    def test_create_blank_name_returns_400(self):
        req = _make_glue_db_req()
        req.name = "   "
        status, body = _parse(_dr._create_database_source(req, _NAMESPACE_ID))
        assert status == 400
        assert "name" in body["error"]

    def test_create_no_config_returns_400(self):
        req = _make_glue_db_req()
        req.glue_configuration = None
        req.jdbc_configuration = None
        status, body = _parse(_dr._create_database_source(req, _NAMESPACE_ID))
        assert status == 400

    def test_create_ddb_put_fails_returns_500(self):
        from botocore.exceptions import ClientError

        mock_dao = MagicMock()
        mock_dao.put.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "PutItem")
        mock_scan_dao = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, _ = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 500

    def test_create_sqs_fails_returns_500(self):
        from botocore.exceptions import ClientError

        mock_dao = MagicMock()
        mock_scan_dao = MagicMock()
        mock_sqs = MagicMock()
        mock_sqs.send_message.side_effect = ClientError({"Error": {"Code": "SQSError"}}, "SendMessage")

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
            patch(f"{_DR}._get_sqs", return_value=mock_sqs),
        ):
            status, _ = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 500
        # Atomic rollback: the partial source + scan-job records are removed,
        # and the source is NOT mislabeled SCAN_FAILED.
        mock_dao.delete.assert_called_once()
        mock_scan_dao.delete.assert_called_once()
        assert not any(c.args and c.args[1].get("status") == "SCAN_FAILED" for c in mock_dao.update.call_args_list)

    def test_create_no_scan_queue_url_skips_sqs(self):
        mock_dao = MagicMock()
        mock_scan_dao = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
            patch(f"{_DR}._SCAN_QUEUE_URL", ""),
        ):
            status, _ = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 202

    def test_create_stores_source_type_database(self):
        mock_dao = MagicMock()
        mock_scan_dao = MagicMock()
        mock_sqs = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
            patch(f"{_DR}._get_sqs", return_value=mock_sqs),
        ):
            status, body = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 202
        put_item = mock_dao.put.call_args[0][0]
        assert put_item["sourceType"] == "DATABASE"
        assert put_item["namespaceId"] == _NAMESPACE_ID


# ===================================================================
# _create_database_source — namespace sourceCount maintenance
# ===================================================================


@pytest.mark.unit
class TestCreateDatabaseSourceCounter:
    """The namespace ``sourceCount`` must be incremented when a DATABASE
    source is created, and rolled back (decremented) if the partial create
    is unwound because the scan could not be enqueued.

    The autouse ``reset_lazy_clients`` fixture patches
    ``adjust_namespace_source_count`` globally; each test re-patches it with a
    local handle so the call can be asserted.
    """

    def test_create_increments_namespace_source_count(self):
        mock_dao = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
            patch(f"{_DR}.adjust_namespace_source_count") as mock_counter,
        ):
            status, _ = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 202
        mock_counter.assert_called_once_with(_NAMESPACE_ID, SourceType.DATABASE, 1)

    def test_create_rolls_back_count_when_scan_enqueue_fails(self):
        """If the scan message cannot be enqueued the source row is deleted to
        avoid an orphaned record; the counter must be decremented to match so
        it does not drift above the true source total."""
        mock_dao = MagicMock()
        mock_sqs = MagicMock()
        mock_sqs.send_message.side_effect = ClientError({"Error": {"Code": "ServiceUnavailable"}}, "SendMessage")

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=mock_sqs),
            patch(f"{_DR}._SCAN_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/scan-queue"),
            patch(f"{_DR}.adjust_namespace_source_count") as mock_counter,
        ):
            status, _ = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 500
        # +1 on create, then -1 once the source row is rolled back.
        assert mock_counter.call_args_list == [
            call(_NAMESPACE_ID, SourceType.DATABASE, 1),
            call(_NAMESPACE_ID, SourceType.DATABASE, -1),
        ]
        mock_dao.delete.assert_called_once()

    def test_create_does_not_double_count_when_ddb_put_fails(self):
        """If the source row never persists (DDB put fails) the counter must
        not be touched at all — there is nothing to count."""
        mock_dao = MagicMock()
        mock_dao.put.side_effect = ClientError({"Error": {"Code": "ProvisionedThroughputExceeded"}}, "PutItem")

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=MagicMock()),
            patch(f"{_DR}._get_sqs", return_value=MagicMock()),
            patch(f"{_DR}.adjust_namespace_source_count") as mock_counter,
        ):
            status, _ = _parse(_dr._create_database_source(_make_glue_db_req(), _NAMESPACE_ID))

        assert status == 500
        mock_counter.assert_not_called()


# ===================================================================
# _handle_get_scan_job
# ===================================================================


@pytest.mark.unit
class TestHandleGetScanJob:
    def test_get_scan_job_happy_path(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"}
        mock_scan_dao = MagicMock()
        mock_scan_dao.get.return_value = {
            "PK": f"SRC#{_SOURCE_ID}",
            "SK": "2026-01-01T00:00:00Z",
            "status": "COMPLETED",
            "scanType": "full",
            "tablesDiscovered": 5,
            "startedAt": "2026-01-01T00:00:00Z",
            "completedAt": "2026-01-01T01:00:00Z",
        }

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, body = _parse(_dr._handle_get_scan_job(_NAMESPACE_ID, _SOURCE_ID, "2026-01-01T00:00:00Z"))

        assert status == 200
        assert body["status"] == "COMPLETED"
        assert body["tablesDiscovered"] == 5

    def test_get_scan_job_source_not_found(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = None
        mock_scan_dao = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, _ = _parse(_dr._handle_get_scan_job(_NAMESPACE_ID, _SOURCE_ID, "job-123"))

        assert status == 404

    def test_get_scan_job_job_not_found(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"}
        mock_scan_dao = MagicMock()
        mock_scan_dao.get.return_value = None

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, _ = _parse(_dr._handle_get_scan_job(_NAMESPACE_ID, _SOURCE_ID, "missing-job"))

        assert status == 404

    def test_get_scan_job_ddb_error_returns_500(self):
        from botocore.exceptions import ClientError

        mock_dao = MagicMock()
        mock_dao.get.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "GetItem")
        mock_scan_dao = MagicMock()

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, _ = _parse(_dr._handle_get_scan_job(_NAMESPACE_ID, _SOURCE_ID, "job-123"))

        assert status == 500

    def test_get_scan_job_scan_dao_error_returns_500(self):
        from botocore.exceptions import ClientError

        mock_dao = MagicMock()
        mock_dao.get.return_value = {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"}
        mock_scan_dao = MagicMock()
        mock_scan_dao.get.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "GetItem")

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, _ = _parse(_dr._handle_get_scan_job(_NAMESPACE_ID, _SOURCE_ID, "job-123"))

        assert status == 500

    def test_get_scan_job_decodes_url_encoded_timestamp(self):
        # ISO-8601 job IDs contain colons that arrive percent-encoded in the
        # path (e.g. "2026-01-01T00%3A00%3A00Z"). The handler must unquote()
        # before looking up the scan-jobs row by SK.
        mock_dao = MagicMock()
        mock_dao.get.return_value = {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"}
        mock_scan_dao = MagicMock()
        mock_scan_dao.get.return_value = {
            "PK": f"SRC#{_SOURCE_ID}",
            "SK": "2026-01-01T00:00:00Z",
            "status": "COMPLETED",
        }

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, body = _parse(_dr._handle_get_scan_job(_NAMESPACE_ID, _SOURCE_ID, "2026-01-01T00%3A00%3A00Z"))

        assert status == 200
        # The scan-jobs lookup must use the decoded SK, not the encoded one.
        scan_lookup_key = mock_scan_dao.get.call_args[0][0]
        assert scan_lookup_key["SK"] == "2026-01-01T00:00:00Z"
        # The decoded id is echoed back in the response.
        assert body["scanJobId"] == "2026-01-01T00:00:00Z"

    def test_get_scan_job_handles_already_decoded_timestamp(self):
        # unquote() on an already-decoded string is a no-op — a plain ISO
        # timestamp (no percent-encoding) must still resolve correctly.
        mock_dao = MagicMock()
        mock_dao.get.return_value = {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"}
        mock_scan_dao = MagicMock()
        mock_scan_dao.get.return_value = {
            "PK": f"SRC#{_SOURCE_ID}",
            "SK": "2026-01-01T00:00:00Z",
            "status": "COMPLETED",
        }

        with (
            patch(f"{_DR}._get_dao", return_value=mock_dao),
            patch(f"{_DR}._get_scan_dao", return_value=mock_scan_dao),
        ):
            status, body = _parse(_dr._handle_get_scan_job(_NAMESPACE_ID, _SOURCE_ID, "2026-01-01T00:00:00Z"))

        assert status == 200
        assert mock_scan_dao.get.call_args[0][0]["SK"] == "2026-01-01T00:00:00Z"
        assert body["scanJobId"] == "2026-01-01T00:00:00Z"


@pytest.mark.unit
class TestHandleUpdateMetadata:
    def _db_item(self):
        return {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceId": _SOURCE_ID,
            "sourceType": "DATABASE",
            "status": "APPROVED",
            "updatedAt": "2026-01-01T00:00:00Z",
        }

    def test_update_name_happy_path(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"name": "new-name"})}
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        mock_dao.update.assert_called_once()

    def test_update_metadata_enrichment_enabled(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"metadataEnrichmentEnabled": False})}
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        update_kwargs = mock_dao.update.call_args
        # update() may be called positionally or with kwargs — pull the
        # update_fields dict regardless of call style.
        args, kwargs = update_kwargs.args, update_kwargs.kwargs
        update_fields = args[1] if len(args) >= 2 else kwargs["update_fields"]
        assert update_fields["metadataEnrichmentEnabled"] is False

    def test_update_glue_config(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {
                "body": json.dumps(
                    {
                        "glueConfiguration": {
                            "catalogId": "123456789012",
                            "region": "us-east-1",
                            "databaseName": "newdb",
                        }
                    }
                )
            }
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200

    def test_update_jdbc_config(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {
                "body": json.dumps(
                    {
                        "jdbcConfiguration": {
                            "engine": "POSTGRESQL",
                            "host": "db.example.com",
                            "port": 5432,
                            "databaseName": "mydb",
                        }
                    }
                )
            }
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200

    def test_update_both_configs_returns_400(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"glueConfiguration": {}, "jdbcConfiguration": {}})}
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 400

    def test_update_empty_body_returns_400(self):
        status, _ = _parse(_dr._handle_update_metadata({"body": "{}"}, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 400

    def test_update_invalid_json_returns_400(self):
        status, _ = _parse(_dr._handle_update_metadata({"body": "not-json"}, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 400

    def test_update_source_not_found_returns_404(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = None

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"name": "new-name"})}
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 404

    def test_update_non_database_source_returns_400(self):
        mock_dao = MagicMock()
        item = self._db_item()
        item["sourceType"] = "DOCUMENTS"
        mock_dao.get.return_value = item

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"name": "new-name"})}
            status, body = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 400
        assert "DATABASE" in body["error"]

    def test_update_blank_name_returns_400(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"name": "   "})}
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 400

    def test_update_ddb_error_returns_500(self):
        from botocore.exceptions import ClientError

        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()
        mock_dao.update.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "UpdateItem")

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"name": "new-name"})}
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 500

    def test_update_no_updatable_fields_returns_400(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = self._db_item()

        with patch(f"{_DR}._get_dao", return_value=mock_dao):
            event = {"body": json.dumps({"name": None})}
            status, _ = _parse(_dr._handle_update_metadata(event, _NAMESPACE_ID, _SOURCE_ID))

        assert status == 400


# ===================================================================
# _handle_list_tables
# ===================================================================


@pytest.mark.unit
class TestHandleListTables:
    def _make_list_event(self, qs=None):
        return {"httpMethod": "GET", "queryStringParameters": qs or {}}

    def test_list_tables_no_smus_domain_returns_500(self):
        with patch(f"{_DR}._SMUS_DOMAIN_ID", ""):
            status, _ = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))
        assert status == 500

    def test_list_tables_namespace_not_found_returns_404(self):
        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = None

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
        ):
            status, _ = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 404

    def test_list_tables_invalid_max_results_returns_400(self):
        with patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"):
            status, _ = _parse(
                _dr._handle_list_tables(self._make_list_event({"maxResults": "abc"}), _NAMESPACE_ID, _SOURCE_ID)
            )
        assert status == 400

    def test_list_tables_invalid_review_status_returns_400(self):
        with patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"):
            status, _ = _parse(
                _dr._handle_list_tables(
                    self._make_list_event({"reviewStatus": "INVALID_STATUS"}), _NAMESPACE_ID, _SOURCE_ID
                )
            )
        assert status == 400

    def test_list_tables_happy_path(self):
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset = MagicMock()
        mock_asset.name = f"DS#{_SOURCE_ID}:mydb.mytable"
        mock_asset.asset_id = "asset-001"

        mock_result = MagicMock()
        mock_result.items = [mock_asset]
        mock_result.next_token = None

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result
        mock_smus.get_asset_forms.return_value = {
            "formsOutput": [
                {
                    "formName": FORM_TYPE_NAME,
                    "content": json.dumps(
                        {
                            "databaseName": "mydb",
                            "tableName": "mytable",
                            "columnCount": 3,
                            "reviewStatus": "PENDING_REVIEW",
                        }
                    ),
                }
            ]
        }

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, body = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "mytable"

    def test_list_tables_get_asset_forms_failure_logs_warning_and_marks_degraded(self):
        """When get_asset_forms raises, the asset is skipped with a warning log
        and the response includes a 'degraded' indicator."""
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset_ok = MagicMock()
        mock_asset_ok.name = f"DS#{_SOURCE_ID}:mydb.good_table"
        mock_asset_ok.asset_id = "asset-ok"

        mock_asset_bad = MagicMock()
        mock_asset_bad.name = f"DS#{_SOURCE_ID}:mydb.bad_table"
        mock_asset_bad.asset_id = "asset-bad"

        mock_result = MagicMock()
        mock_result.items = [mock_asset_bad, mock_asset_ok]
        mock_result.next_token = None

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result

        def _get_forms(asset_id):
            if asset_id == "asset-bad":
                raise RuntimeError("DataZone unavailable")
            return {
                "formsOutput": [
                    {
                        "formName": FORM_TYPE_NAME,
                        "content": json.dumps(
                            {
                                "databaseName": "mydb",
                                "tableName": "good_table",
                                "columnCount": 2,
                                "reviewStatus": "PENDING_REVIEW",
                            }
                        ),
                    }
                ]
            }

        mock_smus.get_asset_forms.side_effect = _get_forms

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
            patch(f"{_DR}.logger") as mock_logger,
        ):
            status, body = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        # Only the good table is returned
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "good_table"
        # Skipped assets indicator present
        assert body["skippedAssets"] == 1
        # Warning was logged with asset context
        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert call_kwargs[0][0] == "list_tables_asset_forms_failed"
        assert call_kwargs[1]["source_id"] == _SOURCE_ID
        assert call_kwargs[1]["asset_id"] == "asset-bad"
        assert call_kwargs[1]["asset_name"] == f"DS#{_SOURCE_ID}:mydb.bad_table"

    def test_list_tables_malformed_form_json_logs_warning_and_marks_degraded(self):
        """When form JSON is unparseable, the asset is skipped with a warning
        and the response includes a 'degraded' indicator."""
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset = MagicMock()
        mock_asset.name = f"DS#{_SOURCE_ID}:mydb.corrupt_table"
        mock_asset.asset_id = "asset-corrupt"

        mock_result = MagicMock()
        mock_result.items = [mock_asset]
        mock_result.next_token = None

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result
        mock_smus.get_asset_forms.return_value = {
            "formsOutput": [
                {
                    "formName": FORM_TYPE_NAME,
                    "content": "NOT VALID JSON {{{",
                }
            ]
        }

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
            patch(f"{_DR}.logger") as mock_logger,
        ):
            status, body = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        assert len(body["items"]) == 0
        assert body["skippedAssets"] == 1
        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert call_kwargs[0][0] == "list_tables_form_parse_failed"
        assert call_kwargs[1]["source_id"] == _SOURCE_ID
        assert call_kwargs[1]["asset_id"] == "asset-corrupt"
        assert call_kwargs[1]["asset_name"] == f"DS#{_SOURCE_ID}:mydb.corrupt_table"
        assert call_kwargs[1]["form_name"] == FORM_TYPE_NAME

    def test_list_tables_multiple_failures_accumulates_skipped_count(self):
        """When multiple assets fail (both API and parse errors),
        skippedAssets accurately reflects the total count."""
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        # Asset 1: get_asset_forms will raise
        mock_asset_api_fail = MagicMock()
        mock_asset_api_fail.name = f"DS#{_SOURCE_ID}:mydb.api_fail"
        mock_asset_api_fail.asset_id = "asset-api-fail"

        # Asset 2: form content will be malformed JSON
        mock_asset_parse_fail = MagicMock()
        mock_asset_parse_fail.name = f"DS#{_SOURCE_ID}:mydb.parse_fail"
        mock_asset_parse_fail.asset_id = "asset-parse-fail"

        # Asset 3: will succeed
        mock_asset_ok = MagicMock()
        mock_asset_ok.name = f"DS#{_SOURCE_ID}:mydb.good_table"
        mock_asset_ok.asset_id = "asset-ok"

        mock_result = MagicMock()
        mock_result.items = [mock_asset_api_fail, mock_asset_parse_fail, mock_asset_ok]
        mock_result.next_token = None

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result

        def _get_forms(asset_id):
            if asset_id == "asset-api-fail":
                raise RuntimeError("DataZone unavailable")
            if asset_id == "asset-parse-fail":
                return {"formsOutput": [{"formName": FORM_TYPE_NAME, "content": "{{{INVALID"}]}
            return {
                "formsOutput": [
                    {
                        "formName": FORM_TYPE_NAME,
                        "content": json.dumps(
                            {
                                "databaseName": "mydb",
                                "tableName": "good_table",
                                "columnCount": 1,
                                "reviewStatus": "PENDING_REVIEW",
                            }
                        ),
                    }
                ]
            }

        mock_smus.get_asset_forms.side_effect = _get_forms

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, body = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "good_table"
        assert body["skippedAssets"] == 2

    def test_list_tables_malformed_columns_field_skips_gracefully(self):
        """When the columns field within a valid form payload contains malformed
        JSON, the asset is skipped and counted in skippedAssets."""
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset = MagicMock()
        mock_asset.name = f"DS#{_SOURCE_ID}:mydb.bad_cols"
        mock_asset.asset_id = "asset-bad-cols"

        mock_result = MagicMock()
        mock_result.items = [mock_asset]
        mock_result.next_token = None

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result
        mock_smus.get_asset_forms.return_value = {
            "formsOutput": [
                {
                    "formName": FORM_TYPE_NAME,
                    "content": json.dumps(
                        {
                            "databaseName": "mydb",
                            "tableName": "bad_cols",
                            "columnCount": 3,
                            "reviewStatus": "PENDING_REVIEW",
                            "columns": "NOT VALID JSON [[[",
                        }
                    ),
                }
            ]
        }

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
            patch(f"{_DR}.logger") as mock_logger,
        ):
            status, body = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        assert len(body["items"]) == 0
        assert body["skippedAssets"] == 1
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args[0][0] == "list_tables_columns_parse_failed"
        assert mock_logger.warning.call_args[1]["asset_id"] == "asset-bad-cols"
        assert mock_logger.warning.call_args[1]["table_id"] == "mydb.bad_cols"

    def test_list_tables_no_failures_omits_degraded_field(self):
        """When all assets parse successfully, the response does not include
        'degraded' or 'skippedAssets' fields."""
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset = MagicMock()
        mock_asset.name = f"DS#{_SOURCE_ID}:mydb.mytable"
        mock_asset.asset_id = "asset-001"

        mock_result = MagicMock()
        mock_result.items = [mock_asset]
        mock_result.next_token = None

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result
        mock_smus.get_asset_forms.return_value = {
            "formsOutput": [
                {
                    "formName": FORM_TYPE_NAME,
                    "content": json.dumps(
                        {
                            "databaseName": "mydb",
                            "tableName": "mytable",
                            "columnCount": 3,
                            "reviewStatus": "PENDING_REVIEW",
                        }
                    ),
                }
            ]
        }

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, body = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        assert "degraded" not in body
        assert "skippedAssets" not in body

    def test_list_tables_search_fails_returns_500(self):
        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_smus = MagicMock()
        mock_smus.search_assets.side_effect = Exception("search failed")

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, _ = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 500

    def test_list_tables_with_next_token(self):
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset = MagicMock()
        mock_asset.name = f"DS#{_SOURCE_ID}:mydb.mytable"
        mock_asset.asset_id = "asset-001"

        mock_result = MagicMock()
        mock_result.items = [mock_asset]
        mock_result.next_token = "next-page-token"

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result
        mock_smus.get_asset_forms.return_value = {
            "formsOutput": [
                {
                    "formName": FORM_TYPE_NAME,
                    "content": json.dumps(
                        {
                            "databaseName": "mydb",
                            "tableName": "mytable",
                            "columnCount": 1,
                            "reviewStatus": "PENDING_REVIEW",
                        }
                    ),
                }
            ]
        }

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, body = _parse(_dr._handle_list_tables(self._make_list_event(), _NAMESPACE_ID, _SOURCE_ID))

        assert status == 200
        assert body.get("nextToken") == "next-page-token"

    def test_list_tables_filters_by_review_status(self):
        from coa_common.datazone_forms import FORM_TYPE_NAME

        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset = MagicMock()
        mock_asset.name = f"DS#{_SOURCE_ID}:mydb.mytable"
        mock_asset.asset_id = "asset-001"

        mock_result = MagicMock()
        mock_result.items = [mock_asset]
        mock_result.next_token = None

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result
        mock_smus.get_asset_forms.return_value = {
            "formsOutput": [
                {
                    "formName": FORM_TYPE_NAME,
                    "content": json.dumps(
                        {"databaseName": "mydb", "tableName": "mytable", "columnCount": 1, "reviewStatus": "APPROVED"}
                    ),
                }
            ]
        }

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            # Filter for PENDING_REVIEW — the table is APPROVED, so it should be excluded
            status, body = _parse(
                _dr._handle_list_tables(
                    self._make_list_event({"reviewStatus": "PENDING_REVIEW"}), _NAMESPACE_ID, _SOURCE_ID
                )
            )

        assert status == 200
        assert len(body["items"]) == 0


# ===================================================================
# _handle_get_table
# ===================================================================


@pytest.mark.unit
class TestHandleGetTable:
    def test_get_table_no_smus_domain_returns_500(self):
        with patch(f"{_DR}._SMUS_DOMAIN_ID", ""):
            status, _ = _parse(_dr._handle_get_table(_NAMESPACE_ID, _SOURCE_ID, "mydb.mytable"))
        assert status == 500

    def test_get_table_returns_column_confidence(self):
        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}
        mock_smus = MagicMock()
        _mock_single_asset_load(
            mock_smus,
            table_id="sales.orders",
            form_content=_serialize_table(columns=[{"name": "col_a", "description": "An id", "confidence": 0.88}]),
        )
        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, body = _parse(_dr._handle_get_table(_NAMESPACE_ID, _SOURCE_ID, "sales.orders"))
        assert status == 200
        assert body["columns"][0]["businessMetadata"]["confidence"] == 0.88

    def test_get_table_namespace_not_found_returns_404(self):
        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = None

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
        ):
            status, _ = _parse(_dr._handle_get_table(_NAMESPACE_ID, _SOURCE_ID, "mydb.mytable"))

        assert status == 404

    def test_get_table_asset_not_found_returns_404(self):
        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_result = MagicMock()
        mock_result.items = []

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, _ = _parse(_dr._handle_get_table(_NAMESPACE_ID, _SOURCE_ID, "mydb.mytable"))

        assert status == 404

    def test_get_table_search_fails_returns_500(self):
        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_smus = MagicMock()
        mock_smus.search_assets.side_effect = Exception("search error")

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, _ = _parse(_dr._handle_get_table(_NAMESPACE_ID, _SOURCE_ID, "mydb.mytable"))

        assert status == 500

    def test_get_table_forms_fetch_fails_returns_500(self):
        mock_ns_dao = MagicMock()
        mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}

        mock_asset = MagicMock()
        mock_asset.name = f"DS#{_SOURCE_ID}:mydb.mytable"
        mock_asset.asset_id = "asset-001"

        mock_result = MagicMock()
        mock_result.items = [mock_asset]

        mock_smus = MagicMock()
        mock_smus.search_assets.return_value = mock_result
        mock_smus.get_asset_forms.side_effect = Exception("forms error")

        with (
            patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
            patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
            patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        ):
            status, _ = _parse(_dr._handle_get_table(_NAMESPACE_ID, _SOURCE_ID, "mydb.mytable"))

        assert status == 500


# ===================================================================
# Resource-oriented review/edit handlers
# ===================================================================


def _serialize_table(
    *,
    table_name: str = "orders",
    database: str = "sales",
    table_status: str = "PENDING_REVIEW",
    columns: list[dict] | None = None,
    description: str = "Existing description",
) -> str:
    """Build a serialized CoaTableMetadata form payload."""
    if columns is None:
        columns = [
            {"name": "col_a", "review_status": "PENDING_REVIEW"},
            {"name": "col_b", "review_status": "PENDING_REVIEW"},
        ]
    return json.dumps(
        {
            "tableName": table_name,
            "databaseName": database,
            "dataSourceId": _SOURCE_ID,
            "namespaceId": _NAMESPACE_ID,
            "databaseDescription": "",
            "description": description,
            "columnCount": len(columns),
            "partitionKeys": "[]",
            "format": "",
            "location": "",
            "synonyms": "[]",
            "glossaryTerms": "[]",
            "tags": "[]",
            "enrichmentSource": "AI_GENERATED",
            "reviewStatus": table_status,
            "primaryKeyColumns": "[]",
            "primaryKeySource": "",
            "primaryKeyConfidence": 0.0,
            "foreignKeys": "[]",
            "columns": json.dumps(
                [
                    {
                        "name": c["name"],
                        "data_type": c.get("data_type", "string"),
                        "nullable": True,
                        "is_partition_key": False,
                        "description": "",
                        "business_metadata": {
                            "description": c.get("description", ""),
                            "synonyms": c.get("synonyms", []),
                            "glossary_terms": c.get("glossary_terms", []),
                            "tags": c.get("tags", []),
                            "enrichment_source": c.get("enrichment_source", "AI_GENERATED"),
                            "review_status": c.get("review_status", "PENDING_REVIEW"),
                            "confidence": c.get("confidence", 0.0),
                        },
                    }
                    for c in columns
                ]
            ),
        }
    )


def _mock_single_asset_load(
    smus_mock: MagicMock,
    *,
    table_id: str,
    form_content: str,
) -> None:
    """Configure an SMUSClient mock to return one matching asset for table_id."""
    asset_name = f"DS#{_SOURCE_ID}:{table_id}"
    asset = MagicMock()
    asset.name = asset_name
    asset.asset_id = f"asset-{table_id}"
    smus_mock.search_assets.return_value = MagicMock(items=[asset], next_token=None)
    smus_mock.get_asset_forms.return_value = {
        "formsOutput": [{"formName": "CoaTableMetadata", "content": form_content}]
    }
    smus_mock.create_asset_revision.return_value = MagicMock(asset_id=asset.asset_id)


@pytest.fixture
def _review_env():
    """Patch shared dependencies (SMUS_DOMAIN_ID, ns_dao, smus client, sources dao).

    The sources DAO is configured to return a reviewable source record by
    default so the ``_assert_source_reviewable`` guard passes. Tests that want
    to exercise the guard (e.g. APPROVING source) should override
    ``_review_env["dao"].get.return_value`` themselves.
    """
    mock_ns_dao = MagicMock()
    mock_ns_dao.get.return_value = {"dataZoneProjectId": "proj-123"}
    mock_smus = MagicMock()
    mock_dao = MagicMock()
    mock_dao.get.return_value = {
        "PK": f"NS#{_NAMESPACE_ID}",
        "SK": f"SRC#{_SOURCE_ID}",
        "sourceType": "DATABASE",
        "status": "PENDING_REVIEW",
    }
    with (
        patch(f"{_DR}._SMUS_DOMAIN_ID", "domain-id"),
        patch(f"{_DR}._get_ns_dao", return_value=mock_ns_dao),
        patch(f"{_DR}._get_smus_client", return_value=mock_smus),
        patch(f"{_DR}._get_dao", return_value=mock_dao),
    ):
        yield {"ns_dao": mock_ns_dao, "smus": mock_smus, "dao": mock_dao}


# ===================================================================
# _handle_review_table
# ===================================================================


@pytest.mark.unit
class TestReviewTable:
    _TABLE_ID = "sales.orders"

    def _event(self, body):
        return {"body": json.dumps(body) if body is not None else "{}"}

    def test_invalid_json_returns_400(self, _review_env):
        status, _ = _parse(_dr._handle_review_table({"body": "not-json"}, _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 400

    def test_missing_decision_returns_400(self, _review_env):
        status, body = _parse(_dr._handle_review_table(self._event({}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 400
        assert "decision" in body["error"]

    def test_invalid_decision_returns_400(self, _review_env):
        status, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "MAYBE"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 400

    def test_no_smus_domain_returns_500(self, _review_env):
        with patch(f"{_DR}._SMUS_DOMAIN_ID", ""):
            status, _ = _parse(
                _dr._handle_review_table(
                    self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
                )
            )
        assert status == 500

    def test_namespace_not_found_returns_404(self, _review_env):
        _review_env["ns_dao"].get.return_value = None
        status, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 404

    def test_table_not_found_returns_404(self, _review_env):
        _review_env["smus"].search_assets.return_value = MagicMock(items=[], next_token=None)
        status, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 404

    def test_pending_to_approved_writes_revision_and_increments_counter(self, _review_env):
        # Per-asset APPROVE now requires all columns to be terminal first.
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="PENDING_REVIEW",
                columns=[
                    {"name": "col_a", "review_status": "APPROVED"},
                    {"name": "col_b", "review_status": "REJECTED"},
                ],
            ),
        )
        status, body = _parse(
            _dr._handle_review_table(self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 200
        assert body["reviewStatus"] == "APPROVED"
        _review_env["smus"].create_asset_revision.assert_called_once()
        _review_env["dao"].atomic_increment.assert_called_once_with(
            {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"},
            "tablesApproved",
            amount=1,
        )

    def test_approve_cascades_pending_columns_to_approved(self, _review_env):
        # Per-asset APPROVE cascades PENDING columns to APPROVED (children
        # first), then approves the table — no 409 precondition anymore.
        from coa_common.datazone_forms import deserialize_form

        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="PENDING_REVIEW",
                columns=[
                    {"name": "col_a", "review_status": "PENDING_REVIEW"},
                    {"name": "col_b", "review_status": "APPROVED"},
                ],
            ),
        )
        status, body = _parse(
            _dr._handle_review_table(self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 200
        assert body["reviewStatus"] == "APPROVED"
        forms_input = _review_env["smus"].create_asset_revision.call_args.kwargs["forms_input"]
        written = deserialize_form(json.loads(forms_input[0]["content"]), data_source_id=_SOURCE_ID)
        col_status = {c.name: c.business_metadata.review_status for c in written.columns}
        assert col_status == {"col_a": "APPROVED", "col_b": "APPROVED"}

    def test_reject_persists_column_change_when_table_already_rejected(self, _review_env):
        # Aggressive reject: the table is already REJECTED but a stray column is
        # still APPROVED. The handler must persist the column flip even though
        # the table status does not change (regression guard for the
        # write-on-any-change fix).
        from coa_common.datazone_forms import deserialize_form

        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="REJECTED",
                columns=[
                    {"name": "col_a", "review_status": "APPROVED"},
                    {"name": "col_b", "review_status": "REJECTED"},
                ],
            ),
        )
        status, body = _parse(
            _dr._handle_review_table(self._event({"decision": "REJECTED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 200
        assert body["reviewStatus"] == "REJECTED"
        _review_env["smus"].create_asset_revision.assert_called_once()
        forms_input = _review_env["smus"].create_asset_revision.call_args.kwargs["forms_input"]
        written = deserialize_form(json.loads(forms_input[0]["content"]), data_source_id=_SOURCE_ID)
        col_status = {c.name: c.business_metadata.review_status for c in written.columns}
        assert col_status == {"col_a": "REJECTED", "col_b": "REJECTED"}

    def test_already_approved_is_idempotent_no_write_no_counter(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="APPROVED",
                columns=[
                    {"name": "col_a", "review_status": "APPROVED"},
                    {"name": "col_b", "review_status": "APPROVED"},
                ],
            ),
        )
        status, body = _parse(
            _dr._handle_review_table(self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 200
        assert body["reviewStatus"] == "APPROVED"
        _review_env["smus"].create_asset_revision.assert_not_called()
        _review_env["dao"].atomic_increment.assert_not_called()

    def test_approved_to_rejected_decrements_counter(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(table_status="APPROVED"),
        )
        _, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "REJECTED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        _review_env["dao"].atomic_increment.assert_called_once_with(
            {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"},
            "tablesApproved",
            amount=-1,
        )

    def test_rejected_to_approved_increments_counter(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="REJECTED",
                columns=[
                    {"name": "col_a", "review_status": "APPROVED"},
                    {"name": "col_b", "review_status": "APPROVED"},
                ],
            ),
        )
        _, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        _review_env["dao"].atomic_increment.assert_called_once_with(
            {"PK": f"NS#{_NAMESPACE_ID}", "SK": f"SRC#{_SOURCE_ID}"},
            "tablesApproved",
            amount=1,
        )

    def test_pending_to_rejected_does_not_change_counter(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(table_status="PENDING_REVIEW"),
        )
        _, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "REJECTED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        _review_env["smus"].create_asset_revision.assert_called_once()
        _review_env["dao"].atomic_increment.assert_not_called()

    def test_counter_failure_is_swallowed_and_emits_metric(self, _review_env):
        # The DataZone revision is the source of truth; a failed counter
        # increment must NOT fail the request, but it MUST emit a metric so
        # ops can alarm on systematic drift.
        from botocore.exceptions import ClientError

        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="PENDING_REVIEW",
                columns=[{"name": "col_a", "review_status": "APPROVED"}],
            ),
        )
        _review_env["dao"].atomic_increment.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "UpdateItem"
        )
        with patch(f"{_DR}.emit_metric") as mock_emit:
            status, body = _parse(
                _dr._handle_review_table(
                    self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
                )
            )
        # Request still succeeds despite the counter failure.
        assert status == 200
        assert body["reviewStatus"] == "APPROVED"
        # Drift is made observable.
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "ApprovalCounterUpdateFailed"

    def test_approve_is_noop_on_columns_when_all_terminal(self, _review_env):
        # With the precondition that all columns must already be terminal,
        # approving the table preserves each column's prior decision and only
        # flips the table itself.
        from coa_common.datazone_forms import deserialize_form

        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="PENDING_REVIEW",
                columns=[
                    {"name": "col_a", "review_status": "REJECTED"},
                    {"name": "col_b", "review_status": "APPROVED"},
                    {"name": "col_c", "review_status": "APPROVED"},
                ],
            ),
        )
        status, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "APPROVED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 200
        # Inspect the form payload that was written back
        forms_input = _review_env["smus"].create_asset_revision.call_args.kwargs["forms_input"]
        written = deserialize_form(json.loads(forms_input[0]["content"]), data_source_id=_SOURCE_ID)
        col_status = {c.name: c.business_metadata.review_status for c in written.columns}
        assert col_status == {"col_a": "REJECTED", "col_b": "APPROVED", "col_c": "APPROVED"}

    def test_reject_cascades_to_all_non_rejected_columns(self, _review_env):
        from coa_common.datazone_forms import deserialize_form

        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="APPROVED",
                columns=[
                    {"name": "col_a", "review_status": "PENDING_REVIEW"},
                    {"name": "col_b", "review_status": "REJECTED"},
                    {"name": "col_c", "review_status": "APPROVED"},
                ],
            ),
        )
        _, _ = _parse(
            _dr._handle_review_table(self._event({"decision": "REJECTED"}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        forms_input = _review_env["smus"].create_asset_revision.call_args.kwargs["forms_input"]
        written = deserialize_form(json.loads(forms_input[0]["content"]), data_source_id=_SOURCE_ID)
        col_status = {c.name: c.business_metadata.review_status for c in written.columns}
        assert all(s == "REJECTED" for s in col_status.values())


# ===================================================================
# _handle_update_table_metadata
# ===================================================================


@pytest.mark.unit
class TestUpdateTableMetadata:
    _TABLE_ID = "sales.orders"

    def _event(self, body):
        return {"body": json.dumps(body) if body is not None else "{}"}

    def test_invalid_json_returns_400(self, _review_env):
        status, _ = _parse(_dr._handle_update_table_metadata({"body": "x"}, _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 400

    def test_missing_overrides_returns_400(self, _review_env):
        status, _ = _parse(
            _dr._handle_update_table_metadata(self._event({}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 400

    def test_empty_overrides_returns_400(self, _review_env):
        status, _ = _parse(
            _dr._handle_update_table_metadata(self._event({"overrides": {}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 400

    def test_happy_path_writes_revision_and_marks_steward_edited(self, _review_env):
        from coa_common.datazone_forms import deserialize_form

        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(table_status="PENDING_REVIEW"),
        )
        status, body = _parse(
            _dr._handle_update_table_metadata(
                self._event({"overrides": {"description": "New description", "tags": ["pii"]}}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
            )
        )
        assert status == 200
        # reviewStatus is preserved (PATCH must not change it)
        assert body["reviewStatus"] == "PENDING_REVIEW"
        forms_input = _review_env["smus"].create_asset_revision.call_args.kwargs["forms_input"]
        written = deserialize_form(json.loads(forms_input[0]["content"]), data_source_id=_SOURCE_ID)
        assert written.business_metadata.description == "New description"
        assert written.business_metadata.tags == ["pii"]
        assert written.business_metadata.enrichment_source == "STEWARD_EDITED"
        assert written.business_metadata.review_status == "PENDING_REVIEW"
        # Counter is never touched on metadata edits
        _review_env["dao"].atomic_increment.assert_not_called()

    def test_no_op_when_override_matches_existing(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(description="Existing description"),
        )
        status, _ = _parse(
            _dr._handle_update_table_metadata(
                self._event({"overrides": {"description": "Existing description"}}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
            )
        )
        assert status == 200
        _review_env["smus"].create_asset_revision.assert_not_called()


# ===================================================================
# _handle_review_column
# ===================================================================


@pytest.mark.unit
class TestReviewColumn:
    _TABLE_ID = "sales.orders"
    _COLUMN = "col_a"

    def _event(self, body):
        return {"body": json.dumps(body) if body is not None else "{}"}

    def test_missing_decision_returns_400(self, _review_env):
        status, _ = _parse(
            _dr._handle_review_column(self._event({}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID, self._COLUMN)
        )
        assert status == 400

    def test_column_not_found_returns_404(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(),
        )
        status, _ = _parse(
            _dr._handle_review_column(
                self._event({"decision": "APPROVED"}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
                "ghost_column",
            )
        )
        assert status == 404

    def test_pending_to_approved_writes_revision_no_counter(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(),
        )
        status, body = _parse(
            _dr._handle_review_column(
                self._event({"decision": "APPROVED"}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
                self._COLUMN,
            )
        )
        assert status == 200
        assert body["reviewStatus"] == "APPROVED"
        _review_env["smus"].create_asset_revision.assert_called_once()
        # Column-level review never touches the table-level counter
        _review_env["dao"].atomic_increment.assert_not_called()

    def test_already_approved_column_is_idempotent(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(columns=[{"name": self._COLUMN, "review_status": "APPROVED"}]),
        )
        status, _ = _parse(
            _dr._handle_review_column(
                self._event({"decision": "APPROVED"}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
                self._COLUMN,
            )
        )
        assert status == 200
        _review_env["smus"].create_asset_revision.assert_not_called()


# ===================================================================
# _handle_update_column_metadata
# ===================================================================


@pytest.mark.unit
class TestUpdateColumnMetadata:
    _TABLE_ID = "sales.orders"
    _COLUMN = "col_a"

    def _event(self, body):
        return {"body": json.dumps(body) if body is not None else "{}"}

    def test_missing_overrides_returns_400(self, _review_env):
        status, _ = _parse(
            _dr._handle_update_column_metadata(self._event({}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID, self._COLUMN)
        )
        assert status == 400

    def test_column_not_found_returns_404(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(),
        )
        status, _ = _parse(
            _dr._handle_update_column_metadata(
                self._event({"overrides": {"description": "x"}}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
                "ghost",
            )
        )
        assert status == 404

    def test_happy_path_marks_steward_edited(self, _review_env):
        from coa_common.datazone_forms import deserialize_form

        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(),
        )
        status, body = _parse(
            _dr._handle_update_column_metadata(
                self._event({"overrides": {"description": "New col desc"}}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
                self._COLUMN,
            )
        )
        assert status == 200
        # reviewStatus on the column is unchanged by an edit
        assert body["reviewStatus"] == "PENDING_REVIEW"
        forms_input = _review_env["smus"].create_asset_revision.call_args.kwargs["forms_input"]
        written = deserialize_form(json.loads(forms_input[0]["content"]), data_source_id=_SOURCE_ID)
        col = next(c for c in written.columns if c.name == self._COLUMN)
        assert col.business_metadata.description == "New col desc"
        assert col.business_metadata.enrichment_source == "STEWARD_EDITED"


# ===================================================================
# _handle_approve_source / _handle_reject_source (async bulk)
# ===================================================================


@pytest.fixture
def _bulk_env():
    """Patch dependencies for bulk approve/reject handlers."""
    mock_dao = MagicMock()
    mock_sqs = MagicMock()
    with (
        patch(f"{_DR}._REVIEW_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/review-queue"),
        patch(f"{_DR}._get_dao", return_value=mock_dao),
        patch(f"{_DR}._get_sqs", return_value=mock_sqs),
    ):
        yield {"dao": mock_dao, "sqs": mock_sqs}


@pytest.mark.unit
class TestApproveSource:
    _EVENT = {"body": "{}"}

    def test_happy_path_returns_202_and_sends_sqs(self, _bulk_env):
        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "PENDING_REVIEW",
            "tablesDiscovered": 5,
        }
        # Conditional update succeeds (returns True)
        _bulk_env["dao"].update.return_value = True
        status, body = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 202
        assert body == {"sourceId": _SOURCE_ID, "status": "APPROVING"}
        # Conditional update was called with the right transition condition.
        # The helper builds dynamic IN-clause placeholders, so assert by value-set
        # rather than pinning specific placeholder names.
        update_call = _bulk_env["dao"].update.call_args
        assert set(update_call.kwargs["condition_values"].values()) == {
            "PENDING_REVIEW",
            "APPROVAL_FAILED",
        }
        assert "#status" in update_call.kwargs["condition_names"]
        # SQS message contains decision=APPROVED
        sqs_call = _bulk_env["sqs"].send_message.call_args
        assert sqs_call.kwargs["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123/review-queue"
        msg_body = json.loads(sqs_call.kwargs["MessageBody"])
        assert msg_body == {
            "namespaceId": _NAMESPACE_ID,
            "sourceId": _SOURCE_ID,
            "decision": "APPROVED",
        }

    def test_approve_from_rejected_source_is_locked_409(self, _bulk_env):
        # REJECTED is terminal: bulk approve is not an allowed entry state
        # either — a rejected source cannot be resurrected, only re-onboarded.
        from botocore.exceptions import ClientError

        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "REJECTED",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "UpdateItem"
        )
        status, body = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 409
        assert "REJECTED" in body["error"]
        _bulk_env["sqs"].send_message.assert_not_called()

    def test_source_not_found_returns_404(self, _bulk_env):
        _bulk_env["dao"].get.return_value = None
        status, _ = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 404
        _bulk_env["sqs"].send_message.assert_not_called()

    def test_non_database_source_returns_400(self, _bulk_env):
        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DOCUMENTS",
            "status": "PENDING_REVIEW",
        }
        status, _ = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 400
        _bulk_env["sqs"].send_message.assert_not_called()

    def test_already_approving_returns_409(self, _bulk_env):
        from botocore.exceptions import ClientError

        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "APPROVING",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
        )
        status, body = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 409
        assert "APPROVING" in body["error"]
        _bulk_env["sqs"].send_message.assert_not_called()

    def test_retry_from_approval_failed_succeeds(self, _bulk_env):
        # User retries after a previous failure — should be allowed
        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "APPROVAL_FAILED",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.return_value = True
        status, _ = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 202

    def test_review_queue_url_unset_returns_500(self):
        mock_dao = MagicMock()
        mock_dao.get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "PENDING_REVIEW",
            "tablesDiscovered": 5,
        }
        mock_dao.update.return_value = True
        with (
            patch(f"{_DR}._REVIEW_QUEUE_URL", ""),
            patch(f"{_DR}._get_dao", return_value=mock_dao),
        ):
            status, _ = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 500

    def test_sqs_failure_rolls_back_status(self, _bulk_env):
        from botocore.exceptions import ClientError

        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "PENDING_REVIEW",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.return_value = True
        _bulk_env["sqs"].send_message.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "SendMessage")
        status, _ = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 500
        # Two update calls: first to APPROVING, second rollback to APPROVAL_FAILED
        assert _bulk_env["dao"].update.call_count == 2
        rollback_call = _bulk_env["dao"].update.call_args_list[1]
        assert rollback_call.args[1] == {"status": "APPROVAL_FAILED"}


@pytest.mark.unit
class TestRejectSource:
    _EVENT = {"body": "{}"}

    def test_happy_path_returns_202_and_sends_reject_decision(self, _bulk_env):
        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "PENDING_REVIEW",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.return_value = True
        status, body = _parse(_dr._handle_reject_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 202
        # Reject flow uses REJECTING (not APPROVING) for the transient state
        assert body == {"sourceId": _SOURCE_ID, "status": "REJECTING"}
        msg_body = json.loads(_bulk_env["sqs"].send_message.call_args.kwargs["MessageBody"])
        assert msg_body["decision"] == "REJECTED"
        # Conditional update allows entry from PENDING_REVIEW or REJECTION_FAILED
        update_call = _bulk_env["dao"].update.call_args
        assert set(update_call.kwargs["condition_values"].values()) == {
            "PENDING_REVIEW",
            "REJECTION_FAILED",
        }

    def test_retry_from_rejection_failed_succeeds(self, _bulk_env):
        # User retries after a previous reject worker failure
        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "REJECTION_FAILED",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.return_value = True
        status, body = _parse(_dr._handle_reject_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 202
        assert body["status"] == "REJECTING"

    def test_sqs_failure_rolls_back_to_rejection_failed(self, _bulk_env):
        from botocore.exceptions import ClientError

        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "PENDING_REVIEW",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.return_value = True
        _bulk_env["sqs"].send_message.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "SendMessage")
        status, _ = _parse(_dr._handle_reject_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 500
        # Rollback uses REJECTION_FAILED, not APPROVAL_FAILED
        rollback_call = _bulk_env["dao"].update.call_args_list[1]
        assert rollback_call.args[1] == {"status": "REJECTION_FAILED"}

    def test_reject_from_rejected_source_is_locked_409(self, _bulk_env):
        # REJECTED is terminal: bulk reject is not an allowed entry state, so
        # the conditional transition fails and the source stays locked.
        from botocore.exceptions import ClientError

        _bulk_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "REJECTED",
            "tablesDiscovered": 5,
        }
        _bulk_env["dao"].update.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "UpdateItem"
        )
        status, body = _parse(_dr._handle_reject_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 409
        assert "REJECTED" in body["error"]
        _bulk_env["sqs"].send_message.assert_not_called()


# ===================================================================
# Bulk-review zero-tables precondition
#
# ApproveSource and RejectSource must reject the call if the source has
# zero discovered tables. The UI also disables the buttons in that case;
# this guard prevents direct API misuse from leaving the source stuck in
# APPROVING / REJECTING with no work to do.
# ===================================================================


@pytest.mark.unit
class TestBulkReviewZeroTablesGuard:
    _EVENT = {"body": "{}"}

    @pytest.mark.parametrize("missing_tables_value", [None, 0])
    def test_approve_with_zero_tables_returns_400(self, _bulk_env, missing_tables_value):
        item = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "PENDING_REVIEW",
        }
        if missing_tables_value is not None:
            item["tablesDiscovered"] = missing_tables_value
        _bulk_env["dao"].get.return_value = item
        status, body = _parse(_dr._handle_approve_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 400
        assert "tablesDiscovered" in body
        assert body["tablesDiscovered"] == 0
        # Must not transition the source or send a worker message.
        _bulk_env["dao"].update.assert_not_called()
        _bulk_env["sqs"].send_message.assert_not_called()

    @pytest.mark.parametrize("missing_tables_value", [None, 0])
    def test_reject_with_zero_tables_returns_400(self, _bulk_env, missing_tables_value):
        item = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "PENDING_REVIEW",
        }
        if missing_tables_value is not None:
            item["tablesDiscovered"] = missing_tables_value
        _bulk_env["dao"].get.return_value = item
        status, body = _parse(_dr._handle_reject_source(self._EVENT, _NAMESPACE_ID, _SOURCE_ID))
        assert status == 400
        assert "tablesDiscovered" in body
        _bulk_env["dao"].update.assert_not_called()
        _bulk_env["sqs"].send_message.assert_not_called()


# ===================================================================
# Reviewable-state guard (_assert_source_reviewable)
#
# The guard runs before per-table/column review and edit operations to
# prevent races with the bulk worker (and to block ops during scan/enrich).
# These tests pin every transition point: which states are allowed through,
# which return 409, plus the missing-source and non-DATABASE error paths.
# ===================================================================


@pytest.mark.unit
class TestReviewableGuard:
    """The guard protects per-table/column review AND edit endpoints."""

    _TABLE_ID = "sales.orders"
    _COLUMN = "col_a"

    def _approve_event(self):
        return {"body": json.dumps({"decision": "APPROVED"})}

    def _override_event(self):
        return {"body": json.dumps({"overrides": {"description": "x"}})}

    @pytest.mark.parametrize(
        "status",
        ["PENDING_REVIEW", "APPROVED", "APPROVAL_FAILED", "REJECTION_FAILED"],
    )
    def test_review_table_allows_all_reviewable_states(self, _review_env, status):
        _review_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": status,
        }
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                columns=[{"name": "col_a", "review_status": "APPROVED"}],
            ),
        )
        resp_status, _ = _parse(
            _dr._handle_review_table(self._approve_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert resp_status == 200

    @pytest.mark.parametrize(
        "status",
        ["REGISTERED", "SCANNING", "ENRICHING", "APPROVING", "REJECTING", "REJECTED", "DELETING"],
    )
    def test_review_table_blocks_non_reviewable_states_with_409(self, _review_env, status):
        _review_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": status,
        }
        resp_status, body = _parse(
            _dr._handle_review_table(self._approve_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert resp_status == 409
        assert status in body["error"]
        # No DataZone calls should have been made
        _review_env["smus"].search_assets.assert_not_called()
        _review_env["smus"].create_asset_revision.assert_not_called()

    def test_review_table_404_when_source_missing(self, _review_env):
        _review_env["dao"].get.return_value = None
        resp_status, _ = _parse(
            _dr._handle_review_table(self._approve_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert resp_status == 404

    def test_409_body_structure_preserves_status_and_allowed_states(self, _review_env):
        # The UI renders the 409 body's "error" string directly, so its exact
        # structure is a contract: a single "error" key whose message embeds the
        # offending status and the sorted list of reviewable states.
        _review_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "APPROVING",
        }
        resp_status, body = _parse(
            _dr._handle_review_table(self._approve_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert resp_status == 409
        # Exactly one field, named "error", carrying a human-readable string.
        assert list(body.keys()) == ["error"]
        assert isinstance(body["error"], str)
        # The blocking status must be preserved verbatim for the user.
        assert "APPROVING" in body["error"]
        # Each allowed state is named so the user knows when the action is valid.
        for allowed in ("PENDING_REVIEW", "APPROVED"):
            assert allowed in body["error"]

    def test_review_table_400_when_source_not_database(self, _review_env):
        _review_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DOCUMENTS",
            "status": "PENDING_REVIEW",
        }
        resp_status, _ = _parse(
            _dr._handle_review_table(self._approve_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert resp_status == 400

    def test_update_table_metadata_blocks_during_approving(self, _review_env):
        _review_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "APPROVING",
        }
        resp_status, _ = _parse(
            _dr._handle_update_table_metadata(self._override_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert resp_status == 409
        # Without the guard, this is the silent-edit-loss race scenario.
        _review_env["smus"].create_asset_revision.assert_not_called()

    def test_review_column_blocks_during_rejecting(self, _review_env):
        _review_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "REJECTING",
        }
        resp_status, _ = _parse(
            _dr._handle_review_column(self._approve_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID, self._COLUMN)
        )
        assert resp_status == 409

    def test_update_column_metadata_blocks_during_enriching(self, _review_env):
        _review_env["dao"].get.return_value = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": f"SRC#{_SOURCE_ID}",
            "sourceType": "DATABASE",
            "status": "ENRICHING",
        }
        resp_status, _ = _parse(
            _dr._handle_update_column_metadata(
                self._override_event(), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID, self._COLUMN
            )
        )
        assert resp_status == 409


# ===================================================================
# _handle_update_table_keys
# ===================================================================


@pytest.mark.unit
class TestTerminalEditGuard:
    """Metadata and key edits are blocked (409) once an asset is APPROVED or REJECTED."""

    _TABLE_ID = "sales.orders"

    def _event(self, body):
        return {"body": json.dumps(body)}

    @pytest.mark.parametrize("terminal", ["REJECTED"])
    def test_table_metadata_edit_blocked_when_terminal(self, _review_env, terminal):
        _mock_single_asset_load(
            _review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table(table_status=terminal)
        )
        status, body = _parse(
            _dr._handle_update_table_metadata(
                self._event({"overrides": {"description": "x"}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
            )
        )
        assert status == 409
        assert "terminal" in body["error"].lower()
        _review_env["smus"].create_asset_revision.assert_not_called()

    @pytest.mark.parametrize("terminal", ["REJECTED"])
    def test_table_keys_edit_blocked_when_terminal(self, _review_env, terminal):
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(table_status=terminal, columns=[{"name": "id", "review_status": terminal}]),
        )
        status, _ = _parse(
            _dr._handle_update_table_keys(
                self._event({"primaryKey": {"columns": ["id"]}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
            )
        )
        assert status == 409
        _review_env["smus"].create_asset_revision.assert_not_called()

    @pytest.mark.parametrize("terminal", ["REJECTED"])
    def test_column_metadata_edit_blocked_when_terminal(self, _review_env, terminal):
        # Source/table reviewable; only the column itself is terminal → 409.
        _mock_single_asset_load(
            _review_env["smus"],
            table_id=self._TABLE_ID,
            form_content=_serialize_table(
                table_status="PENDING_REVIEW",
                columns=[{"name": "col_a", "review_status": terminal}],
            ),
        )
        status, _ = _parse(
            _dr._handle_update_column_metadata(
                self._event({"overrides": {"description": "x"}}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
                "col_a",
            )
        )
        assert status == 409
        _review_env["smus"].create_asset_revision.assert_not_called()

    def test_table_metadata_edit_allowed_when_pending(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table(table_status="PENDING_REVIEW")
        )
        status, _ = _parse(
            _dr._handle_update_table_metadata(
                self._event({"overrides": {"description": "x"}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
            )
        )
        assert status == 200

    def test_table_metadata_edit_allowed_when_approved(self, _review_env):
        _mock_single_asset_load(
            _review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table(table_status="APPROVED")
        )
        status, _ = _parse(
            _dr._handle_update_table_metadata(
                self._event({"overrides": {"description": "x"}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
            )
        )
        assert status == 200


@pytest.mark.unit
class TestUpdateTableKeys:
    _TABLE_ID = "sales.orders"

    def _event(self, body):
        return {"body": json.dumps(body) if body is not None else "{}"}

    def _written_table(self, _review_env):
        from coa_common.datazone_forms import deserialize_form

        forms_input = _review_env["smus"].create_asset_revision.call_args.kwargs["forms_input"]
        return deserialize_form(json.loads(forms_input[0]["content"]), data_source_id=_SOURCE_ID)

    def test_invalid_json_returns_400(self, _review_env):
        status, _ = _parse(
            _dr._handle_update_table_keys({"body": "not-json"}, _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID)
        )
        assert status == 400

    def test_missing_both_returns_400(self, _review_env):
        status, body = _parse(_dr._handle_update_table_keys(self._event({}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 400
        assert "primaryKey" in body["error"]

    def test_set_primary_key_marks_steward_specified(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table())
        status, _ = _parse(
            _dr._handle_update_table_keys(
                self._event({"primaryKey": {"columns": ["col_a"]}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
            )
        )
        assert status == 200
        table = self._written_table(_review_env)
        assert table.primary_key.columns == ["col_a"]
        assert table.primary_key.source == "STEWARD_SPECIFIED"

    def test_duplicate_primary_key_columns_are_deduped(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table())
        status, _ = _parse(
            _dr._handle_update_table_keys(
                self._event({"primaryKey": {"columns": ["col_a", "col_b", "col_a"]}}),
                _NAMESPACE_ID,
                _SOURCE_ID,
                self._TABLE_ID,
            )
        )
        assert status == 200
        assert self._written_table(_review_env).primary_key.columns == ["col_a", "col_b"]

    def _form_with_keys(self):
        form = json.loads(_serialize_table())
        form["primaryKeyColumns"] = json.dumps(["col_a"])
        form["primaryKeySource"] = "DETERMINISTIC"
        form["foreignKeys"] = json.dumps(
            [{"column": "col_a", "target_table": "customers", "target_column": "id", "source": "DETERMINISTIC"}]
        )
        return json.dumps(form)

    def test_unchanged_primary_key_keeps_original_source(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=self._form_with_keys())
        status, _ = _parse(
            _dr._handle_update_table_keys(
                self._event({"primaryKey": {"columns": ["col_a"]}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
            )
        )
        assert status == 200
        assert self._written_table(_review_env).primary_key.source == "DETERMINISTIC"

    def test_unchanged_foreign_key_kept_only_edited_one_marked_steward(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=self._form_with_keys())
        # Re-send the existing FK unchanged plus one new FK (simulates the UI
        # sending the full list when only adding one).
        body = {
            "foreignKeys": [
                {"column": "col_a", "targetTable": "customers", "targetColumn": "id"},
                {"column": "col_b", "targetTable": "orders", "targetColumn": "id"},
            ]
        }
        status, _ = _parse(_dr._handle_update_table_keys(self._event(body), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 200
        by_col = {fk.column: fk.source for fk in self._written_table(_review_env).foreign_keys}
        assert by_col == {"col_a": "DETERMINISTIC", "col_b": "STEWARD_SPECIFIED"}

    def test_unknown_primary_key_column_returns_400(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table())
        status, _ = _parse(
            _dr._handle_update_table_keys(
                self._event({"primaryKey": {"columns": ["nope"]}}), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID
            )
        )
        assert status == 400
        _review_env["smus"].create_asset_revision.assert_not_called()

    def test_set_foreign_keys_marks_steward_specified(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table())
        body = {"foreignKeys": [{"column": "col_a", "targetTable": "customers", "targetColumn": "id"}]}
        status, _ = _parse(_dr._handle_update_table_keys(self._event(body), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 200
        table = self._written_table(_review_env)
        assert len(table.foreign_keys) == 1
        assert table.foreign_keys[0].column == "col_a"
        assert table.foreign_keys[0].target_table == "customers"
        assert table.foreign_keys[0].source == "STEWARD_SPECIFIED"

    def test_foreign_key_unknown_column_returns_400(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table())
        body = {"foreignKeys": [{"column": "nope", "targetTable": "customers"}]}
        status, _ = _parse(_dr._handle_update_table_keys(self._event(body), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 400

    def test_foreign_key_missing_target_returns_400(self, _review_env):
        _mock_single_asset_load(_review_env["smus"], table_id=self._TABLE_ID, form_content=_serialize_table())
        body = {"foreignKeys": [{"column": "col_a"}]}
        status, _ = _parse(_dr._handle_update_table_keys(self._event(body), _NAMESPACE_ID, _SOURCE_ID, self._TABLE_ID))
        assert status == 400
