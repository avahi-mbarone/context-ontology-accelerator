# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolve a namespace's VKG service health from ECS service state.

Running (>=1 task, running >= desired) -> HEALTHY; starting up (not yet serving
but its primary deployment is IN_PROGRESS) -> PROVISIONING; exists but not
serving and not rolling out -> UNAVAILABLE; no service / missing config / error
-> UNKNOWN. The ECS health check runs the container's functional /health probe,
so "running" means "can translate". Read on demand from GetNamespace; any
failure degrades to UNKNOWN.
"""

from __future__ import annotations

import os

import boto3
import structlog
from coa_control_plane_server.models import VkgHealthStatus

logger = structlog.get_logger(__name__)

_ecs = None


def _ecs_client():
    global _ecs
    if _ecs is None:
        _ecs = boto3.client("ecs", region_name=os.environ.get("AWS_REGION"))
    return _ecs


def _service_name(namespace_id: str) -> str:
    # Mirrors the reload Lambda's name; rstrip guards a trailing-dash prefix.
    prefix = os.environ.get("RESOURCE_PREFIX", "").rstrip("-")
    return f"{prefix}-vkg-{namespace_id}"


def resolve_vkg_health(namespace_id: str) -> str:
    """Return a VkgHealthStatus value for the namespace's VKG service."""
    cluster = os.environ.get("VKG_CLUSTER_ARN")
    if not cluster or not namespace_id:
        return VkgHealthStatus.UNKNOWN.value

    try:
        resp = _ecs_client().describe_services(
            cluster=cluster,
            services=[_service_name(namespace_id)],
        )
    except Exception as e:
        logger.warning("vkg_health_resolve_failed", namespace_id=namespace_id, error=str(e))
        return VkgHealthStatus.UNKNOWN.value

    # A missing service comes back under `failures`, not `services`.
    active = [s for s in resp.get("services", []) if s.get("status") == "ACTIVE"]
    if not active:
        return VkgHealthStatus.UNKNOWN.value

    svc = active[0]
    running = svc.get("runningCount", 0)
    desired = svc.get("desiredCount", 0)
    if running >= 1 and running >= desired:
        return VkgHealthStatus.HEALTHY.value

    # Not yet serving. Distinguish a service that is still starting up (its primary
    # deployment is rolling out) from one that is genuinely down, so the UI can set
    # the expectation that it will become healthy shortly rather than showing an
    # error. First-time provisioning starts with runningCount 0 < desired and an
    # IN_PROGRESS primary deployment; reloads keep the old task serving
    # (minimumHealthyPercent 100) so they stay HEALTHY above.
    deployments = svc.get("deployments", [])
    primary = next((d for d in deployments if d.get("status") == "PRIMARY"), None)
    if primary is not None and primary.get("rolloutState") == "IN_PROGRESS":
        return VkgHealthStatus.PROVISIONING.value
    return VkgHealthStatus.UNAVAILABLE.value
