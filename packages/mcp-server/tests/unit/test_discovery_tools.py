# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for discovery tools (list_metrics, describe_schema).

Discovery tools invoke backend Lambdas directly via LambdaClient.
These tests mock invoke_api to verify correct parameter construction
and response handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from coa_mcp.tools.discovery import describe_schema, list_metrics


@pytest.fixture
def mock_lambda_client():
    """Mock LambdaClient with async invoke_api."""
    client = AsyncMock()
    return client


@pytest.mark.unit
class TestListMetrics:
    """Tests for the list_metrics discovery tool."""

    @pytest.mark.asyncio
    async def test_invokes_metric_service_lambda(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"metrics": [], "namespace": "ns1"}
        with patch(
            "coa_mcp.tools.discovery.METRIC_SERVICE_LAMBDA",
            "-dev-metric-api",
        ):
            await list_metrics(mock_lambda_client, "ns1", "tok")
        mock_lambda_client.invoke_api.assert_called_once_with(
            function_name="-dev-metric-api",
            method="GET",
            resource="/namespaces/{namespaceId}/metrics",
            path_params={"namespaceId": "ns1"},
            query_params={"maxResults": "100"},
            bearer_token="tok",
            authorizer_context=None,
        )

    @pytest.mark.asyncio
    async def test_returns_metrics(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {
            "metrics": [
                {"metricId": "m1", "name": "Revenue", "description": "Total revenue"},
                {"metricId": "m2", "name": "Churn", "description": "Monthly churn"},
            ],
            "namespace": "sales",
        }
        result = await list_metrics(mock_lambda_client, "sales", "tok")
        assert len(result["metrics"]) == 2
        assert result["metrics"][0]["name"] == "Revenue"
        assert result["namespace"] == "sales"

    @pytest.mark.asyncio
    async def test_empty_namespace(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"metrics": [], "namespace": "empty-ns"}
        result = await list_metrics(mock_lambda_client, "empty-ns", "tok")
        assert result["metrics"] == []

    @pytest.mark.asyncio
    async def test_max_results_capped_at_1000(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"metrics": [], "namespace": "ns"}
        await list_metrics(mock_lambda_client, "ns", "tok", max_results=9999)
        call_kwargs = mock_lambda_client.invoke_api.call_args[1]
        assert call_kwargs["query_params"]["maxResults"] == "1000"

    @pytest.mark.asyncio
    async def test_forwards_bearer_token(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"metrics": [], "namespace": "ns"}
        await list_metrics(mock_lambda_client, "ns", "my-jwt-token")
        call_kwargs = mock_lambda_client.invoke_api.call_args[1]
        assert call_kwargs["bearer_token"] == "my-jwt-token"


@pytest.mark.unit
class TestDescribeSchema:
    """Tests for the describe_schema discovery tool."""

    @pytest.mark.asyncio
    async def test_invokes_ontology_proxy_lambda(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"classes": [], "ontologyVersion": ""}
        with patch(
            "coa_mcp.tools.discovery.ONTOLOGY_PROXY_LAMBDA",
            "-dev-ontology-api-proxy",
        ):
            await describe_schema(mock_lambda_client, "ns1", "tok")
        mock_lambda_client.invoke_api.assert_called_once_with(
            function_name="-dev-ontology-api-proxy",
            method="GET",
            resource="/namespaces/{namespaceId}/graph/schema",
            path_params={"namespaceId": "ns1"},
            query_params={"maxResults": "100", "includeProperties": "true"},
            bearer_token="tok",
            authorizer_context=None,
        )

    @pytest.mark.asyncio
    async def test_returns_classes(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {
            "classes": [
                {"uri": "urn:class:Order", "label": "Order", "description": "Customer orders", "properties": []},
            ],
            "ontologyVersion": "v2",
        }
        result = await describe_schema(mock_lambda_client, "sales", "tok")
        assert len(result["classes"]) == 1
        assert result["classes"][0]["label"] == "Order"

    @pytest.mark.asyncio
    async def test_include_properties_false(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"classes": [], "ontologyVersion": ""}
        await describe_schema(mock_lambda_client, "ns", "tok", include_properties=False)
        call_kwargs = mock_lambda_client.invoke_api.call_args[1]
        assert call_kwargs["query_params"]["includeProperties"] == "false"

    @pytest.mark.asyncio
    async def test_max_results_capped_at_500(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"classes": [], "ontologyVersion": ""}
        await describe_schema(mock_lambda_client, "ns", "tok", max_results=9999)
        call_kwargs = mock_lambda_client.invoke_api.call_args[1]
        assert call_kwargs["query_params"]["maxResults"] == "500"

    @pytest.mark.asyncio
    async def test_default_include_properties_true(self, mock_lambda_client):
        mock_lambda_client.invoke_api.return_value = {"classes": [], "ontologyVersion": ""}
        await describe_schema(mock_lambda_client, "ns", "tok")
        call_kwargs = mock_lambda_client.invoke_api.call_args[1]
        assert call_kwargs["query_params"]["includeProperties"] == "true"
