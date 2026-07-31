# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared EMF metrics emitter."""

from __future__ import annotations

import json

import pytest
from coa_common.metrics import emit_metric

pytestmark = pytest.mark.unit


def test_emit_metric_writes_valid_emf(capsys):
    emit_metric("SemanticContext/Test", "RequestCount", 1, "Count", Reason="ok")
    doc = json.loads(capsys.readouterr().out.strip())

    assert doc["RequestCount"] == 1
    assert doc["Reason"] == "ok"
    meta = doc["_aws"]["CloudWatchMetrics"][0]
    assert meta["Namespace"] == "SemanticContext/Test"
    assert meta["Metrics"][0] == {"Name": "RequestCount", "Unit": "Count"}
    assert meta["Dimensions"] == [["Reason"]]


def test_emit_metric_without_dimensions(capsys):
    emit_metric("SemanticContext/Test", "ErrorCount", 0, "Count")
    doc = json.loads(capsys.readouterr().out.strip())

    assert doc["ErrorCount"] == 0
    assert doc["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]


def test_emit_metric_drops_none_dimensions(capsys):
    emit_metric("SemanticContext/Test", "DenyCount", 1, "Count", Action=None)
    doc = json.loads(capsys.readouterr().out.strip())

    assert "Action" not in doc
    assert doc["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]


def test_emit_metric_swallows_serialization_errors(capsys):
    # An unserializable value must not raise — metrics emission is best-effort
    # and must never break the caller's request handling.
    emit_metric("SemanticContext/Test", "BadMetric", object(), "Count")  # type: ignore[arg-type]
    assert capsys.readouterr().out == ""
