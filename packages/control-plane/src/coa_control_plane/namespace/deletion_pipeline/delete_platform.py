# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deletion pipeline step: platform-level cleanup.

Tears down the VKG ECS service, Athena workgroup, DataZone project, and
namespace role mappings/roles. All best-effort (log + swallow) except role
mappings/roles, which raise on DynamoDB errors so the state machine's retry
policy applies — these must succeed for the namespace to be considered
fully cleaned up (unlike VKG/Athena/DataZone teardown, which are already
best-effort in ``cleanup.py``).
"""

from __future__ import annotations

from typing import Any

import structlog

from coa_control_plane.namespace.cleanup import (
    delete_athena_workgroup,
    delete_role_mappings,
    delete_roles,
    delete_smu_project,
    teardown_vkg_service,
)

logger = structlog.get_logger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions task: platform-level namespace cleanup.

    Input: {"namespaceId": str, "athenaWorkgroupName": str | None,
            "dataZoneProjectId": str | None}
    Output: {"namespaceId": str}
    """
    namespace_id = event["namespaceId"]

    teardown_vkg_service(namespace_id)
    delete_athena_workgroup(event.get("athenaWorkgroupName"))
    delete_smu_project(namespace_id, {"dataZoneProjectId": event.get("dataZoneProjectId")})

    # Role mappings/roles use the real DynamoDBDAO path (not best-effort) —
    # a failure here must fail the step so Step Functions retries it.
    delete_role_mappings(namespace_id)
    delete_roles(namespace_id)

    logger.info("namespace_platform_cleanup_complete", namespace_id=namespace_id)
    return {"namespaceId": namespace_id}
