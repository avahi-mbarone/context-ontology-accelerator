# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deletion pipeline step: mark namespace as DELETE_FAILED.

Invoked from the Step Functions ``Catch`` on any unrecoverable step failure
(after retries are exhausted). Sets the namespace status to DELETE_FAILED so
the client can retry deletion — the DELETE endpoint accepts DELETE_FAILED
as a valid starting state and re-runs the whole pipeline (idempotent: every
step here tolerates re-running against already-partially-deleted resources,
e.g. "source not found" on a repeat delete is treated as success).
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from coa_common.dao import DynamoDBDAO

logger = structlog.get_logger(__name__)

_ns_dao: DynamoDBDAO | None = None


def _get_ns_dao() -> DynamoDBDAO:
    global _ns_dao  # noqa: PLW0603
    if _ns_dao is None:
        _ns_dao = DynamoDBDAO(os.environ["NAMESPACES_TABLE"], region=os.environ["AWS_REGION"])
    return _ns_dao


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions task: set namespace status to DELETE_FAILED.

    Input: {"namespaceId": str, "error": <Step Functions error info>}
    Output: {"namespaceId": str, "status": "DELETE_FAILED"}
    """
    namespace_id = event["namespaceId"]
    error = event.get("error")

    logger.error("namespace_deletion_failed", namespace_id=namespace_id, error=error)

    _get_ns_dao().update(
        key={"PK": f"NS#{namespace_id}", "SK": "METADATA"},
        update_fields={"status": "DELETE_FAILED"},
    )

    return {"namespaceId": namespace_id, "status": "DELETE_FAILED"}
