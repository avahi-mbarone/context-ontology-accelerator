# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for MetricResolver SPARQL graph-naming fix.

Verifies that _metric_list_sparql():
1. Uses STRSTARTS with the correct graph URI prefix
2. Uses a BIND/REPLACE regex to extract namespace from graph URI
3. Produces valid SPARQL (single braces)
4. Reflects custom graph URI templates
5. Uses proper XPath regex escaping for the prefix
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from coa_serve.tier1.metric_resolver import (
    MetricResolver,
    _metric_list_sparql,
)


@pytest.mark.unit
class TestMetricResolverSparqlGraphNaming:
    """Verify metric list SPARQL targets the correct named graph."""

    def test_uses_strstarts(self):
        """SPARQL uses STRSTARTS with the template's static prefix."""
        sparql = _metric_list_sparql("https://ontology-workbench.local/{namespace}")

        assert "STRSTARTS(STR(?g)" in sparql
        assert "https://ontology-workbench.local/" in sparql
        assert "GRAPH ?g" in sparql
        assert "GRAPH <" not in sparql

    def test_extracts_namespace_via_replace(self):
        """BIND/REPLACE extracts namespace from graph URI."""
        sparql = _metric_list_sparql("https://ontology-workbench.local/{namespace}")

        assert "BIND(REPLACE(STR(?g)" in sparql
        assert "AS ?namespace)" in sparql

    def test_single_braces_in_output(self):
        """Generated SPARQL must have single braces (valid SPARQL)."""
        sparql = _metric_list_sparql("https://ontology-workbench.local/{namespace}")

        assert "{{" not in sparql
        assert "}}" not in sparql

    def test_custom_base_url(self):
        """Custom template is reflected in STRSTARTS prefix."""
        sparql = _metric_list_sparql("https://my-neptune.prod.internal/{namespace}")

        assert "https://my-neptune.prod.internal/" in sparql
        assert "ontology-workbench" not in sparql

    def test_default_template_fallback(self):
        """Empty template uses the default and still produces valid SPARQL."""
        sparql = _metric_list_sparql("")

        assert "STRSTARTS" in sparql
        assert "GRAPH ?g" in sparql
        assert "ontology-workbench.local" in sparql

    def test_xpath_regex_escaping(self):
        """Dots in the prefix are escaped in the REPLACE regex."""
        sparql = _metric_list_sparql("https://ontology.example.com/{namespace}")

        # The REPLACE regex should escape the dots (doubled for SPARQL string literal)
        assert "ontology\\\\.example\\\\.com" in sparql

    def test_resolver_uses_metric_list_sparql(self):
        """MetricResolver._refresh_from_neptune passes the correct SPARQL."""
        mock_neptune = AsyncMock()
        mock_neptune.query.return_value = []
        resolver = MetricResolver(neptune_client=mock_neptune)

        import asyncio

        asyncio.run(resolver._refresh_from_neptune())

        mock_neptune.query.assert_called_once()
        sparql_arg = mock_neptune.query.call_args[0][0]
        assert "STRSTARTS" in sparql_arg
        assert "GRAPH ?g" in sparql_arg
