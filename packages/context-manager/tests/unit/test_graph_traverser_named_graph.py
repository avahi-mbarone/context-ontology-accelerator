# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for graph traverser named-graph STRSTARTS fix (Fix 3).

Covers:
- SPARQL uses GRAPH ?g + STRSTARTS pattern (not fixed GRAPH <uri>)
- _graph_uri_prefix helper
- Empty template guard (returns [] without querying)
- Multiple entities in label query
- FILTER clause escaping
- Query structure validation for both hop levels
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from coa_serve.tier3.graph_traverser import GraphTraverser

GRAPH_URI_TEMPLATE = "https://ontology-workbench.local/{namespace}"


@pytest.fixture
def mock_neptune():
    client = AsyncMock()
    client.query.return_value = []
    return client


@pytest.mark.unit
class TestGraphTraverserNamedGraphPattern:
    """Verify SPARQL queries use STRSTARTS(STR(?g), ...) instead of fixed GRAPH <uri>."""

    async def test_label_query_uses_strstarts(self, mock_neptune):
        """_build_label_query should use GRAPH ?g + STRSTARTS filter, not GRAPH <uri>."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse("claims", "insurance", entities=["claim"])

        query = mock_neptune.query.call_args[0][0]
        assert "GRAPH ?g" in query
        assert "STRSTARTS(STR(?g)" in query
        assert "https://ontology-workbench.local/insurance/" in query
        assert "GRAPH <https://ontology-workbench.local/insurance>" not in query

    async def test_hop_query_2hop_uses_strstarts(self, mock_neptune):
        """_build_hop_query (max_hops=2) should use STRSTARTS pattern."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse_from_uris(["http://ex.org/Claim"], "my-namespace", max_hops=2)

        query = mock_neptune.query.call_args[0][0]
        assert "GRAPH ?g" in query
        assert "STRSTARTS(STR(?g)" in query
        assert "https://ontology-workbench.local/my-namespace/" in query
        assert "GRAPH <https://ontology-workbench.local/my-namespace>" not in query

    async def test_hop_query_1hop_uses_strstarts(self, mock_neptune):
        """_build_hop_query (max_hops=1) should use STRSTARTS pattern."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse_from_uris(["http://ex.org/Claim"], "test-ns", max_hops=1)

        query = mock_neptune.query.call_args[0][0]
        assert "GRAPH ?g" in query
        assert "STRSTARTS(STR(?g)" in query
        assert "https://ontology-workbench.local/test-ns/" in query
        assert "UNION" in query  # 1-hop uses UNION pattern

    async def test_graph_uri_prefix_trailing_slash(self, mock_neptune):
        """Prefix should always end with / for proper STRSTARTS matching."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        prefix = traverser._graph_uri_prefix("my-ns")
        assert prefix == "https://ontology-workbench.local/my-ns/"

    async def test_graph_uri_prefix_deduplicates_slash(self, mock_neptune):
        """If template already produces trailing slash, don't double up."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template="https://example.com/{namespace}/")
        prefix = traverser._graph_uri_prefix("test")
        assert prefix == "https://example.com/test/"
        assert "//" not in prefix.replace("https://", "")


@pytest.mark.unit
class TestGraphTraverserEmptyTemplate:
    """When graph_uri_template is empty/unset, traverser should return [] without querying."""

    async def test_traverse_returns_empty_no_template(self, mock_neptune):
        """traverse() with no template configured returns [] and never queries."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template="")
        results = await traverser.traverse("claims", "insurance", entities=["claim"])
        assert results == []
        mock_neptune.query.assert_not_awaited()

    async def test_traverse_from_uris_returns_empty_no_template(self, mock_neptune):
        """traverse_from_uris() with no template returns [] and never queries."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template="")
        results = await traverser.traverse_from_uris(["http://ex.org/Claim"], "insurance", max_hops=2)
        assert results == []
        mock_neptune.query.assert_not_awaited()


@pytest.mark.unit
class TestGraphTraverserQueryStructure:
    """Validate the structure of generated SPARQL queries."""

    async def test_label_query_multiple_entities(self, mock_neptune):
        """Multiple entities produce OR-ed CONTAINS filters."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse("claims and policies", "ns", entities=["claim", "policy"])

        query = mock_neptune.query.call_args[0][0]
        assert 'CONTAINS(LCASE(?label), "claim")' in query
        assert 'CONTAINS(LCASE(?label), "policy")' in query
        assert "||" in query

    async def test_label_query_escapes_quotes(self, mock_neptune):
        """Entities with quotes are properly escaped in SPARQL."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        # Entity with a double-quote char
        await traverser.traverse("test", "ns", entities=['foo"bar'])
        # The entity is sanitized by _sanitize_entities which only allows [a-z0-9_-]
        # So this shouldn't make it through — verifying the sanitizer works
        mock_neptune.query.assert_not_awaited()

    async def test_label_query_has_optional_relationships(self, mock_neptune):
        """Label query includes OPTIONAL block for relationships."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse("claims", "ns", entities=["claim"])

        query = mock_neptune.query.call_args[0][0]
        assert "OPTIONAL" in query
        assert "?predicate" in query
        assert "?related" in query
        assert "?relLabel" in query

    async def test_label_query_has_limit(self, mock_neptune):
        """Label query has a LIMIT clause."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse("claims", "ns", entities=["claim"])

        query = mock_neptune.query.call_args[0][0]
        assert "LIMIT" in query

    async def test_hop_query_2hop_has_values_clause(self, mock_neptune):
        """2-hop query includes VALUES ?seed with the provided URIs."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse_from_uris(["http://ex.org/A", "http://ex.org/B"], "ns", max_hops=2)

        query = mock_neptune.query.call_args[0][0]
        assert "VALUES ?seed" in query
        assert "<http://ex.org/A>" in query
        assert "<http://ex.org/B>" in query

    async def test_hop_query_2hop_has_hop2_variables(self, mock_neptune):
        """2-hop query surfaces class↔class edges via the induced property
        domain/range arm (replaces the former hop2 second-level variables)."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse_from_uris(["http://ex.org/Claim"], "ns", max_hops=2)

        query = mock_neptune.query.call_args[0][0]
        assert "(rdfs:domain|rdfs:range)" in query
        assert "?relPredicate" in query
        assert "?related" in query

    async def test_hop_query_1hop_no_hop2_variables(self, mock_neptune):
        """Query should NOT include the legacy hop2 second-level variables."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse_from_uris(["http://ex.org/Claim"], "ns", max_hops=1)

        query = mock_neptune.query.call_args[0][0]
        assert "hop2" not in query
        assert "UNION" in query

    async def test_hop_query_1hop_bidirectional(self, mock_neptune):
        """Query traverses both direct directions (outgoing and incoming) plus
        the induced property-node arm."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse_from_uris(["http://ex.org/Claim"], "ns", max_hops=1)

        query = mock_neptune.query.call_args[0][0]
        # Direct arms (non-induced ontologies): both edge directions present.
        assert "?seed ?relPredicate ?entity" in query
        assert "?entity ?relPredicate ?seed" in query
        # Induced arm: property node bridged off the seed class.
        assert "?entity (rdfs:domain|rdfs:range) ?seed" in query

    async def test_hop_query_limits_to_10_uris(self, mock_neptune):
        """traverse_from_uris caps at 10 URIs to prevent bloated queries."""
        uris = [f"http://ex.org/Entity{i}" for i in range(20)]
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse_from_uris(uris, "ns", max_hops=2)

        query = mock_neptune.query.call_args[0][0]
        # Only first 10 should appear
        assert "<http://ex.org/Entity9>" in query
        assert "<http://ex.org/Entity10>" not in query

    async def test_strstarts_filter_outside_graph_block(self, mock_neptune):
        """STRSTARTS FILTER should be outside the GRAPH ?g block (at WHERE level)."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        await traverser.traverse("claims", "ns", entities=["claim"])

        query = mock_neptune.query.call_args[0][0]
        # The FILTER(STRSTARTS...) should appear after the closing }} of GRAPH ?g
        # Simple structural check: STRSTARTS appears after the last entity FILTER
        strstarts_pos = query.find("STRSTARTS")
        graph_g_pos = query.find("GRAPH ?g")
        assert strstarts_pos > graph_g_pos


@pytest.mark.unit
class TestGraphTraverserNamespaceInPrefix:
    """Verify the namespace is properly embedded in the graph URI prefix."""

    async def test_namespace_with_uuid(self, mock_neptune):
        """UUID-style namespaces work correctly."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        prefix = traverser._graph_uri_prefix("385e5e21-ac50-48a1-b59b-bbba19f26a24")
        assert prefix == "https://ontology-workbench.local/385e5e21-ac50-48a1-b59b-bbba19f26a24/"

    async def test_namespace_with_simple_name(self, mock_neptune):
        """Simple alphanumeric namespaces work."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template=GRAPH_URI_TEMPLATE)
        prefix = traverser._graph_uri_prefix("bird-benchmark")
        assert prefix == "https://ontology-workbench.local/bird-benchmark/"

    async def test_different_template_base(self, mock_neptune):
        """Custom template bases are respected."""
        traverser = GraphTraverser(mock_neptune, graph_uri_template="https://custom.domain.com/graphs/{namespace}")
        prefix = traverser._graph_uri_prefix("my-ns")
        assert prefix == "https://custom.domain.com/graphs/my-ns/"
