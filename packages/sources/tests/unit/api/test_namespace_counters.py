# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for ``adjust_namespace_source_count``.

The counter helper drives the ``sourceCount`` attribute the UI displays
on the namespace list and detail pages. The function is best-effort: a
transient DynamoDB error or a missing ``NAMESPACES_TABLE`` env var must
not block the source create/delete workflow that calls it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from coa_sources.api import namespace_counters

_MODULE = "coa_sources.api.namespace_counters"


@pytest.fixture(autouse=True)
def _reset_lazy_dao():
    """Clear the cached DAO between tests to honor patched env vars."""
    namespace_counters._ns_dao = None
    yield
    namespace_counters._ns_dao = None


@pytest.fixture(autouse=True)
def _ensure_table_env(monkeypatch):
    monkeypatch.setenv("NAMESPACES_TABLE", "test-namespaces")


@pytest.mark.unit
class TestAdjustNamespaceSourceCount:
    def test_increment_targets_source_count(self):
        mock_dao = MagicMock()
        with patch(f"{_MODULE}._get_ns_dao", return_value=mock_dao):
            namespace_counters.adjust_namespace_source_count("ns-1", "DATABASE", 1)
        mock_dao.atomic_increment.assert_called_once_with(
            key={"PK": "NS#ns-1", "SK": "METADATA"},
            attribute="sourceCount",
            amount=1,
        )

    def test_decrement_targets_source_count(self):
        mock_dao = MagicMock()
        with patch(f"{_MODULE}._get_ns_dao", return_value=mock_dao):
            namespace_counters.adjust_namespace_source_count("ns-1", "DOCUMENTS", -1)
        mock_dao.atomic_increment.assert_called_once_with(
            key={"PK": "NS#ns-1", "SK": "METADATA"},
            attribute="sourceCount",
            amount=-1,
        )

    def test_zero_delta_is_a_noop(self):
        mock_dao = MagicMock()
        with patch(f"{_MODULE}._get_ns_dao", return_value=mock_dao):
            namespace_counters.adjust_namespace_source_count("ns-1", "DATABASE", 0)
        mock_dao.atomic_increment.assert_not_called()

    def test_swallows_client_error_so_caller_is_not_blocked(self):
        mock_dao = MagicMock()
        mock_dao.atomic_increment.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "UpdateItem")
        with patch(f"{_MODULE}._get_ns_dao", return_value=mock_dao):
            namespace_counters.adjust_namespace_source_count("ns-1", "DATABASE", 1)

    def test_skips_when_namespaces_table_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("NAMESPACES_TABLE", raising=False)
        with patch(f"{_MODULE}._NAMESPACES_TABLE", ""):
            namespace_counters.adjust_namespace_source_count("ns-1", "DATABASE", 1)
