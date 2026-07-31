# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Loads JSON fixture files and provides lookup helpers."""

import json
from pathlib import Path

from app.schemas import Database, DatabaseSchema, Table

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_DATA_DIR = Path(__file__).parent.parent / "sample_data"


def _load(filename: str) -> list[dict]:
    with open(FIXTURES_DIR / filename) as f:
        return json.load(f)


def load_catalogs() -> list[dict]:
    """Load all catalog JSON files from sample_data/."""
    catalogs = []
    if SAMPLE_DATA_DIR.is_dir():
        for p in sorted(SAMPLE_DATA_DIR.glob("*.json")):
            with open(p) as f:
                catalogs.append(json.load(f))
    return catalogs


def load_databases() -> list[Database]:
    return [Database(**d) for d in _load("databases.json")]


def load_schemas() -> list[DatabaseSchema]:
    return [DatabaseSchema(**s) for s in _load("databaseSchemas.json")]


def load_tables() -> list[Table]:
    return [Table(**t) for t in _load("tables.json")]
