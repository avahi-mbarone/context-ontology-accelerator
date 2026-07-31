# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Get Import Job Lambda handler.

GET /namespaces/{namespaceId}/import-jobs/{jobId} → 200 OK

Returns the current status and progress of an async import job.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from coa_common.logging import setup_logging
from coa_common.response import api_response

from coa_metrics.api.import_job_store import get_job

setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
logger = structlog.get_logger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Gateway proxy-integration Lambda handler."""
    namespace_id = event.get("pathParameters", {}).get("namespaceId", "")
    job_id = event.get("pathParameters", {}).get("jobId", "")
    logger.info("get_import_job", namespace=namespace_id, job_id=job_id)

    if not job_id:
        return api_response(400, {"message": "jobId is required"})

    job = get_job(namespace_id, job_id)
    if not job:
        return api_response(404, {"message": f"Import job '{job_id}' not found"})

    return api_response(
        200,
        {
            "jobId": job["jobId"],
            "status": job["status"],
            "metricsTotal": job.get("metricsTotal", 0),
            "metricsProcessed": job.get("metricsProcessed", 0),
            "metricsCreated": job.get("metricsCreated", 0),
            "metricsUpdated": job.get("metricsUpdated", 0),
            "errors": job.get("errors", []),
            "warnings": job.get("warnings", []),
        },
    )
