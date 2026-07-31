# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Smoke tests — verify all database pipeline modules import cleanly.

These catch broken imports (e.g. references to deleted Smithy models) that
would only surface at Lambda cold-start time in production.
"""

import importlib
import os
import sys
import unittest.mock as mock

_ENV = {
    "SMUS_DOMAIN_ID": "test-domain",
    "SOURCES_TABLE": "test-sources",
    "DATASOURCES_TABLE": "test-sources",
    "SOURCE_SCAN_JOBS_TABLE": "test-scan-jobs",
    "SCAN_JOBS_TABLE": "test-scan-jobs",
    "NAMESPACES_TABLE": "test-namespaces",
    "PROJECT_ACCESS_ROLE_ARN": "arn:aws:iam::123456789012:role/test",
}


def _fresh_import(module_name: str) -> None:
    """Import a module fresh (removing any cached version) with test env vars."""
    sys.modules.pop(module_name, None)
    with mock.patch.dict(os.environ, _ENV):
        importlib.import_module(module_name)


def test_connectors_import():
    """database/connectors/__init__.py must import without error."""
    from coa_sources.database.connectors import (  # noqa: F401
        GlueCatalogConnector,
        JdbcConnector,
        MetadataConnector,
        get_connector,
    )


def test_discovery_handler_import():
    """database/pipeline/discovery_handler must import without error."""
    _fresh_import("coa_sources.database.pipeline.discovery_handler")


def test_enrichment_handler_import():
    """database/pipeline/enrichment_handler must import without error."""
    _fresh_import("coa_sources.database.pipeline.enrichment_handler")
