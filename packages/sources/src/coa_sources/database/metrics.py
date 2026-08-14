# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Minimal CloudWatch metric emitter using Embedded Metric Format (EMF).

EMF JSON written to stdout is auto-extracted into CloudWatch metrics by the
Lambda log pipeline — no PutMetricData call, so no extra IAM grant or latency.
"""

from __future__ import annotations

import json
import time

import structlog

NAMESPACE = "COA/Sources"

logger = structlog.get_logger(__name__)


def emit_metric(name: str, value: float, unit: str = "None", **dimensions: str) -> None:
    """Emit a single EMF metric. Dimensions must be low-cardinality.

    Emission is best-effort: a bad dimension, JSON-encoding, or stdout error must
    never crash the scan. But the failure must be observable — a swallowed error
    darkens a dashboard widget with no trail — so it is logged rather than passed.
    """
    try:
        dims = {k: str(v) for k, v in dimensions.items() if v is not None}
        doc = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": [list(dims.keys())],
                        "Metrics": [{"Name": name, "Unit": unit}],
                    }
                ],
            },
            name: value,
            **dims,
        }
        print(json.dumps(doc))
    except Exception as exc:  # noqa: BLE001 — emission must not crash the caller
        logger.warning("metric_emission_failed", metric_name=name, error=str(exc))
