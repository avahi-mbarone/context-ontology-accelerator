# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Guard every Glue table definition against the OpenCSVSerde + DATE trap.

OpenCSVSerde reads each field as a string and then coerces, and for DATE/TIMESTAMP
it expects a UNIX numeric value (days since epoch / millis) — never an ISO string.
Pairing it with a `date` column over ISO data produces a failure no scan can
catch, because it happens at QUERY time:

    Athena query FAILED: BAD_DATA: Error parsing column 'order_date' with value
    '2024-02-10' with error: 'java.lang.NumberFormatException: For input string:
    "2024-02-10"'

The source still onboards and reports healthy; only queries touching the column
break. Expensive to trace back from a Tier-2 test failure, so it is pinned here
statically — no AWS and no deployment needed.

Table definitions live in two places, and both are scanned: inline
`--table-input '{...}'` blobs in the integ seed scripts, and the versioned
`demo/<industry>/glue/*.table.json` files the demo seeder feeds through `jq`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Neither `tests/cdk/` nor `demo/` is published to the public mirror (see the
# allowlist in .npmignore), so both scan roots below are absent there. The globs
# would quietly yield nothing and `test_scan_found_the_known_definitions` would
# fail on the empty scan; skip the module instead — there is nothing to guard.
if not (_REPO_ROOT / "tests" / "cdk" / "scripts").exists():
    pytest.skip("tests/cdk/ is absent from this checkout (public mirror)", allow_module_level=True)

_OPEN_CSV_SERDE = "OpenCSVSerde"
# Types OpenCSVSerde cannot read from a text/ISO representation.
_TEXT_HOSTILE_TYPES = ("date", "timestamp")


def _inline_table_inputs(script: Path) -> list[tuple[str, dict]]:
    """Every `--table-input '{...}'` JSON blob in a seed script.

    The scripts interpolate shell into the JSON (e.g. the S3 location), so
    interpolations are replaced with a literal before parsing.
    """
    out: list[tuple[str, dict]] = []
    for raw in re.findall(r"--table-input\s+'(\{.*?\n\s*\})'", script.read_text(), re.DOTALL):
        cleaned = re.sub(r"'\"\$\{[^}]+\}\"'", "PLACEHOLDER", raw)
        try:
            out.append((script.name, json.loads(cleaned)))
        except json.JSONDecodeError as exc:  # pragma: no cover - fail loudly rather than skip
            raise AssertionError(f"{script.name}: unparseable --table-input blob: {exc}\n{cleaned[:400]}") from exc
    return out


def _all_table_definitions() -> list[tuple[str, dict]]:
    """(source label, Glue table-input dict) for every definition in the repo."""
    defs: list[tuple[str, dict]] = []
    for script in sorted((_REPO_ROOT / "tests" / "cdk" / "scripts").glob("*glue*.sh")):
        defs += _inline_table_inputs(script)
    for table_json in sorted(_REPO_ROOT.glob("demo/*/glue/*.table.json")):
        defs.append((str(table_json.relative_to(_REPO_ROOT)), json.loads(table_json.read_text())))
    return defs


_DEFINITIONS = _all_table_definitions()


def test_scan_found_the_known_definitions() -> None:
    """Guard the guard: an empty or shrunken scan must fail, not silently pass."""
    sources = {src for src, _ in _DEFINITIONS}
    assert "load-glue-s3-data.sh" in sources, f"integ Glue seed script not scanned; found {sources}"
    assert any(s.endswith(".table.json") for s in sources), f"no versioned demo table defs scanned; found {sources}"


@pytest.mark.parametrize(("source", "table"), _DEFINITIONS, ids=[f"{s}:{t.get('Name', '?')}" for s, t in _DEFINITIONS])
def test_no_date_columns_under_opencsv_serde(source: str, table: dict) -> None:
    """A date/timestamp column must never be declared with OpenCSVSerde."""
    sd = table.get("StorageDescriptor", {})
    if _OPEN_CSV_SERDE not in sd.get("SerdeInfo", {}).get("SerializationLibrary", ""):
        return

    offenders = [
        f"{col.get('Name')} ({col.get('Type')})"
        for col in sd.get("Columns", [])
        if col.get("Type", "").lower().startswith(_TEXT_HOSTILE_TYPES)
    ]
    assert not offenders, (
        f"{source}: table '{table.get('Name')}' uses OpenCSVSerde, which reads "
        f"date/timestamp values as UNIX numerics — these columns will fail at query "
        f"time with BAD_DATA / NumberFormatException on ISO values: {offenders}. "
        f"Use LazySimpleSerDe (parses ISO dates, but no quoted fields), or declare "
        f"the column as string."
    )
