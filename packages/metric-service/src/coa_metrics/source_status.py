# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""APPROVED-source enforcement for metric creation/update.

The UI's Create Metric form only offers sources with status APPROVED or
COMPLETED; the API and OSI import must enforce the same rule so they cannot
be used to bypass it. This module reads the source record directly from the
unified sources table (``PK=NS#{namespaceId}``, ``SK=SRC#{sourceId}`` —
written by ``packages/sources``) and checks its ``status``.

Fail-closed by default: if the sources table is not configured or the read
fails, enforcement raises ``SourceValidationUnavailableError`` (callers map
this to a 503) instead of silently allowing the reference. Set
``ALLOW_PERMISSIVE_SOURCE_LOOKUP=true`` (dev/testing only) to skip
enforcement — a WARNING is logged whenever permissive mode is active.
"""

from __future__ import annotations

import os

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from coa_common.dao import DynamoDBDAO
from coa_control_plane_server.models.source_status import SourceStatus

logger = structlog.get_logger(__name__)

PERMISSIVE_ENV = "ALLOW_PERMISSIVE_SOURCE_LOOKUP"

# Statuses a metric may reference — keep in sync with the UI filter in
# packages/web-app/src/pages/MetricForm.tsx (APPROVED || COMPLETED).
_ALLOWED_STATUSES = frozenset({SourceStatus.APPROVED.value, SourceStatus.COMPLETED.value})


class SourceValidationUnavailableError(RuntimeError):
    """Source status could not be verified (missing config or read failure)."""


def permissive_lookup_enabled() -> bool:
    """True when the dev-only permissive mode is explicitly enabled via env."""
    return os.environ.get(PERMISSIVE_ENV, "").lower() == "true"


def check_source_approved(namespace: str, data_source_id: str) -> str | None:
    """Verify the referenced data source is APPROVED/COMPLETED.

    Args:
        namespace: The namespace the metric belongs to.
        data_source_id: The source referenced by the metric's ``dataSourceId``.

    Returns:
        None when the source is approved (or permissive mode is enabled),
        otherwise a human-readable rejection message for a 400 response.

    Raises:
        SourceValidationUnavailableError: When enforcement is impossible
            (table not configured, or the DynamoDB read failed) and
            permissive mode is not enabled — fail closed.
    """
    if not data_source_id:
        return "dataSourceId is required"

    if permissive_lookup_enabled():
        logger.warning(
            "permissive_source_lookup_active",
            namespace=namespace,
            data_source_id=data_source_id,
            detail="source approval NOT enforced — dev/testing mode",
        )
        return None

    table = os.environ.get("DATA_SOURCES_TABLE", "")
    if not table:
        raise SourceValidationUnavailableError("DATA_SOURCES_TABLE not configured")

    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        item = DynamoDBDAO(table, region=region).get({"PK": f"NS#{namespace}", "SK": f"SRC#{data_source_id}"})
    except ClientError as exc:
        # Surface the specific AWS error code (ResourceNotFoundException,
        # AccessDeniedException, ProvisionedThroughputExceededException, …)
        # so operational issues are diagnosable from the 503 + logs.
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.error(
            "sources_table_read_failed",
            table=table,
            namespace=namespace,
            data_source_id=data_source_id,
            error_code=error_code,
            exc_info=True,
        )
        raise SourceValidationUnavailableError(f"sources table read failed ({error_code}): {exc}") from exc
    except BotoCoreError as exc:
        # Non-API boto3 failures (connection, endpoint, credential resolution).
        logger.error(
            "sources_table_read_failed",
            table=table,
            namespace=namespace,
            data_source_id=data_source_id,
            error_code=type(exc).__name__,
            exc_info=True,
        )
        raise SourceValidationUnavailableError(f"sources table read failed ({type(exc).__name__}): {exc}") from exc
    except Exception as exc:
        # Last-resort fallback so an unexpected error still fails closed as a
        # 503 (SourceValidationUnavailableError) instead of a raw 500.
        logger.error(
            "sources_table_read_failed_unexpected",
            table=table,
            namespace=namespace,
            data_source_id=data_source_id,
            error_code=type(exc).__name__,
            exc_info=True,
        )
        raise SourceValidationUnavailableError(f"sources table read failed: {exc}") from exc

    if not item:
        return f"Data source '{data_source_id}' does not exist in namespace '{namespace}'"

    status = str(item.get("status", ""))
    if status not in _ALLOWED_STATUSES:
        return (
            f"Data source '{data_source_id}' has status '{status or 'UNKNOWN'}' — "
            f"metrics can only reference APPROVED or COMPLETED sources"
        )
    return None
