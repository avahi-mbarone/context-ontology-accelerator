# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""DynamoDB-backed store for import job tracking."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
import structlog

logger = structlog.get_logger(__name__)

_TABLE_NAME = os.environ.get("IMPORT_JOBS_TABLE", "coa-dev-metric-import-jobs")
_dynamodb = None


def _get_table():
    global _dynamodb  # noqa: PLW0603
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _dynamodb.Table(_TABLE_NAME)


def create_job(
    namespace_id: str,
    s3_key: str,
    metrics_total: int,
) -> dict[str, Any]:
    """Create a new import job record. Returns the job dict."""
    job_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    item = {
        "PK": f"NS#{namespace_id}",
        "SK": f"IMPORT#{job_id}",
        "jobId": job_id,
        "namespaceId": namespace_id,
        "status": "IN_PROGRESS",
        "s3Key": s3_key,
        "metricsTotal": metrics_total,
        "metricsProcessed": 0,
        "metricsCreated": 0,
        "metricsUpdated": 0,
        "errors": [],
        "warnings": [],
        "createdAt": now,
        "updatedAt": now,
    }
    _get_table().put_item(Item=item)
    logger.info("import_job_created", job_id=job_id, namespace=namespace_id, total=metrics_total)
    return item


def get_job(namespace_id: str, job_id: str) -> dict[str, Any] | None:
    """Fetch a job by ID. Returns None if not found."""
    result = _get_table().get_item(
        Key={"PK": f"NS#{namespace_id}", "SK": f"IMPORT#{job_id}"},
    )
    return result.get("Item")


def update_job_progress(
    namespace_id: str,
    job_id: str,
    metrics_processed: int,
    metrics_created: int,
    metrics_updated: int,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> None:
    """Atomically increment job progress counters.

    Counter arguments are per-chunk deltas. Using DynamoDB ADD (and list_append
    for errors/warnings) makes concurrent updates safe against lost updates.
    """
    now = datetime.now(UTC).isoformat()
    set_parts = ["updatedAt = :ts"]
    expr_values: dict[str, Any] = {
        ":mp": metrics_processed,
        ":mc": metrics_created,
        ":mu": metrics_updated,
        ":ts": now,
    }
    if errors:
        set_parts.append("errors = list_append(errors, :errs)")
        expr_values[":errs"] = errors
    if warnings:
        set_parts.append("warnings = list_append(warnings, :warns)")
        expr_values[":warns"] = warnings

    update_expr = "ADD metricsProcessed :mp, metricsCreated :mc, metricsUpdated :mu SET " + ", ".join(set_parts)

    _get_table().update_item(
        Key={"PK": f"NS#{namespace_id}", "SK": f"IMPORT#{job_id}"},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )


def complete_job(namespace_id: str, job_id: str, status: str = "COMPLETED") -> None:
    """Mark a job as completed or failed."""
    now = datetime.now(UTC).isoformat()
    _get_table().update_item(
        Key={"PK": f"NS#{namespace_id}", "SK": f"IMPORT#{job_id}"},
        UpdateExpression="SET #s = :s, updatedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":ts": now},
    )
    logger.info("import_job_completed", job_id=job_id, status=status)
