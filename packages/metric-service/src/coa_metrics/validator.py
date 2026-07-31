# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Metric validation module.

Validates metric definitions against data source metadata and SQL syntax.

Checks (per Metric Onboarding Service LLD §5.1):
  1. SQL parses without syntax errors in declared dialect (sqlglot) → ERROR (blocks)
  2. All table references exist in OMS for the metric's dataSourceId → WARNING
  3. All column references exist and match expected types → WARNING
  4. Dimension columns exist in referenced tables → WARNING
  5. Filter columns exist and type matches operator → WARNING
  6. :governedMetricFor references a valid ontology class → WARNING

Philosophy: "Author early, validate continuously"
- Only Check 1 blocks metric creation (hard error)
- Checks 2-6 produce soft warnings — metric is still published
- Re-scan impact detection triggers re-validation when schema changes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── Result types ────────────────────────────────────────────────────────


class Severity(Enum):
    """Validation check severity."""

    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationCheck:
    """A single validation check result."""

    check: str
    severity: Severity
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Aggregate result of metric validation."""

    valid: bool
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]

    @classmethod
    def from_checks(cls, checks: list[ValidationCheck]) -> ValidationResult:
        """Build a ValidationResult from a list of individual check results."""
        errors = []
        warnings = []
        for c in checks:
            if c.passed:
                continue
            entry = {
                "check": c.check,
                "severity": c.severity.value,
                "message": c.message,
                "details": c.details,
            }
            if c.severity == Severity.ERROR:
                errors.append(entry)
            else:
                warnings.append(entry)
        return cls(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )


# ── Data source lookup interface ────────────────────────────────────────
# Base classes and implementations live in lookups.py (per review — keeps
# validator.py focused on check orchestration).

from coa_metrics.lookups import (  # noqa: E402, F401
    ColumnMetadata,
    DataSourceLookup,
    NeptuneOntologyLookup,
    OntologyLookup,
    SmusCatalogDataSourceLookup,
)

# Backward compat alias — new code should use SmusCatalogDataSourceLookup.
DynamoDBDataSourceLookup = None  # type: ignore[assignment]


# ── Main validation function ────────────────────────────────────────────

_DIALECT_MAP: dict[str, str] = {
    "trino": "trino",
    "postgresql": "postgres",
    "redshift": "redshift",
    "mysql": "mysql",
    "snowflake": "snowflake",
    "databricks": "databricks",
}


def _resolve_dialect(dialect: str) -> str | None:
    """Resolve a dialect string to a sqlglot dialect name (case-insensitive)."""
    return _DIALECT_MAP.get(dialect.lower())


def check_select_shape(sql: str, dialect: str = "") -> str | None:
    """Check that a metric expression is a full SELECT statement.

    Mirrors the serve-time SQL firewall's statement-shape rule
    (``packages/context-manager/.../tier2/sql_firewall.py`` —
    ``_SAFE_STATEMENT_TYPES``): only a top-level SELECT or set operation
    (UNION/INTERSECT/EXCEPT) is executable at Tier 1. Aggregate fragments
    like ``COUNT(*)`` or ``SUM(orders.total)`` parse fine but are rejected
    by the firewall at query time, so they must be rejected at onboarding —
    keep this in sync with the firewall so ``validate`` predicts serve-time
    acceptance.

    Also mirrors the firewall's deep scan (``_DATA_MODIFYING_NODES``): a
    data-modifying node nested anywhere in the AST — e.g.
    ``WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d`` — passes
    the top-level shape check but is rejected by the firewall, so it must be
    rejected here too for early feedback.

    Args:
        sql: The metric SQL expression.
        dialect: The metric dialect (e.g. POSTGRESQL); used for parsing.

    Returns:
        None if the expression is a full SELECT statement, otherwise a
        human-actionable error message.
    """
    import sqlglot

    safe_statement_types: tuple[type[sqlglot.exp.Expression], ...] = (
        sqlglot.exp.Select,
        sqlglot.exp.Union,
        sqlglot.exp.Intersect,
        sqlglot.exp.Except,
    )

    try:
        parsed = sqlglot.parse_one(sql, read=_resolve_dialect(dialect))
    except sqlglot.errors.ParseError as exc:
        return f"SQL expression could not be parsed ({dialect}): {exc}"

    if not isinstance(parsed, safe_statement_types):
        return (
            f"Expression must be a full SELECT statement — got a "
            f"{type(parsed).__name__} fragment. The serve-time SQL firewall only "
            f"executes SELECT statements; wrap the fragment, e.g. "
            f"'SELECT {sql.strip()} FROM <source_table>'."
        )

    # Deep scan: data-modifying nodes must not appear anywhere in the AST,
    # even nested in CTEs/subqueries of an otherwise-safe SELECT. Keep in
    # sync with sql_firewall.py's _DATA_MODIFYING_NODES.
    data_modifying_nodes: tuple[type[sqlglot.exp.Expression], ...] = (
        sqlglot.exp.Insert,
        sqlglot.exp.Update,
        sqlglot.exp.Delete,
        sqlglot.exp.Merge,
        sqlglot.exp.Into,
        sqlglot.exp.Create,
        sqlglot.exp.Drop,
        sqlglot.exp.Alter,
    )
    for node in parsed.walk():
        if isinstance(node, data_modifying_nodes):
            return (
                f"Expression contains a data-modifying operation "
                f"({type(node).__name__}) nested inside the statement — the "
                f"serve-time SQL firewall rejects these. Remove the "
                f"data-modifying clause; metric expressions must be read-only."
            )
    return None


def validate_metric(
    metric_body: dict[str, Any],
    data_sources_lookup: DataSourceLookup | None = None,
    ontology_lookup: OntologyLookup | None = None,
    namespace: str = "",
) -> ValidationResult:
    """Validate a metric definition against OMS metadata and ontology.

    Args:
        metric_body: The metric definition (API format or internal dict).
        data_sources_lookup: Lookup for data source/table/column validation (Checks 2-5).
        ontology_lookup: Lookup for ontology class validation (Check 6).
        namespace: The namespace context for ontology lookups.

    Returns:
        ValidationResult with errors (block creation) and warnings (non-blocking).
    """
    import sqlglot
    from sqlglot.errors import ParseError

    checks: list[ValidationCheck] = []

    data_source_id = metric_body.get("dataSourceId", "")
    source_table = metric_body.get("sourceTable", "")
    expression = metric_body.get("expression", {})
    dialects = expression.get("dialects", [])
    ontology_concepts = metric_body.get("ontologyConcepts", [])

    # ── Parse SQL once — reuse ASTs across all checks ───────────────────
    # Each entry: (dialect_name, list of parsed statements)
    parsed_dialects: list[tuple[str, list[Any]]] = []

    for i, dialect_entry in enumerate(dialects):
        dialect = dialect_entry.get("dialect", "")
        sql_expr = dialect_entry.get("expression", "")
        if not sql_expr:
            continue

        sqlglot_dialect = _resolve_dialect(dialect)
        try:
            stmts = sqlglot.parse(sql_expr, dialect=sqlglot_dialect)
            if not stmts or all(s is None for s in stmts):
                checks.append(
                    ValidationCheck(
                        check="sql_syntax",
                        severity=Severity.ERROR,
                        passed=False,
                        message=f"SQL expression is empty or unparseable ({dialect})",
                        details={"dialect": dialect, "index": i},
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        check="sql_syntax",
                        severity=Severity.ERROR,
                        passed=True,
                        message=f"SQL syntax valid ({dialect})",
                        details={"dialect": dialect, "index": i},
                    )
                )
                parsed_dialects.append((dialect, [s for s in stmts if s is not None]))

                # ── Check 1b: statement shape (serve-firewall parity, #617) ─
                # A syntactically-valid fragment (e.g. COUNT(*)) is rejected by
                # the serve-time SQL firewall — flag it here so validation
                # predicts serve-time acceptance.
                shape_error = check_select_shape(sql_expr, dialect)
                checks.append(
                    ValidationCheck(
                        check="sql_shape",
                        severity=Severity.ERROR,
                        passed=shape_error is None,
                        message=shape_error or f"Expression is a full SELECT statement ({dialect})",
                        details={"dialect": dialect, "index": i},
                    )
                )
        except ParseError as exc:
            checks.append(
                ValidationCheck(
                    check="sql_syntax",
                    severity=Severity.ERROR,
                    passed=False,
                    message=f"SQL syntax error ({dialect}): {exc}",
                    details={"dialect": dialect, "index": i, "error": str(exc)},
                )
            )
        except Exception as exc:
            logger.warning("sqlglot_unexpected_error", error=str(exc), dialect=dialect)
            checks.append(
                ValidationCheck(
                    check="sql_syntax",
                    severity=Severity.ERROR,
                    passed=False,
                    message=f"Could not parse SQL expression ({dialect}): {exc}",
                    details={"dialect": dialect, "index": i, "error": str(exc)},
                )
            )

    # ── Checks 2-5: OMS metadata validation (WARNING) ───────────────────
    # Only run if we have a lookup AND at least one successfully parsed SQL.
    if data_sources_lookup and data_source_id and parsed_dialects:
        checks.extend(_check_table_references(parsed_dialects, data_source_id, source_table, data_sources_lookup))
        checks.extend(_check_column_references(parsed_dialects, data_source_id, source_table, data_sources_lookup))
        checks.extend(_check_dimension_columns(parsed_dialects, data_source_id, source_table, data_sources_lookup))
        checks.extend(_check_filter_compatibility(parsed_dialects, data_source_id, source_table, data_sources_lookup))

    # ── Check 6: Ontology class linkage (WARNING) ───────────────────────
    if ontology_lookup and ontology_concepts:
        checks.extend(_check_ontology_linkage(ontology_concepts, ontology_lookup, namespace))

    return ValidationResult.from_checks(checks)


# ── Check 2: Table References ───────────────────────────────────────────


def _check_table_references(
    parsed_dialects: list[tuple[str, list[Any]]],
    data_source_id: str,
    source_table: str,
    lookup: DataSourceLookup,
) -> list[ValidationCheck]:
    """Check 2: All table references in SQL exist in OMS for the metric's dataSourceId."""
    from sqlglot import exp

    checks: list[ValidationCheck] = []
    tables_checked: set[str] = set()

    for _dialect, stmts in parsed_dialects:
        for stmt in stmts:
            for table in stmt.find_all(exp.Table):
                table_name = table.name
                if not table_name or table_name.lower() in tables_checked:
                    continue
                tables_checked.add(table_name.lower())

                exists = lookup.table_exists(data_source_id, table_name)
                checks.append(
                    ValidationCheck(
                        check="table_reference",
                        severity=Severity.WARNING,
                        passed=exists,
                        message=(
                            f"Table '{table_name}' exists in data source"
                            if exists
                            else f"Table '{table_name}' not found in data source '{data_source_id}'"
                        ),
                        details={"table": table_name, "dataSourceId": data_source_id},
                    )
                )

    # Also verify the declared sourceTable exists
    if source_table and source_table.lower() not in tables_checked:
        exists = lookup.table_exists(data_source_id, source_table)
        checks.append(
            ValidationCheck(
                check="table_reference",
                severity=Severity.WARNING,
                passed=exists,
                message=(
                    f"Source table '{source_table}' exists in data source"
                    if exists
                    else f"Source table '{source_table}' not found in data source '{data_source_id}'"
                ),
                details={"table": source_table, "dataSourceId": data_source_id},
            )
        )

    return checks


