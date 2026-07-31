# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for AthenaSampler — Glue-catalog enum-value sampling via Athena.

The guard logic mirrors the JDBC dialect: bounded distinct count AND average
per-value repetition (excludes unique identifiers). Athena I/O is mocked at the
``_run`` boundary so no live client is needed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from coa_sources.database.connectors.athena_sampler import AthenaSampler

pytestmark = pytest.mark.unit


def _sampler() -> AthenaSampler:
    # Explicit output_location makes .enabled True without env.
    return AthenaSampler(region="us-east-1", workgroup="wg-test", output_location="s3://spill/enum/")


def _fake_run(*, total: int, distinct: int, values: list[str]):
    """Return a _run side_effect that answers the count gate then DISTINCT."""

    def run(sql: str):
        if "count(" in sql.lower():
            return [[str(total), str(distinct)]]
        if "select distinct" in sql.lower():
            return [[v] for v in values]
        return []

    return run


class TestAthenaSamplerGuard:
    def test_low_cardinality_repeated_column_returns_values(self):
        s = _sampler()
        with patch.object(
            s, "_run", side_effect=_fake_run(total=133, distinct=2, values=["RETURNED", "RETURN_REQUESTED"])
        ):
            out = s.sample_columns("coa_demo", "orders", [("return_state", "varchar")])
        assert out == {"return_state": ["RETURNED", "RETURN_REQUESTED"]}

    def test_unique_identifier_skipped(self):
        # distinct == total → repetition gate rejects even a small table
        s = _sampler()
        with patch.object(
            s, "_run", side_effect=_fake_run(total=37, distinct=37, values=[f"O-{i}" for i in range(37)])
        ):
            out = s.sample_columns("db", "orders", [("order_id", "varchar")])
        assert "order_id" not in out

    def test_high_cardinality_skipped(self):
        s = _sampler()
        with patch.object(s, "_run", side_effect=_fake_run(total=9000, distinct=5000, values=[])):
            out = s.sample_columns("db", "t", [("c", "varchar")])
        assert "c" not in out

    def test_empty_column_skipped(self):
        s = _sampler()
        with patch.object(s, "_run", side_effect=_fake_run(total=0, distinct=0, values=[])):
            out = s.sample_columns("db", "t", [("c", "string")])
        assert "c" not in out

    def test_low_repetition_freetext_skipped(self):
        # near-unique free-text (30 distinct / 60 rows, ratio 2.0) → fails
        # MIN_REPETITION_FACTOR=3 (60 < 90) despite passing the distinct<=50 cap
        s = _sampler()
        with patch.object(
            s, "_run", side_effect=_fake_run(total=60, distinct=30, values=[f"name{i}" for i in range(30)])
        ):
            out = s.sample_columns("db", "customers", [("first_name", "varchar")])
        assert "first_name" not in out

    def test_non_string_columns_filtered_before_query(self):
        s = _sampler()
        # int/date/decimal columns are not sampleable → no _run call at all
        with patch.object(s, "_run", side_effect=AssertionError("should not query non-string columns")):
            out = s.sample_columns("db", "t", [("total_usd", "decimal"), ("order_date", "date"), ("qty", "int")])
        assert out == {}

    def test_long_freetext_values_dropped_by_shape_filter(self):
        # 500-char values are free text, not enum labels → shape filter drops.
        s = _sampler()
        with patch.object(s, "_run", side_effect=_fake_run(total=10, distinct=1, values=["x" * 500])):
            out = s.sample_columns("db", "t", [("c", "varchar")])
        assert "c" not in out

    def test_values_length_capped(self):
        # Per-value 100-char cap still applies to values that pass the shape
        # filter: many short values keep the SET average low (column kept), and
        # the one oversized value is truncated to 100 chars.
        s = _sampler()
        vals = [f"S{i}" for i in range(9)] + ["Z" * 250]
        with patch.object(s, "_run", side_effect=_fake_run(total=100, distinct=10, values=vals)):
            out = s.sample_columns("db", "t", [("code", "varchar")])
        assert "code" in out
        assert max(len(v) for v in out["code"]) == 100

    def test_disabled_when_no_workgroup_or_output(self):
        s = AthenaSampler(region="us-east-1", workgroup="", output_location="")
        assert s.enabled is False
        # disabled sampler returns {} without querying
        with patch.object(s, "_run", side_effect=AssertionError("disabled sampler must not query")):
            assert s.sample_columns("db", "t", [("c", "varchar")]) == {}

    def test_per_column_error_is_swallowed(self):
        s = _sampler()
        with patch.object(s, "_run", side_effect=RuntimeError("athena denied")):
            out = s.sample_columns("db", "t", [("c", "varchar")])
        assert out == {}
