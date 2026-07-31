# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""List Metrics Lambda handler.

GET /namespaces/{namespaceId}/metrics → 200 OK

Returns paginated list of metrics with optional filters.
Query params: dataSourceId, sourceTable, maxResults, nextToken
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from coa_common.logging import setup_logging
from coa_common.response import api_response

from coa_metrics.api.create_metric import _metric_to_dict
from coa_metrics.neptune_client import MetricNeptuneClient

setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
logger = structlog.get_logger(__name__)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

_neptune: MetricNeptuneClient | None = None


def _get_neptune() -> MetricNeptuneClient:
    global _neptune  # noqa: PLW0603
    if _neptune is None:
        _neptune = MetricNeptuneClient()
    return _neptune


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Gateway proxy-integration Lambda handler for GET /namespaces/{ns}/metrics."""
    namespace = event.get("pathParameters", {}).get("namespaceId", "")
    query_params = event.get("queryStringParameters") or {}
    logger.info("list_metrics", namespace=namespace, filters=query_params)

    # Parse pagination
    try:
        limit = min(int(query_params.get("maxResults", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
    except (ValueError, TypeError):
        limit = DEFAULT_PAGE_SIZE

    # Parse nextToken as offset (simple offset-based pagination for Neptune)
    try:
        offset = int(query_params.get("nextToken", "0"))
    except (ValueError, TypeError):
        offset = 0

    # Parse filters
    data_source_id = query_params.get("dataSourceId")
    source_table = query_params.get("sourceTable")

    # Query Neptune
    metrics = _get_neptune().list_metrics(
        namespace=namespace,
        data_source_id=data_source_id,
        source_table=source_table,
        limit=limit + 1,  # fetch one extra to determine if there's a next page
        offset=offset,
    )

    # Determine pagination
    has_next = len(metrics) > limit
    if has_next:
        metrics = metrics[:limit]
    next_token = str(offset + limit) if has_next else None

    response_body: dict[str, Any] = {
        "metrics": [_metric_to_dict(m) for m in metrics],
    }
    if next_token:
        response_body["nextToken"] = next_token

    return api_response(200, response_body)