# ── Check 3: Column References ──────────────────────────────────────────


def _check_column_references(
    parsed_dialects: list[tuple[str, list[Any]]],
    data_source_id: str,
    source_table: str,
    lookup: DataSourceLookup,
) -> list[ValidationCheck]:
    """Check 3: All column references in SQL exist in the source table metadata."""
    from sqlglot import exp

    checks: list[ValidationCheck] = []
    columns_checked: set[str] = set()

    table_columns = lookup.get_table_columns(data_source_id, source_table)
    if table_columns is None:
        return checks

    known_columns = {col.name.lower() for col in table_columns}

    for _dialect, stmts in parsed_dialects:
        for stmt in stmts:
            for col in stmt.find_all(exp.Column):
                col_name = col.name
                if not col_name or col_name.lower() in columns_checked:
                    continue
                columns_checked.add(col_name.lower())

                exists = col_name.lower() in known_columns
                if not exists:
                    checks.append(
                        ValidationCheck(
                            check="column_reference",
                            severity=Severity.WARNING,
                            passed=False,
                            message=f"Column '{col_name}' not found in table '{source_table}' metadata",
                            details={
                                "column": col_name,
                                "table": source_table,
                                "dataSourceId": data_source_id,
                            },
                        )
                    )

    return checks


# ── Check 4: Dimension Columns ──────────────────────────────────────────


