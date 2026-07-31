# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Development-only support utilities.

This module contains the Fuseki SPARQL client and CORS/dev-mode helpers
that are only used in local development (SCL_USE_FUSEKI=true or SCL_ALLOW_CORS=true).
It is NOT imported in production — server.py conditionally imports from here
only when the relevant env vars are set.
"""

from __future__ import annotations


class FusekiClient:
    """Lightweight Fuseki SPARQL client for local dev — no SigV4.

    Only used when SCL_USE_FUSEKI=true. In production, NeptuneGraphClient
    with SigV4 is used instead.
    """

    def __init__(self, query_url: str):
        """Store the Fuseki SPARQL query endpoint URL.

        Args:
            query_url: The Fuseki SPARQL query endpoint.
        """
        self._url = query_url

    async def query(self, sparql: str, **kwargs) -> list[dict]:
        """Run a SPARQL query against Fuseki and return flattened result rows.

        Args:
            sparql: The SPARQL query text.
            **kwargs: Ignored; accepted for signature compatibility with the
                production Neptune client.

        Returns:
            One dict per result binding, mapping variable name to its value.
        """
        import httpx

        params = {"query": sparql}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                self._url,
                params=params,
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            data = resp.json()
            bindings = data.get("results", {}).get("bindings", [])
            return [{k: v.get("value", "") for k, v in row.items()} for row in bindings]

    async def health_check(self) -> dict:
        """Return a static healthy status for the local Fuseki client.

        Returns:
            A dict reporting an ``ok`` status.
        """
        return {"status": "ok"}


def add_cors_middleware(app):
    """Add CORS middleware for local demo UI.

    Only called when SCL_ALLOW_CORS=true. Allows the local React
    dev server (port 3000) to talk to the MCP server.
    """
    from starlette.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
    return app
