#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate data-catalog JSON fixtures from pc-insurance-tables.yaml.

Reads the parser output and writes OpenMetadata-compatible fixture files.
No column names, types, or descriptions are invented — empty strings for
fields the DDL doesn't specify.

Outputs two things:
  1. Appends to ``tests/fixtures/data-catalog/app/fixtures/{databases,
     databaseSchemas,tables}.json`` so the 13 P&C tables are listed via
     ``GET /api/v1/tables``.
  2. Writes ``tests/fixtures/data-catalog/sample_data/pc_insurance.json``
     so the datasource ``ds-pc-insurance`` is discoverable via
     ``GET /api/v1/catalogs/``. Without this second output, the tables
     exist in the catalog but no datasource references them, and
     datasource-driven induction (via ``POST /induce/`` with
     ``datasource_ids``) can't reach them.

Idempotent: re-running replaces the pc entries rather than appending
duplicates.
"""

import json
from pathlib import Path

import yaml

YAML_PATH = Path(__file__).parent / "pc-insurance-tables.yaml"
FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "data-catalog" / "app" / "fixtures"
SAMPLE_DATA_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "data-catalog" / "sample_data"

DB_ID = "db-pc-001"
SCHEMA_ID = "schema-pc-001"
DB_FQN = "pc_postgres.pc_insurance"
SCHEMA_FQN = "pc_postgres.pc_insurance.claims"

NAMESPACE_ID = "ns-pc-insurance"
DATASOURCE_ID = "ds-pc-insurance"
DATABASE_NAME = "pc_insurance"
DATABASE_DESCRIPTION = (
    "P&C (Property & Casualty) Insurance database. Schema subset from the OMG P&C "
    'Data Model (dtc/13-04-15), as published in "Knowledge Graph and LLM Accuracy '
    'Benchmark Report" Appendix 9.1 (Sequeda et al., arXiv:2311.07509).'
)


def _build_columns(columns_yaml: list[dict]) -> list[dict]:
    """Copy column metadata verbatim from the parser output."""
    out = []
    for col in columns_yaml:
        c = {
            "name": col["name"],
            "dataType": col["dataType"],
            "ordinalPosition": col["ordinalPosition"],
        }
        for k in ("dataLength", "precision", "scale", "constraint"):
            if k in col:
                c[k] = col[k]
        out.append(c)
    return out


def _build_constraints(table_yaml: dict) -> list[dict]:
    """Build tableConstraints entries from parser output."""
    constraints = []
    if table_yaml.get("primaryKey"):
        constraints.append(
            {
                "constraintType": "PRIMARY_KEY",
                "columns": table_yaml["primaryKey"],
            }
        )
    for fk in table_yaml.get("foreignKeys", []):
        constraints.append(
            {
                "constraintType": "FOREIGN_KEY",
                "columns": fk["columns"],
                "referredColumns": [f"{SCHEMA_FQN}.{fk['referredTable']}.{rc}" for rc in fk["referredColumns"]],
            }
        )
    return constraints


def _build_table_entry(index: int, table_yaml: dict) -> dict:
    """One OpenMetadata-style Table row for tables.json."""
    table_id = f"pc-{index:03d}"
    return {
        "id": table_id,
        "name": table_yaml["name"],
        "fullyQualifiedName": f"{SCHEMA_FQN}.{table_yaml['name']}",
        "tableType": "Regular",
        "databaseSchema": {
            "id": SCHEMA_ID,
            "type": "databaseSchema",
            "name": "claims",
            "fullyQualifiedName": SCHEMA_FQN,
        },
        "columns": _build_columns(table_yaml["columns"]),
        "tableConstraints": _build_constraints(table_yaml),
        "tags": [],
    }


def _build_catalog_entry(tables_yaml: list[dict]) -> dict:
    """One catalog document for sample_data/pc_insurance.json.

    Shape matches sample_data/catalog1.json so the catalog service's
    load_catalogs() picks it up automatically at startup.
    """
    source_tables = []
    for t in tables_yaml:
        cols = t["columns"]
        pk_cols = t.get("primaryKey") or []
        fks = [
            {
                "column": fk["columns"][0] if fk["columns"] else "",
                "targetTable": fk["referredTable"],
                "targetColumn": fk["referredColumns"][0] if fk["referredColumns"] else "",
                "source": "DETERMINISTIC",
                "confidence": 1.0,
            }
            for fk in t.get("foreignKeys", [])
        ]
        source_tables.append(
            {
                "name": t["name"],
                "technicalMetadata": {
                    "columnCount": len(cols),
                    "format": "postgres",
                },
                "businessMetadata": {
                    "description": "",  # DDL has no descriptions — do not invent
                    "enrichmentSource": "DETERMINISTIC",
                    "reviewStatus": "APPROVED",
                },
                "primaryKey": ({"columns": pk_cols, "source": "DETERMINISTIC", "confidence": 1.0} if pk_cols else None),
                "foreignKeys": fks,
                "columns": [
                    {
                        "name": c["name"],
                        "dataType": c["dataType"],
                        "description": "",
                        "constraint": c.get("constraint"),
                    }
                    for c in cols
                ],
            }
        )

    return {
        "namespaceId": NAMESPACE_ID,
        "sources": [
            {
                "datasourceId": DATASOURCE_ID,
                "sourceType": "JDBC_DATABASE",
                "databases": [
                    {
                        "name": DATABASE_NAME,
                        "description": DATABASE_DESCRIPTION,
                        "tables": source_tables,
                    }
                ],
            }
        ],
    }


def generate():
    if not YAML_PATH.exists():
        raise SystemExit(f"Missing {YAML_PATH}. Run parse_ddl_to_config.py first.")

    with open(YAML_PATH) as f:
        data = yaml.safe_load(f)
    tables_yaml = data["tables"]

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    db_entry = {
        "id": DB_ID,
        "name": DATABASE_NAME,
        "displayName": "P&C Insurance Database (v2)",
        "fullyQualifiedName": DB_FQN,
        "description": "",
        "service": {
            "id": "svc-pc-001",
            "type": "databaseService",
            "name": "pc_postgres",
            "fullyQualifiedName": "pc_postgres",
            "serviceType": "Postgres",
        },
        "tags": [],
        "owners": [],
    }

    schema_entry = {
        "id": SCHEMA_ID,
        "name": "claims",
        "displayName": "Claims Schema",
        "fullyQualifiedName": SCHEMA_FQN,
        "description": "",
        "database": {
            "id": DB_ID,
            "type": "database",
            "name": DATABASE_NAME,
            "fullyQualifiedName": DB_FQN,
        },
    }

    table_entries = [_build_table_entry(i, t) for i, t in enumerate(tables_yaml, 1)]

    # ── Update databases.json (idempotent: replace PC entry if present) ──
    dbs_path = FIXTURES_DIR / "databases.json"
    dbs = json.loads(dbs_path.read_text()) if dbs_path.exists() else []
    dbs = [d for d in dbs if d.get("id") != DB_ID]
    dbs.append(db_entry)
    dbs_path.write_text(json.dumps(dbs, indent=2) + "\n")
    print(f"✓ databases.json: {DB_ID}")

    # ── Update databaseSchemas.json (idempotent) ──
    schemas_path = FIXTURES_DIR / "databaseSchemas.json"
    schemas = json.loads(schemas_path.read_text()) if schemas_path.exists() else []
    schemas = [s for s in schemas if s.get("id") != SCHEMA_ID]
    schemas.append(schema_entry)
    schemas_path.write_text(json.dumps(schemas, indent=2) + "\n")
    print(f"✓ databaseSchemas.json: {SCHEMA_ID}")

    # ── Update tables.json (idempotent: drop all pc-* first) ──
    tables_path = FIXTURES_DIR / "tables.json"
    tables = json.loads(tables_path.read_text()) if tables_path.exists() else []
    tables = [t for t in tables if not t.get("id", "").startswith("pc-")]
    tables.extend(table_entries)
    tables_path.write_text(json.dumps(tables, indent=2) + "\n")
    print(f"✓ tables.json: {len(table_entries)} pc tables (pc-001 .. pc-{len(table_entries):03d})")

    # ── Write sample_data/pc_insurance.json so datasource is discoverable ──
    catalog_path = SAMPLE_DATA_DIR / "pc_insurance.json"
    catalog_path.write_text(json.dumps(_build_catalog_entry(tables_yaml), indent=2) + "\n")
    print(f"✓ sample_data/pc_insurance.json: datasourceId={DATASOURCE_ID} ({len(table_entries)} tables)")

    # ── Verify ──
    pc = [t for t in tables if t["id"].startswith("pc-")]
    assert len(pc) == len(tables_yaml), f"Expected {len(tables_yaml)} pc tables, got {len(pc)}"
    for t in pc:
        if t["name"] == "Loss_Payment":
            assert len(t["columns"]) == 1, f"Loss_Payment has {len(t['columns'])} columns, expected 1"
            assert t["columns"][0]["name"] == "Claim_Amount_Identifier"
            print("✓ Loss_Payment verified: 1 column, name=Claim_Amount_Identifier")
    print(f"✓ All {len(pc)} pc tables present in fixtures")


if __name__ == "__main__":
    generate()
