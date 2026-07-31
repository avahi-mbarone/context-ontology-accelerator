# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for metric validation module — Checks 1-6.

Tests cover:
- Check 1: SQL syntax validation (ERROR severity)
- Check 2: Table reference existence (WARNING)
- Check 3: Column reference existence (WARNING)
- Check 4: Dimension column existence (WARNING)
- Check 5: Filter type compatibility (WARNING)
- Check 6: Ontology class linkage (WARNING)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from coa_common.constants import URN_PREFIX
from coa_metrics.validator import (
    ColumnMetadata,
    DataSourceLookup,
    DynamoDBDataSourceLookup,
    NeptuneOntologyLookup,
    OntologyLookup,
    check_select_shape,
    validate_metric,
)

pytestmark = pytest.mark.unit


# ── Mock implementations ────────────────────────────────────────────────


class MockDataSourceLookup(DataSourceLookup):
    """Mock lookup with configurable data sources, tables, and columns."""

    def __init__(
        self,
        sources: set[str] | None = None,
        tables: dict[str, set[str]] | None = None,
        columns: dict[str, list[ColumnMetadata]] | None = None,
    ) -> None:
        self._sources = sources or set()
        self._tables = tables or {}
        self._columns = columns or {}

    def data_source_exists(self, data_source_id: str) -> bool:
        return data_source_id in self._sources

    def table_exists(self, data_source_id: str, table_name: str) -> bool:
        ds_tables = self._tables.get(data_source_id, set())
        # Case-insensitive table lookup
        return table_name.lower() in {t.lower() for t in ds_tables}

    def get_table_columns(self, data_source_id: str, table_name: str) -> list[ColumnMetadata] | None:
        key = f"{data_source_id}:{table_name.lower()}"
        return self._columns.get(key)


class MockOntologyLookup(OntologyLookup):
    """Mock ontology lookup with configurable existing classes."""

    def __init__(self, existing_classes: set[str] | None = None) -> None:
        self._classes = existing_classes or set()

    def class_exists(self, class_uri: str, namespace: str) -> bool:
        return class_uri in self._classes


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def valid_metric() -> dict:
    """A valid metric body with all fields populated."""
    return {
        "name": "monthly_revenue",
        "description": "Total revenue from all orders in a calendar month",
        "expression": {
            "dialects": [
                {
                    "dialect": "postgresql",
                    "expression": (
                        "SELECT region, SUM(total_amount) AS monthly_revenue"
                        " FROM orders WHERE status = 'completed' GROUP BY region"
                    ),
                },
            ]
        },
        "dataSourceId": "ds-abc123",
        "sourceTable": "orders",
        "ontologyConcepts": ["ind:Order"],
    }


@pytest.fixture
def fragment_metric() -> dict:
    """A metric with aggregate fragment (no SELECT/GROUP BY)."""
    return {
        "name": "total_sales",
        "description": "Sum of sales",
        "expression": {
            "dialects": [
                {"dialect": "trino", "expression": "SUM(orders.total_amount)"},
            ]
        },
        "dataSourceId": "ds-abc123",
        "sourceTable": "orders",
        "ontologyConcepts": [],
    }


@pytest.fixture
def lookup() -> MockDataSourceLookup:
    """Standard lookup with orders table and common columns."""
    return MockDataSourceLookup(
        sources={"ds-abc123"},
        tables={"ds-abc123": {"orders", "customers"}},
        columns={
            "ds-abc123:orders": [
                ColumnMetadata(name="total_amount", data_type="decimal"),
                ColumnMetadata(name="region", data_type="varchar"),
                ColumnMetadata(name="order_date", data_type="date"),
                ColumnMetadata(name="status", data_type="varchar"),
                ColumnMetadata(name="customer_id", data_type="integer"),
            ],
            "ds-abc123:customers": [
                ColumnMetadata(name="id", data_type="integer"),
                ColumnMetadata(name="name", data_type="varchar"),
            ],
        },
    )


