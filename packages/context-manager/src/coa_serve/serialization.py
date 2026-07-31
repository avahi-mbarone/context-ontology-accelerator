# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""JSON serialization utilities for streaming event payloads.

Provides safe type coercion for values that stdlib ``json.dumps`` rejects
(Decimal, date/datetime/time) so event payloads serialize without raising.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal


def json_safe(obj: object) -> object:
    """Recursively convert a value into JSON-native types.

    Query result rows can carry types the stdlib encoder rejects, notably
    ``Decimal`` from a ``numeric``/``DECIMAL`` DB column (asyncpg). Left
    unconverted, serialization raises and the response is never delivered.

    Decimal → float; date/time → ISO-8601 string; containers are handled
    recursively.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (_dt.date, _dt.datetime, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj
