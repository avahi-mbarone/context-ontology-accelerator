"""Emit one Glue create-table input JSON per table, from schema.py.

Same shape as the repo-root products-table.json/inventory_snapshots-table.json,
but Parquet SerDe instead of CSV (see ../../DEMO-DATASET-PLAN.md §8.3). ``load.sh``
consumes these directly with ``aws glue create-table --table-input file://...``.

Run with ``python3 glue_tables.py`` (no external dependencies) after setting
SOURCES_BUCKET, or let load.sh do both steps together.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from schema import GLUE_DATABASE_NAME, S3_PREFIX, TABLES

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def table_input(table_name: str, bucket: str) -> dict:
    from schema import TABLES_BY_NAME

    table = TABLES_BY_NAME[table_name]
    return {
        "Name": table.name,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "parquet"},
        "StorageDescriptor": {
            "Columns": [{"Name": c.name, "Type": c.glue_type, "Comment": c.comment} for c in table.columns],
            "Location": f"s3://{bucket}/{S3_PREFIX}/{table.name}/",
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                "Parameters": {"serialization.format": "1"},
            },
        },
    }


def main() -> None:
    bucket = os.environ.get("SOURCES_BUCKET")
    if not bucket:
        sys.exit("error: set SOURCES_BUCKET to the coa-dev sources data bucket name (see HANDOFF.md)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        payload = table_input(table.name, bucket)
        dest = OUTPUT_DIR / table.name / f"{table.name}-table.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2) + "\n")
        print(dest)

    print(f"\nDatabase name for `aws glue create-database`: {GLUE_DATABASE_NAME}")


if __name__ == "__main__":
    main()