@pytest.fixture
def ontology_lookup() -> MockOntologyLookup:
    """Ontology with Order and Customer classes."""
    return MockOntologyLookup(existing_classes={"ind:Order", "ind:Customer"})


# ── Check 1: SQL Syntax ─────────────────────────────────────────────────


class TestCheck1SqlSyntax:
    """Check 1: SQL parses without syntax errors in declared dialect."""

    def test_valid_sql_passes(self, valid_metric: dict) -> None:
        result = validate_metric(valid_metric)
        assert result.valid
        assert len(result.errors) == 0

    def test_fragment_fails_shape_check(self, fragment_metric: dict) -> None:
        """#617: fragments parse fine but the serve firewall rejects them —
        the sql_shape check must flag them so validate predicts serve-time
        acceptance (previously this asserted fragments were valid)."""
        result = validate_metric(fragment_metric)
        assert not result.valid
        shape_errors = [e for e in result.errors if e["check"] == "sql_shape"]
        assert len(shape_errors) == 1
        assert "full SELECT statement" in shape_errors[0]["message"]

    def test_invalid_sql_produces_error(self) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "postgresql", "expression": "SELECT FROM WHERE"}]},
            "dataSourceId": "ds-1",
            "sourceTable": "t",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric)
        # Check 1 errors block validation
        assert not result.valid
        assert len(result.errors) >= 1
        assert result.errors[0]["check"] == "sql_syntax"
        assert result.errors[0]["severity"] == "error"

    def test_multiple_dialects_validated_independently(self) -> None:
        metric = {
            "expression": {
                "dialects": [
                    {"dialect": "trino", "expression": "SUM(amount)"},
                    {"dialect": "postgresql", "expression": "INVALID SQL {{{{"},
                ]
            },
            "dataSourceId": "ds-1",
            "sourceTable": "t",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric)
        # One dialect fails, one passes
        assert not result.valid
        assert len(result.errors) >= 1

    def test_empty_expression_produces_error(self) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": ""}]},
            "dataSourceId": "ds-1",
            "sourceTable": "t",
            "ontologyConcepts": [],
        }
        # Empty string — no SQL to parse, should not error
        result = validate_metric(metric)
        assert result.valid

    def test_all_supported_dialects(self) -> None:
        for dialect in ["trino", "postgresql", "redshift", "snowflake", "mysql", "databricks"]:
            metric = {
                "expression": {"dialects": [{"dialect": dialect, "expression": "SELECT SUM(amount) FROM t"}]},
                "dataSourceId": "ds-1",
                "sourceTable": "t",
                "ontologyConcepts": [],
            }
            result = validate_metric(metric)
            assert result.valid, f"Failed for dialect: {dialect}"


# ── Check 1b: Statement shape (serve-firewall parity, #617) ─────────────


