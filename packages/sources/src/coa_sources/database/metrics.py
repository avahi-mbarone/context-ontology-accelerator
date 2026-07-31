# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Minimal CloudWatch metric emitter using Embedded Metric Format (EMF).

EMF JSON written to stdout is auto-extracted into CloudWatch metrics by the
Lambda log pipeline — no PutMetricData call, so no extra IAM grant or latency.
"""

from __future__ import annotations

import json
import time

NAMESPACE = "SemanticContext/Sources"


def emit_metric(name: str, value: float, unit: str = "None", **dimensions: str) -> None:
    """Emit a single EMF metric. Dimensions must be low-cardinality."""
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
    except Exception:  # noqa: BLE001
        pass
