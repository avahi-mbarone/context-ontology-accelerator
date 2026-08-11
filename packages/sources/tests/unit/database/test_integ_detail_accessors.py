# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests pinning the GetSource field paths the integ suite reads.

These exist because getting a path wrong is a SILENT test bug: reading a nested
field off the top level yields ``None``, and the assertion then reports "the
pipeline never produced it" on a scan that in fact succeeded. That happened —
`athenaDataCatalogName` was read off the top level while the API nests it under
``databaseDetails`` — so the contract is now asserted here, without needing a
deployed environment.

The sample payload is a real GetSource response for a completed Oracle scan.
"""

from __future__ import annotations

import pytest

from tests.shared.detail_helpers import database_details, source_scan_error

pytestmark = pytest.mark.unit

_ORACLE_DETAIL = {
    "sourceId": "45a125cf-730e-4680-82d8-f713f299d60c",
    "namespaceId": "0006eda7-4cee-4d57-bfaf-3ef0089546c8",
    "name": "integ-catalog-oracle-c994498b",
    "sourceType": "DATABASE",
    "sourceSubType": "JDBC_DATABASE",
    "status": "PENDING_REVIEW",
    "databaseDetails": {
        "jdbcConfiguration": {
            "engine": "ORACLE",
            "host": "scl-integ-test-databases-ora-0c754f0ccbcdc7d6.elb.us-east-1.amazonaws.com",
            "port": 1521,
            "databaseName": "FREEPDB1",
            "schemaFilter": "SCL_TEST",
        },
        "metadataEnrichmentEnabled": False,
        "tablesDiscovered": 8.0,
        "lastScanJobId": "2026-08-05T15:59:00Z",
        "glueConnectionName": "scldevds_09f896f977de809c",
        "athenaDataCatalogName": "scldevds_09f896f977de809c",
    },
}


def test_federation_refs_are_read_from_database_details() -> None:
    """The regression: these live under databaseDetails, never at the top level."""
    details = database_details(_ORACLE_DETAIL)
    assert details["athenaDataCatalogName"] == "scldevds_09f896f977de809c"
    assert details["glueConnectionName"] == "scldevds_09f896f977de809c"
    assert details["lastScanJobId"] == "2026-08-05T15:59:00Z"
    # Proof the top level does NOT carry them — a direct .get() would be None and
    # every catalog assertion would fail on a perfectly good scan.
    assert _ORACLE_DETAIL.get("athenaDataCatalogName") is None


def test_jdbc_configuration_is_read_from_database_details() -> None:
    """`databaseSource` is the CREATE shape; responses use `databaseDetails`."""
    jdbc = database_details(_ORACLE_DETAIL)["jdbcConfiguration"]
    assert jdbc["engine"] == "ORACLE"
    assert _ORACLE_DETAIL.get("databaseSource") is None


def test_database_details_missing_or_null_is_an_empty_dict() -> None:
    """A pre-scan source has no details yet — callers must still be able to .get()."""
    assert database_details({}) == {}
    assert database_details({"databaseDetails": None}) == {}


def test_scan_error_returns_empty_without_a_scan_job_id() -> None:
    """No job id means no lookup: classification degrades to "unknown", not a crash."""
    assert source_scan_error("https://api.example.com", {}, "ns", "src", {}) == ""
