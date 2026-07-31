#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Parse pc-insurance-ddl.sql into pc-insurance-tables.yaml using sqlglot.

All schema content flows from the DDL — no column names, types, or descriptions
are typed by hand or by an LLM.
"""

import re
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

DDL_PATH = Path(__file__).parent / "pc-insurance-ddl.sql"
OUT_PATH = Path(__file__).parent / "pc-insurance-tables.yaml"

# ── Type mapping: sqlglot DataType → data-catalog types ──────────────────────

TYPE_MAP = {
    "INT": "INT",
    "BIGINT": "BIGINT",
    "DATETIME": "DATETIME",
}


def _param_int(params, idx):
    """Extract integer value from a DataTypeParam at given index."""
    if idx >= len(params):
        return None
    p = params[idx]
    # DataTypeParam wraps a Literal
    lit = p.this if hasattr(p, "this") else p
    return int(str(lit))


def map_column_type(dtype: exp.DataType) -> dict:
    """Map a sqlglot DataType node to data-catalog column attributes."""
    type_name = dtype.this.name if hasattr(dtype.this, "name") else str(dtype.this)
    type_name = type_name.upper().replace("DATATYPE.", "")

    result = {}
    params = dtype.expressions

    if type_name in TYPE_MAP:
        result["dataType"] = TYPE_MAP[type_name]
    elif type_name == "VARCHAR":
        result["dataType"] = "VARCHAR"
        if params:
            result["dataLength"] = _param_int(params, 0)
    elif type_name == "CHAR":
        result["dataType"] = "CHAR"
        if params:
            result["dataLength"] = _param_int(params, 0)
    elif type_name == "DECIMAL":
        result["dataType"] = "DECIMAL"
        if len(params) >= 2:
            result["precision"] = _param_int(params, 0)
            result["scale"] = _param_int(params, 1)
    else:
        result["dataType"] = type_name

    return result


# ── Preprocess DDL ───────────────────────────────────────────────────────────


def preprocess_ddl(raw: str) -> str:
    """Preprocess DDL for sqlglot compatibility:
    1. Remove ASC/DESC from PRIMARY KEY column lists
    2. Add semicolons between CREATE TABLE statements
    """

    # Strip ASC/DESC from PK definitions
    def strip_pk_ordering(m):
        inner = m.group(1)
        inner = re.sub(r"\b(ASC|DESC)\b", "", inner)
        return f"PRIMARY KEY ({inner})"

    cleaned = re.sub(r"PRIMARY\s+KEY\s*\(([^)]+)\)", strip_pk_ordering, raw)

    # Add semicolons: insert ';' before each CREATE TABLE except the first
    cleaned = re.sub(r"(\))\s*\n\s*(CREATE\s+TABLE)", r"\1;\n\2", cleaned)

    return cleaned


# ── Parse ────────────────────────────────────────────────────────────────────


def parse_ddl() -> list[dict]:
    raw = DDL_PATH.read_text()
    cleaned = preprocess_ddl(raw)
    stmts = sqlglot.parse(cleaned)

    tables = []
    for stmt in stmts:
        if not isinstance(stmt, exp.Create):
            continue

        table_expr = stmt.find(exp.Table)
        table_name = table_expr.name

        columns = []
        pk_cols = []
        fks = []
        ordinal = 0

        schema = stmt.find(exp.Schema)
        if not schema:
            continue

        for node in schema.expressions:
            if isinstance(node, exp.ColumnDef):
                ordinal += 1
                col_name = node.name
                dtype = node.find(exp.DataType)
                col_info = {"name": col_name, "ordinalPosition": ordinal}
                col_info.update(map_column_type(dtype))

                # Check NOT NULL constraint (allow_null=True means explicit NULL, not NOT NULL)
                for constraint in node.find_all(exp.ColumnConstraint):
                    kind = constraint.find(exp.NotNullColumnConstraint)
                    if kind and not kind.args.get("allow_null"):
                        col_info["constraint"] = "NOT_NULL"

                columns.append(col_info)

            elif isinstance(node, exp.PrimaryKey):
                # PK columns may be Column or Identifier nodes
                for e in node.expressions:
                    if isinstance(e, (exp.Column, exp.Identifier)):
                        pk_cols.append(e.name)
                    elif hasattr(e, "find"):
                        col = e.find(exp.Column) or e.find(exp.Identifier)
                        if col:
                            pk_cols.append(col.name)

            elif isinstance(node, exp.ForeignKey):
                fk_columns = [e.name for e in node.expressions if isinstance(e, (exp.Column, exp.Identifier))]
                ref = node.find(exp.Reference)
                if ref:
                    ref_schema = ref.find(exp.Schema)
                    ref_table = ref_schema.find(exp.Table).name if ref_schema else None
                    ref_cols = (
                        [e.name for e in ref_schema.expressions if isinstance(e, (exp.Column, exp.Identifier))]
                        if ref_schema
                        else []
                    )
                    fks.append(
                        {
                            "columns": fk_columns,
                            "referredTable": ref_table,
                            "referredColumns": ref_cols,
                        }
                    )

        table_dict = {
            "name": table_name,
            "columns": columns,
            "primaryKey": pk_cols,
        }
        if fks:
            table_dict["foreignKeys"] = fks

        tables.append(table_dict)

    return tables


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tables = parse_ddl()

    # ── Assertions ───────────────────────────────────────────────────────
    assert len(tables) == 13, f"Expected 13 tables, got {len(tables)}"
    total_cols = sum(len(t["columns"]) for t in tables)
    assert total_cols == 65, f"Expected 65 columns, got {total_cols}"

    expected_single_col = {"Loss_Payment", "Loss_Reserve", "Expense_Payment", "Expense_Reserve", "Premium"}
    for t in tables:
        if t["name"] in expected_single_col:
            assert len(t["columns"]) == 1, f"{t['name']} must have 1 column, got {len(t['columns'])}"
            assert t["columns"][0]["name"] in ("Claim_Amount_Identifier", "Policy_Amount_Identifier"), (
                f"{t['name']} column has wrong name: {t['columns'][0]['name']}"
            )

    expected_composite_pk = {
        "Claim_Coverage": 3,
        "Policy_Coverage_Detail": 2,
        "Agreement_Party_Role": 4,
    }
    for t in tables:
        if t["name"] in expected_composite_pk:
            assert len(t["primaryKey"]) == expected_composite_pk[t["name"]], (
                f"{t['name']} composite PK wrong: {t['primaryKey']}"
            )

    print(f"✓ DDL parsed: {len(tables)} tables, {total_cols} columns")

    # ── Write YAML ───────────────────────────────────────────────────────
    with open(OUT_PATH, "w") as f:
        yaml.dump({"tables": tables}, f, default_flow_style=False, sort_keys=False)

    print(f"✓ Written to {OUT_PATH}")