def _check_dimension_columns(
    parsed_dialects: list[tuple[str, list[Any]]],
    data_source_id: str,
    source_table: str,
    lookup: DataSourceLookup,
) -> list[ValidationCheck]:
    """Check 4: Columns used in GROUP BY (dimensions) exist in the source table."""
    from sqlglot import exp

    checks: list[ValidationCheck] = []
    dimensions_checked: set[str] = set()

    table_columns = lookup.get_table_columns(data_source_id, source_table)
    if table_columns is None:
        return checks

    known_columns = {col.name.lower() for col in table_columns}

    for _dialect, stmts in parsed_dialects:
        for stmt in stmts:
            group_by = stmt.find(exp.Group)
            if group_by is None:
                continue
            for col in group_by.find_all(exp.Column):
                col_name = col.name
                if not col_name or col_name.lower() in dimensions_checked:
                    continue
                dimensions_checked.add(col_name.lower())

                exists = col_name.lower() in known_columns
                if not exists:
                    checks.append(
                        ValidationCheck(
                            check="dimension_column",
                            severity=Severity.WARNING,
                            passed=False,
                            message=f"Dimension column '{col_name}' not found in table '{source_table}'",
                            details={
                                "column": col_name,
                                "table": source_table,
                                "usage": "GROUP BY (dimension)",
                            },
                        )
                    )

    return checks


