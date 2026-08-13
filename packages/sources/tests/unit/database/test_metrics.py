# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the EMF metrics emitter."""

from __future__ import annotations

import json

import structlog.testing
from coa_sources.database.metrics import NAMESPACE, emit_metric


def test_emit_metric_writes_valid_emf(capsys):
    emit_metric("ScanDuration", 123.4, "Milliseconds", SourceType="JDBC_DATABASE")
    doc = json.loads(capsys.readouterr().out.strip())

    assert doc["ScanDuration"] == 123.4
    assert doc["SourceType"] == "JDBC_DATABASE"
    meta = doc["_aws"]["CloudWatchMetrics"][0]
    assert meta["Namespace"] == NAMESPACE
    assert meta["Metrics"][0] == {"Name": "ScanDuration", "Unit": "Milliseconds"}
    assert meta["Dimensions"] == [["SourceType"]]


def test_emit_metric_without_dimensions(capsys):
    emit_metric("GlueThrottleCount", 0, "Count")
    doc = json.loads(capsys.readouterr().out.strip())

    assert doc["GlueThrottleCount"] == 0
    assert doc["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]


def test_emit_metric_drops_none_dimensions(capsys):
    emit_metric("TablesDiscovered", 5, "Count", SourceType=None)
    doc = json.loads(capsys.readouterr().out.strip())

    assert "SourceType" not in doc
    assert doc["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]


class _BadDimension:
    def __str__(self) -> str:
        raise TypeError("not serializable")


def test_emit_metric_failure_logs_name_and_error():
    """A swallowed emission error must still carry the metric name and cause."""
    with structlog.testing.capture_logs() as logs:
        emit_metric("ScanDuration", 1.0, "Milliseconds", SourceType=_BadDimension())

    assert logs == [
        {
            "event": "metric_emission_failed",
            "log_level": "warning",
            "metric_name": "ScanDuration",
            "error": "not serializable",
        }
    ]
