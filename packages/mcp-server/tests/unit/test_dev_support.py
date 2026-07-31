# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for local-dev support utilities (Fuseki client + CORS middleware).

These are only used in local development. Fuseki HTTP calls are mocked so no
real network access occurs; the CORS helper is tested against a real Starlette
app instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from coa_mcp.dev_support import FusekiClient, add_cors_middleware


@pytest.mark.unit
class TestFusekiClient:
    @pytest.mark.asyncio
    async def test_query_flattens_sparql_json_bindings(self):
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "results": {
                "bindings": [
                    {"s": {"value": "urn:a"}, "label": {"value": "Alpha"}},
                    {"s": {"value": "urn:b"}, "label": {"value": "Beta"}},
                ]
            }
        }

        mock_async_client = AsyncMock()
        mock_async_client.get = AsyncMock(return_value=fake_resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_async_client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=cm):
            client = FusekiClient("http://localhost:3030/coa/query")
            rows = await client.query("SELECT * WHERE { ?s ?p ?o }")

        assert rows == [
            {"s": "urn:a", "label": "Alpha"},
            {"s": "urn:b", "label": "Beta"},
        ]

    @pytest.mark.asyncio
    async def test_query_empty_bindings_returns_empty_list(self):
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"results": {"bindings": []}}

        mock_async_client = AsyncMock()
        mock_async_client.get = AsyncMock(return_value=fake_resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_async_client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=cm):
            client = FusekiClient("http://localhost:3030/coa/query")
            rows = await client.query("ASK {}")

        assert rows == []

    @pytest.mark.asyncio
    async def test_health_check_returns_ok(self):
        client = FusekiClient("http://localhost:3030/coa/query")
        assert await client.health_check() == {"status": "ok"}


@pytest.mark.unit
class TestAddCorsMiddleware:
    def test_adds_cors_middleware_to_app(self):
        from starlette.applications import Starlette
        from starlette.middleware.cors import CORSMiddleware

        app = Starlette()
        returned = add_cors_middleware(app)
        assert returned is app
        assert any(mw.cls is CORSMiddleware for mw in app.user_middleware)