class TestCheckSelectShape:
    """check_select_shape mirrors the serve firewall's SELECT-only rule."""

    def test_full_select_passes(self) -> None:
        assert check_select_shape("SELECT COUNT(*) AS total FROM orders", "TRINO") is None

    def test_cte_select_passes(self) -> None:
        sql = "WITH t AS (SELECT amount FROM orders) SELECT SUM(amount) FROM t"
        assert check_select_shape(sql, "POSTGRESQL") is None

    def test_union_passes(self) -> None:
        sql = "SELECT id FROM a UNION SELECT id FROM b"
        assert check_select_shape(sql, "TRINO") is None

    def test_count_fragment_rejected(self) -> None:
        error = check_select_shape("COUNT(*)", "TRINO")
        assert error is not None
        assert "full SELECT statement" in error
        assert "SELECT COUNT(*) FROM <source_table>" in error

    def test_sum_fragment_rejected(self) -> None:
        error = check_select_shape("SUM(orders.total_amount)", "POSTGRESQL")
        assert error is not None
        assert "full SELECT statement" in error

    def test_unparseable_sql_rejected(self) -> None:
        error = check_select_shape("SELECT FROM WHERE (((", "TRINO")
        assert error is not None

    def test_unknown_dialect_still_checks_shape(self) -> None:
        # Unresolvable dialect falls back to sqlglot's default parser
        assert check_select_shape("SELECT 1", "NOT_A_DIALECT") is None
        assert check_select_shape("COUNT(*)", "NOT_A_DIALECT") is not None

    # ── Deep scan: data-modifying nodes nested inside a SELECT ──────────
    # Mirrors sql_firewall.py's _DATA_MODIFYING_NODES walk — a top-level
    # SELECT can smuggle DML through a CTE, which the firewall rejects at
    # query time, so onboarding must reject it too.

    def test_data_modifying_cte_delete_rejected(self) -> None:
        sql = "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d"
        error = check_select_shape(sql, "POSTGRESQL")
        assert error is not None
        assert "data-modifying" in error
        assert "Delete" in error

    def test_data_modifying_cte_insert_rejected(self) -> None:
        sql = "WITH i AS (INSERT INTO audit (id) VALUES (1) RETURNING *) SELECT * FROM i"
        error = check_select_shape(sql, "POSTGRESQL")
        assert error is not None
        assert "data-modifying" in error

    def test_data_modifying_cte_update_rejected(self) -> None:
        sql = "WITH u AS (UPDATE orders SET total = 0 RETURNING *) SELECT * FROM u"
        error = check_select_shape(sql, "POSTGRESQL")
        assert error is not None
        assert "data-modifying" in error

    def test_select_into_rejected(self) -> None:
        error = check_select_shape("SELECT * INTO backup_orders FROM orders", "POSTGRESQL")
        assert error is not None

    def test_read_only_cte_and_subquery_still_pass(self) -> None:
        # Deep scan must not flag legitimate nested SELECTs
        sql = (
            "WITH recent AS (SELECT * FROM orders WHERE created > '2026-01-01') "
            "SELECT COUNT(*) FROM recent WHERE id IN (SELECT order_id FROM refunds)"
        )
        assert check_select_shape(sql, "POSTGRESQL") is None


# ── Check 2: Table References ───────────────────────────────────────────