# ── Check 5: Filter Type Compatibility ──────────────────────────────────

# Operators that require numeric/date types
_NUMERIC_OPS = {"GT", "LT", "GTE", "LTE", "BETWEEN"}
# Operators that require string types
_STRING_OPS = {"LIKE", "ILIKE"}
# Numeric-compatible types
_NUMERIC_TYPES = {"integer", "int", "bigint", "smallint", "decimal", "numeric", "float", "double", "real", "number"}
# Date-compatible types
_DATE_TYPES = {"date", "timestamp", "timestamptz", "datetime", "timestamp_ntz", "timestamp_ltz"}
# String types
_STRING_TYPES = {"varchar", "text", "char", "string", "character varying", "nvarchar"}


def _check_filter_compatibility(
    parsed_dialects: list[tuple[str, list[Any]]],
    data_source_id: str,
    source_table: str,
    lookup: DataSourceLookup,
) -> list[ValidationCheck]:
    """Check 5: Columns in WHERE clauses have type-compatible operators."""
    from sqlglot import exp

    checks: list[ValidationCheck] = []
    filters_checked: set[str] = set()

    table_columns = lookup.get_table_columns(data_source_id, source_table)
    if table_columns is None:
        return checks

    for _dialect, stmts in parsed_dialects:
        for stmt in stmts:
            where = stmt.find(exp.Where)
            if where is None:
                continue

            for comparison in where.find_all(exp.GT, exp.LT, exp.GTE, exp.LTE, exp.Like, exp.ILike, exp.Between):
                col_node = comparison.find(exp.Column)
                if col_node is None:
                    continue

                col_name = col_node.name
                if not col_name:
                    continue

                check_key = f"{col_name}:{type(comparison).__name__}"
                if check_key in filters_checked:
                    continue
                filters_checked.add(check_key)

                col_type = lookup.get_column_type(data_source_id, source_table, col_name)
                if col_type is None:
                    continue

                op_name = type(comparison).__name__.upper()
                compatible = _is_type_compatible(col_type, op_name)

                if not compatible:
                    checks.append(
                        ValidationCheck(
                            check="filter_type_compatibility",
                            severity=Severity.WARNING,
                            passed=False,
                            message=(
                                f"Column '{col_name}' (type: {col_type}) may be incompatible with operator '{op_name}'"
                            ),
                            details={
                                "column": col_name,
                                "columnType": col_type,
                                "operator": op_name,
                                "table": source_table,
                            },
                        )
                    )

    return checks


def _is_type_compatible(col_type: str, operator: str) -> bool:
    """Check if a column type is compatible with a comparison operator."""
    col_type_lower = col_type.lower()

    # LIKE/ILIKE only makes sense on string types
    if operator in ("LIKE", "ILIKE"):
        return col_type_lower in _STRING_TYPES or col_type_lower in _DATE_TYPES

    # Numeric comparisons (GT, LT, GTE, LTE, BETWEEN) work on numeric and date types
    if operator in ("GT", "LT", "GTE", "LTE", "BETWEEN"):
        return col_type_lower in _NUMERIC_TYPES or col_type_lower in _DATE_TYPES

    return True  # Unknown operator — don't flag


# ── Check 6: Ontology Class Linkage ────────────────────────────────────


def _check_ontology_linkage(
    ontology_concepts: list[str],
    ontology_lookup: OntologyLookup,
    namespace: str,
) -> list[ValidationCheck]:
    """Check 6: :governedMetricFor references valid ontology classes in published graph."""
    checks: list[ValidationCheck] = []

    for class_ref in ontology_concepts:
        if not class_ref:
            continue
        exists = ontology_lookup.class_exists(class_ref, namespace)
        checks.append(
            ValidationCheck(
                check="ontology_linkage",
                severity=Severity.WARNING,
                passed=exists,
                message=(
                    f"Ontology class '{class_ref}' exists in published ontology"
                    if exists
                    else f"Ontology class '{class_ref}' not found in published ontology for namespace '{namespace}'"
                ),
                details={"classUri": class_ref, "namespace": namespace},
            )
        )

    return checks
