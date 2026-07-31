# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for data source / ontology lookup implementations."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def _lookup():
    from coa_metrics.lookups import SmusCatalogDataSourceLookup

    return SmusCatalogDataSourceLookup(
        domain_id="dzd-1",
        project_id="prj-1",
        namespace_id="ns-1",
        datasources_table="sources-tbl",
        region="us-east-1",
    )


_CATALOG = {
    "sources": [
        {
            "datasourceId": "ds-1",
            "databases": [
                {
                    "tables": [
                        {
                            "name": "Orders",
                            "columns": [
                                {"name": "order_id", "type": "integer"},
                                {"name": "amount", "type": "decimal"},
                                {"name": "", "type": "ignored"},  # empty name → skipped
                                {"type": "no_name_key"},  # missing name → skipped
                            ],
                        },
                        {"name": "", "columns": []},  # empty table name → skipped
                    ]
                }
            ],
        }
    ]
}


class TestSmusCatalogDataSourceLookup:
    """Tests for the SMUS catalog-backed data source lookup."""

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_data_source_exists_true_when_in_catalog(self, mock_read):
        mock_read.return_value = _CATALOG
        lookup = _lookup()

        assert lookup.data_source_exists("ds-1") is True
        # Cached: a second lookup does not re-read the catalog.
        assert lookup.data_source_exists("ds-1") is True
        mock_read.assert_called_once()

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_data_source_exists_false_when_absent(self, mock_read):
        mock_read.return_value = {"sources": []}
        lookup = _lookup()

        assert lookup.data_source_exists("ds-missing") is False

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_table_exists_is_case_insensitive(self, mock_read):
        mock_read.return_value = _CATALOG
        lookup = _lookup()

        assert lookup.table_exists("ds-1", "orders") is True
        assert lookup.table_exists("ds-1", "ORDERS") is True
        assert lookup.table_exists("ds-1", "customers") is False

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_get_table_columns_returns_named_columns_only(self, mock_read):
        mock_read.return_value = _CATALOG
        lookup = _lookup()

        columns = lookup.get_table_columns("ds-1", "orders")

        assert columns is not None
        assert [c.name for c in columns] == ["order_id", "amount"]

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_get_table_columns_none_for_unknown_source(self, mock_read):
        mock_read.return_value = {"sources": []}
        lookup = _lookup()

        assert lookup.get_table_columns("ds-unknown", "orders") is None

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_get_column_type_case_insensitive_match(self, mock_read):
        mock_read.return_value = _CATALOG
        lookup = _lookup()

        assert lookup.get_column_type("ds-1", "orders", "ORDER_ID") == "integer"
        assert lookup.get_column_type("ds-1", "orders", "amount") == "decimal"

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_get_column_type_returns_none_for_missing_column(self, mock_read):
        mock_read.return_value = _CATALOG
        lookup = _lookup()

        assert lookup.get_column_type("ds-1", "orders", "no_such_col") is None

    @patch("coa_common.metadata_store.catalog_reader.read_approved_catalog")
    def test_catalog_read_failure_degrades_to_empty(self, mock_read):
        mock_read.side_effect = RuntimeError("catalog down")
        lookup = _lookup()

        assert lookup.data_source_exists("ds-1") is False
        assert lookup.table_exists("ds-1", "orders") is False
        assert lookup.get_table_columns("ds-1", "orders") is None


class TestNeptuneOntologyLookup:
    """Tests for the Neptune SPARQL-backed ontology class check."""

    def _build(self):
        from coa_metrics.lookups import NeptuneOntologyLookup

        return NeptuneOntologyLookup()

    def test_rejects_malformed_class_uri(self):
        lookup = self._build()

        # No prefix separator → rejected before any query.
        assert lookup.class_exists("not a curie", "ns-1") is False

    def test_non_string_class_uri_rejected(self):
        lookup = self._build()

        assert lookup.class_exists(None, "ns-1") is False  # type: ignore[arg-type]

    def test_returns_true_when_sparql_ask_true(self):
        lookup = self._build()

        with patch.object(lookup, "_sparql_query", return_value={"boolean": True}) as q:
            assert lookup.class_exists("ind:Order", "ns-1") is True
        q.assert_called_once()

    def test_returns_false_when_sparql_ask_false(self):
        lookup = self._build()

        with patch.object(lookup, "_sparql_query", return_value={"boolean": False}):
            assert lookup.class_exists("ind:Order", "ns-1") is False

    def test_fails_open_on_sparql_error(self):
        lookup = self._build()

        with patch.object(lookup, "_sparql_query", side_effect=RuntimeError("neptune down")):
            # Fail open — Neptune errors must not block validation.
            assert lookup.class_exists("ind:Order", "ns-1") is False