class TestCheck2TableReferences:
    """Check 2: All table references exist in OMS for the metric's dataSourceId."""

    def test_existing_table_passes(self, valid_metric: dict, lookup: MockDataSourceLookup) -> None:
        result = validate_metric(valid_metric, data_sources_lookup=lookup)
        table_warnings = [w for w in result.warnings if w["check"] == "table_reference"]
        assert all(w["details"]["table"] != "orders" for w in table_warnings if not w.get("passed", True))

    def test_missing_table_produces_warning(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT * FROM nonexistent_table"}]},
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        assert result.valid  # Warnings don't block
        table_warnings = [w for w in result.warnings if w["check"] == "table_reference"]
        assert len(table_warnings) >= 1
        assert "nonexistent_table" in table_warnings[0]["message"]

    def test_source_table_validated_even_if_not_in_sql(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT SUM(amount) FROM t"}]},
            "dataSourceId": "ds-abc123",
            "sourceTable": "missing_table",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        table_warnings = [w for w in result.warnings if w["check"] == "table_reference"]
        assert any("missing_table" in w["message"] for w in table_warnings)

    def test_no_lookup_skips_table_check(self, valid_metric: dict) -> None:
        result = validate_metric(valid_metric, data_sources_lookup=None)
        table_warnings = [w for w in result.warnings if w["check"] == "table_reference"]
        assert len(table_warnings) == 0


# ── Check 3: Column References ──────────────────────────────────────────


class TestCheck3ColumnReferences:
    """Check 3: All column references exist and match expected types."""

    def test_valid_columns_no_warning(self, valid_metric: dict, lookup: MockDataSourceLookup) -> None:
        result = validate_metric(valid_metric, data_sources_lookup=lookup)
        col_warnings = [w for w in result.warnings if w["check"] == "column_reference"]
        assert len(col_warnings) == 0

    def test_missing_column_produces_warning(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT SUM(nonexistent_col) FROM orders"}]},
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        assert result.valid  # Soft warning
        col_warnings = [w for w in result.warnings if w["check"] == "column_reference"]
        assert len(col_warnings) >= 1
        assert "nonexistent_col" in col_warnings[0]["message"]

    def test_column_check_case_insensitive(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT SUM(TOTAL_AMOUNT) FROM orders"}]},
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        col_warnings = [w for w in result.warnings if w["check"] == "column_reference"]
        assert len(col_warnings) == 0

    def test_no_column_metadata_skips_check(self) -> None:
        lookup = MockDataSourceLookup(
            sources={"ds-abc123"},
            tables={"ds-abc123": {"orders"}},
            columns={},  # No column metadata available
        )
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT SUM(anything) FROM orders"}]},
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        col_warnings = [w for w in result.warnings if w["check"] == "column_reference"]
        assert len(col_warnings) == 0


# ── Check 4: Dimension Columns ──────────────────────────────────────────


class TestCheck4DimensionColumns:
    """Check 4: Dimension columns (GROUP BY) exist in referenced tables."""

    def test_valid_dimension_passes(self, valid_metric: dict, lookup: MockDataSourceLookup) -> None:
        result = validate_metric(valid_metric, data_sources_lookup=lookup)
        dim_warnings = [w for w in result.warnings if w["check"] == "dimension_column"]
        assert len(dim_warnings) == 0

    def test_missing_dimension_column_produces_warning(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {
                "dialects": [
                    {
                        "dialect": "postgresql",
                        "expression": "SELECT bad_dim, SUM(total_amount) FROM orders GROUP BY bad_dim",
                    }
                ]
            },
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        assert result.valid
        dim_warnings = [w for w in result.warnings if w["check"] == "dimension_column"]
        assert len(dim_warnings) >= 1
        assert "bad_dim" in dim_warnings[0]["message"]

    def test_fragment_skips_dimension_check(self, fragment_metric: dict, lookup: MockDataSourceLookup) -> None:
        """Fragments don't have GROUP BY — dimension check should not fire."""
        result = validate_metric(fragment_metric, data_sources_lookup=lookup)
        dim_warnings = [w for w in result.warnings if w["check"] == "dimension_column"]
        assert len(dim_warnings) == 0


# ── Check 5: Filter Type Compatibility ──────────────────────────────────


class TestCheck5FilterCompatibility:
    """Check 5: Filter columns exist and type matches operator."""

    def test_compatible_filter_no_warning(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {
                "dialects": [
                    {
                        "dialect": "postgresql",
                        "expression": "SELECT SUM(total_amount) FROM orders WHERE total_amount > 100",
                    }
                ]
            },
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        filter_warnings = [w for w in result.warnings if w["check"] == "filter_type_compatibility"]
        assert len(filter_warnings) == 0

    def test_like_on_varchar_no_warning(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {
                "dialects": [
                    {
                        "dialect": "postgresql",
                        "expression": "SELECT SUM(total_amount) FROM orders WHERE region LIKE '%US%'",
                    }
                ]
            },
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        filter_warnings = [w for w in result.warnings if w["check"] == "filter_type_compatibility"]
        assert len(filter_warnings) == 0

    def test_like_on_integer_produces_warning(self, lookup: MockDataSourceLookup) -> None:
        metric = {
            "expression": {
                "dialects": [
                    {
                        "dialect": "postgresql",
                        "expression": "SELECT SUM(total_amount) FROM orders WHERE customer_id LIKE '%123%'",
                    }
                ]
            },
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, data_sources_lookup=lookup)
        filter_warnings = [w for w in result.warnings if w["check"] == "filter_type_compatibility"]
        assert len(filter_warnings) >= 1
        assert "customer_id" in filter_warnings[0]["message"]

    def test_no_where_clause_skips_check(self, fragment_metric: dict, lookup: MockDataSourceLookup) -> None:
        result = validate_metric(fragment_metric, data_sources_lookup=lookup)
        filter_warnings = [w for w in result.warnings if w["check"] == "filter_type_compatibility"]
        assert len(filter_warnings) == 0


# ── Check 6: Ontology Class Linkage ────────────────────────────────────


class TestCheck6OntologyLinkage:
    """Check 6: :governedMetricFor references a valid ontology class."""

    def test_existing_class_passes(self, valid_metric: dict, ontology_lookup: MockOntologyLookup) -> None:
        result = validate_metric(valid_metric, ontology_lookup=ontology_lookup, namespace="sales")
        onto_warnings = [w for w in result.warnings if w["check"] == "ontology_linkage"]
        assert len(onto_warnings) == 0

    def test_missing_class_produces_warning(self, ontology_lookup: MockOntologyLookup) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT SUM(amount) FROM t"}]},
            "dataSourceId": "ds-1",
            "sourceTable": "t",
            "ontologyConcepts": ["ind:NonExistentClass"],
        }
        result = validate_metric(metric, ontology_lookup=ontology_lookup, namespace="sales")
        assert result.valid  # Soft warning
        onto_warnings = [w for w in result.warnings if w["check"] == "ontology_linkage"]
        assert len(onto_warnings) == 1
        assert "NonExistentClass" in onto_warnings[0]["message"]

    def test_multiple_concepts_validated(self, ontology_lookup: MockOntologyLookup) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT SUM(amount) FROM t"}]},
            "dataSourceId": "ds-1",
            "sourceTable": "t",
            "ontologyConcepts": ["ind:Order", "ind:Missing", "ind:Customer"],
        }
        result = validate_metric(metric, ontology_lookup=ontology_lookup, namespace="sales")
        onto_warnings = [w for w in result.warnings if w["check"] == "ontology_linkage"]
        assert len(onto_warnings) == 1  # Only "ind:Missing" fails
        assert "Missing" in onto_warnings[0]["message"]

    def test_no_ontology_lookup_skips_check(self, valid_metric: dict) -> None:
        result = validate_metric(valid_metric, ontology_lookup=None)
        onto_warnings = [w for w in result.warnings if w["check"] == "ontology_linkage"]
        assert len(onto_warnings) == 0

    def test_empty_concepts_skips_check(self, ontology_lookup: MockOntologyLookup) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT SUM(amount) FROM t"}]},
            "dataSourceId": "ds-1",
            "sourceTable": "t",
            "ontologyConcepts": [],
        }
        result = validate_metric(metric, ontology_lookup=ontology_lookup, namespace="sales")
        onto_warnings = [w for w in result.warnings if w["check"] == "ontology_linkage"]
        assert len(onto_warnings) == 0


# ── Combined / Integration Tests ───────────────────────────────────────


class TestCombinedValidation:
    """Tests that verify multiple checks running together."""

    def test_all_checks_pass_for_valid_metric(
        self,
        valid_metric: dict,
        lookup: MockDataSourceLookup,
        ontology_lookup: MockOntologyLookup,
    ) -> None:
        result = validate_metric(
            valid_metric,
            data_sources_lookup=lookup,
            ontology_lookup=ontology_lookup,
            namespace="sales",
        )
        assert result.valid
        assert len(result.errors) == 0
        # May have some warnings for table references in SQL
        # but core columns should pass

    def test_syntax_error_blocks_even_with_other_warnings(
        self, lookup: MockDataSourceLookup, ontology_lookup: MockOntologyLookup
    ) -> None:
        metric = {
            "expression": {"dialects": [{"dialect": "trino", "expression": "SELECT FROM WHERE"}]},
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": ["ind:Missing"],
        }
        result = validate_metric(
            metric,
            data_sources_lookup=lookup,
            ontology_lookup=ontology_lookup,
            namespace="sales",
        )
        assert not result.valid  # Blocked by Check 1
        assert len(result.errors) >= 1
        assert result.errors[0]["check"] == "sql_syntax"

    def test_multiple_warning_types_returned(
        self, lookup: MockDataSourceLookup, ontology_lookup: MockOntologyLookup
    ) -> None:
        metric = {
            "expression": {
                "dialects": [
                    {
                        "dialect": "postgresql",
                        "expression": "SELECT bad_col FROM missing_table WHERE customer_id LIKE '%x%' GROUP BY bad_dim",
                    }
                ]
            },
            "dataSourceId": "ds-abc123",
            "sourceTable": "orders",
            "ontologyConcepts": ["ind:NonExistent"],
        }
        result = validate_metric(
            metric,
            data_sources_lookup=lookup,
            ontology_lookup=ontology_lookup,
            namespace="sales",
        )
        assert result.valid  # All are warnings, not errors
        # Should have warnings from multiple checks
        check_types = {w["check"] for w in result.warnings}
        assert len(check_types) >= 2  # At least table + ontology or column + ontology

    def test_validation_without_any_lookups(self, valid_metric: dict) -> None:
        """Validation with no lookups only runs Check 1 (syntax)."""
        result = validate_metric(valid_metric)
        assert result.valid
        assert len(result.errors) == 0
        assert len(result.warnings) == 0


# ── Concrete lookup resilience ──────────────────────────────────────────


@pytest.mark.skip(reason="DynamoDBDataSourceLookup deprecated — replaced by SmusCatalogDataSourceLookup")
class TestDynamoDBDataSourceLookupResilience:
    """DynamoDB errors must degrade gracefully, never crash validation."""

    def _lookup(self) -> DynamoDBDataSourceLookup:
        lookup = DynamoDBDataSourceLookup(table_name="t", region="us-east-1")
        lookup._table = MagicMock()
        return lookup

    def test_data_source_exists_returns_false_on_dynamodb_error(self) -> None:
        lookup = self._lookup()
        lookup._table.get_item.side_effect = Exception("ThrottlingException")
        assert lookup.data_source_exists("ds-1") is False

    def test_data_source_exists_true_when_item_present(self) -> None:
        lookup = self._lookup()
        lookup._table.get_item.return_value = {"Item": {"PK": "DS#ds-1"}}
        assert lookup.data_source_exists("ds-1") is True

    def test_get_table_columns_returns_none_on_dynamodb_error(self) -> None:
        lookup = self._lookup()
        lookup._table.get_item.side_effect = Exception("AccessDeniedException")
        assert lookup.get_table_columns("ds-1", "orders") is None

    def test_get_table_columns_caches_none_result(self) -> None:
        lookup = self._lookup()
        lookup._table.get_item.side_effect = Exception("boom")
        assert lookup.get_table_columns("ds-1", "orders") is None
        # Second call must hit the cache, not DynamoDB again.
        lookup._table.get_item.reset_mock()
        assert lookup.get_table_columns("ds-1", "orders") is None
        lookup._table.get_item.assert_not_called()


class TestNeptuneOntologyLookupUriValidation:
    """class_exists must reject unsafe/malformed concept URIs before querying."""

    def _lookup(self) -> NeptuneOntologyLookup:
        lookup = NeptuneOntologyLookup()
        lookup._sparql_query = MagicMock(return_value={"boolean": True})
        return lookup

    def test_valid_curie_runs_query(self) -> None:
        lookup = self._lookup()
        assert lookup.class_exists("ind:Order", "sales") is True
        lookup._sparql_query.assert_called_once()

    def test_valid_urn_iri_runs_query(self) -> None:
        lookup = self._lookup()
        assert lookup.class_exists(f"urn:{URN_PREFIX}:sales:Order", "sales") is True
        lookup._sparql_query.assert_called_once()

    @pytest.mark.parametrize(
        "bad_uri",
        [
            "ind:Order} . } #",  # SPARQL break-out attempt
            "ind:Order ?x",  # whitespace injection
            "no-colon-here",  # not a CURIE/IRI
            "",  # empty
            "ind:Or<der>",  # angle brackets
            'ind:"Order"',  # quotes
        ],
    )
    def test_unsafe_uri_rejected_without_query(self, bad_uri: str) -> None:
        lookup = self._lookup()
        assert lookup.class_exists(bad_uri, "sales") is False
        lookup._sparql_query.assert_not_called()

    def test_query_error_fails_open_to_false(self) -> None:
        lookup = self._lookup()
        lookup._sparql_query.side_effect = Exception("neptune down")
        assert lookup.class_exists("ind:Order", "sales") is False
