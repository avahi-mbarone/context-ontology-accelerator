# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Discovery tools — list_metrics and describe_schema.

Delegated to backend Lambdas via direct invocation (bypassing API Gateway).
The MCP server is a thin protocol adapter; all DB/Bedrock access is in the Lambdas.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from ..clients.lambda_client import LambdaClient

logger = structlog.get_logger(__name__)

METRIC_SERVICE_LAMBDA = os.environ.get("METRIC_SERVICE_LAMBDA_ARN", "")
ONTOLOGY_PROXY_LAMBDA = os.environ.get("ONTOLOGY_PROXY_LAMBDA_ARN", "")


async def list_metrics(
    lambda_client: LambdaClient,
    namespace_id: str,
    bearer_token: str,
    *,
    max_results: int = 100,
    authorizer_context: dict | None = None,
) -> dict[str, Any]:
    """List governed metric definitions via Lambda invocation.

    Args:
        lambda_client: Lambda client for direct invocation.
        namespace_id: The namespace to query.
        bearer_token: Caller's JWT for identity propagation.
        max_results: Maximum metrics to return (default 100, max 1000).
        authorizer_context: Optional authorizer context for the synthetic event.

    Returns:
        Dict with 'metrics' list.
    """
    return await lambda_client.invoke_api(
        function_name=METRIC_SERVICE_LAMBDA,
        method="GET",
        resource="/namespaces/{namespaceId}/metrics",
        path_params={"namespaceId": namespace_id},
        query_params={"maxResults": str(min(max_results, 1000))},
        bearer_token=bearer_token,
        authorizer_context=authorizer_context,
    )


async def describe_schema(
    lambda_client: LambdaClient,
    namespace_id: str,
    bearer_token: str,
    *,
    max_results: int = 100,
    include_properties: bool = True,
    authorizer_context: dict | None = None,
) -> dict[str, Any]:
    """Describe ontology classes and properties via Lambda invocation.

    Args:
        lambda_client: Lambda client for direct invocation.
        namespace_id: The namespace to query.
        bearer_token: Caller's JWT for identity propagation.
        max_results: Maximum classes to return (default 100, max 500).
        include_properties: Whether to include properties (default True).
        authorizer_context: Optional authorizer context for the synthetic event.

    Returns:
        Dict with 'classes' and 'ontologyVersion'.
    """
    return await lambda_client.invoke_api(
        function_name=ONTOLOGY_PROXY_LAMBDA,
        method="GET",
        resource="/namespaces/{namespaceId}/graph/schema",
        path_params={"namespaceId": namespace_id},
        query_params={
            "maxResults": str(min(max_results, 500)),
            "includeProperties": str(include_properties).lower(),
        },
        bearer_token=bearer_token,
        authorizer_context=authorizer_context,
    )
