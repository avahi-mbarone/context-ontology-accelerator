# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Minimal CloudWatch metric emitter using Embedded Metric Format (EMF).

EMF JSON written to stdout is auto-extracted into CloudWatch metrics by the
Lambda log pipeline — no PutMetricData call, so no extra IAM grant or latency.

Shared across packages (e.g. ``sources``, ``control-plane``) that need
low-overhead custom metrics from within a Lambda handler. Package-specific
wrappers may set their own namespace and default dimensions on top of this.
"""

from __future__ import annotations

import json
import time


def emit_metric(namespace: str, name: str, value: float, unit: str = "None", **dimensions: str | None) -> None:
    """Emit a single EMF metric. Dimensions must be low-cardinality."""
    try:
        dims = {k: str(v) for k, v in dimensions.items() if v is not None}
        doc = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": namespace,
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
