# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the ontology source abstraction (task 9).

Covers ``coa_serve.tier3.agentic.ontology.source``:

- :class:`OntologyFileSource` parses a fixture ``.ttl`` into an :class:`Ontology`
  with the determined node types, edge types, and the directional source→target
  ``edge_map`` per edge type (Req 3.1);
- :class:`OntologyGraphSource` shapes a mocked SPARQL response into the SAME
  :class:`Ontology` shape — proving both backends are interchangeable, including
  the directional source→target per edge type (Req 3.6);
- datatype properties are excluded from edge types, and an object property with
  no declared domain/range still surfaces as an edge type but contributes no
  directional ``edge_map`` triple;
- module load of the ontology source does NOT import ``graphrag_toolkit``
  (Req 12.3).

The graph source is exercised through a fake :class:`GraphClient` whose ``query``
returns canned SPARQL bindings (distinguished by the projected variable), so the
test exercises the real query-building + binding-parsing path with no Neptune and
no ``graphrag_toolkit`` access.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from coa_serve.tier3.agentic.ontology.source import (
    Ontology,
    OntologyFileSource,
    OntologyGraphSource,
)

FIXTURE_TTL = str(Path(__file__).parent / "fixtures" / "ontology_sample.ttl")

# The ontology the fixture .ttl encodes, in the uniform Ontology shape.
EXPECTED_NODE_TYPES = ("Company", "FinancialReport", "Person")
EXPECTED_EDGE_TYPES = ("COMPETES_WITH", "HAS_FINANCIALS", "RELATED_TO", "WORKS_FOR")
EXPECTED_EDGE_MAP = (
    ("COMPETES_WITH", "Company", "Company"),
    ("HAS_FINANCIALS", "Company", "FinancialReport"),
    ("WORKS_FOR", "Person", "Company"),
)


class _FakeGraphClient:
    """Synchronous-bindings fake of the read-only SPARQL ``GraphClient``.

    Returns canned bindings keyed on which projection the query selects so the
    node-type and edge-type queries get their respective responses. Records the
    SPARQL it was asked to run so the test can assert the published named graph
    is targeted.
    """

    def __init__(self, node_rows, edge_rows):
        self._node_rows = node_rows
        self._edge_rows = edge_rows
        self.queries: list[str] = []

    async def query(self, sparql: str):
        self.queries.append(sparql)
        if "?classLabel" in sparql:
            return list(self._node_rows)
        if "?propLabel" in sparql:
            return list(self._edge_rows)
        raise AssertionError(f"unexpected SPARQL: {sparql!r}")


def _graph_source_matching_fixture() -> tuple[OntologyGraphSource, _FakeGraphClient]:
    """An ``OntologyGraphSource`` over a fake client whose bindings mirror the .ttl.

    The bindings intentionally reproduce the fixture: three classes, three
    fully-directional object properties, and one object property (``RELATED_TO``)
    with no domain/range — so a successful parity assertion proves both backends
    produce the identical shape from equivalent source data.
    """
    node_rows = [{"classLabel": label} for label in ("Company", "FinancialReport", "Person")]
    edge_rows = [
        {"propLabel": "COMPETES_WITH", "domainLabel": "Company", "rangeLabel": "Company"},
        {"propLabel": "HAS_FINANCIALS", "domainLabel": "Company", "rangeLabel": "FinancialReport"},
        {"propLabel": "WORKS_FOR", "domainLabel": "Person", "rangeLabel": "Company"},
        {"propLabel": "RELATED_TO"},  # no domain/range → edge type only, no edge_map triple
    ]
    client = _FakeGraphClient(node_rows, edge_rows)
    # Per-ontology graphs live under a namespace prefix from this template — the
    # same shape the serve GraphTraverser + the ontology write side use.
    return OntologyGraphSource(client, graph_uri_template="https://ontology-workbench.local/{namespace}"), client


# ── OntologyFileSource ─────────────────────────────────────────────


@pytest.mark.unit
class TestOntologyFileSource:
    async def test_parses_fixture_into_expected_shape(self):
        onto = await OntologyFileSource(FIXTURE_TTL).load("any-namespace")
        assert onto.node_types == EXPECTED_NODE_TYPES
        assert onto.edge_types == EXPECTED_EDGE_TYPES
        assert onto.edge_map == EXPECTED_EDGE_MAP

    async def test_directional_source_to_target_per_edge_type(self):
        """Each edge_map triple is (edge_type, source_node_type, target_node_type) (Req 3.1)."""
        onto = await OntologyFileSource(FIXTURE_TTL).load("ns")
        by_edge = {edge: (src, tgt) for edge, src, tgt in onto.edge_map}
        # HAS_FINANCIALS is directional Company → FinancialReport (not the reverse).
        assert by_edge["HAS_FINANCIALS"] == ("Company", "FinancialReport")
        # WORKS_FOR is directional Person → Company.
        assert by_edge["WORKS_FOR"] == ("Person", "Company")

    async def test_datatype_property_excluded_from_edges(self):
        onto = await OntologyFileSource(FIXTURE_TTL).load("ns")
        assert "revenue" not in onto.edge_types

    async def test_object_property_without_domain_range_has_no_edge_map(self):
        onto = await OntologyFileSource(FIXTURE_TTL).load("ns")
        # RELATED_TO is a declared edge type...
        assert "RELATED_TO" in onto.edge_types
        # ...but contributes no directional triple.
        assert all(edge != "RELATED_TO" for edge, _, _ in onto.edge_map)

    async def test_missing_file_raises(self):
        # A missing/unreadable .ttl surfaces as an OSError (FileNotFoundError) at
        # load time, mirroring the graph source's raise-on-failure contract.
        with pytest.raises(OSError):
            await OntologyFileSource("/nonexistent/path/ontology.ttl").load("ns")


# ── OntologyGraphSource ────────────────────────────────────────────


@pytest.mark.unit
class TestOntologyGraphSource:
    async def test_shapes_sparql_response_into_expected_shape(self):
        source, _ = _graph_source_matching_fixture()
        onto = await source.load("acme-namespace")
        assert onto.node_types == EXPECTED_NODE_TYPES
        assert onto.edge_types == EXPECTED_EDGE_TYPES
        assert onto.edge_map == EXPECTED_EDGE_MAP

    async def test_queries_namespace_ontology_graphs_by_prefix(self):
        """Queries the namespace's per-ontology graphs via GRAPH ?g + STRSTARTS on
        the namespace prefix (matching GraphTraverser + the ontology write side),
        NOT a hardcoded single :published graph (which nothing writes → empty)."""
        source, client = _graph_source_matching_fixture()
        await source.load("acme-namespace")
        assert len(client.queries) == 2
        for sparql in client.queries:
            assert "GRAPH ?g" in sparql
            assert 'STRSTARTS(STR(?g), "https://ontology-workbench.local/acme-namespace/")' in sparql

    async def test_empty_ontology_when_no_graph_uri_template(self):
        """With no graph-URI template the namespace has no queryable ontology graph,
        so load returns an empty Ontology WITHOUT issuing an unscoped query."""
        source, client = _graph_source_matching_fixture()
        source._graph_uri_template = ""  # simulate unconfigured template
        onto = await source.load("acme-namespace")
        assert onto.node_types == () and onto.edge_types == ()
        assert client.queries == []

    async def test_invalid_namespace_rejected(self):
        source, client = _graph_source_matching_fixture()
        with pytest.raises(ValueError):
            await source.load("bad namespace!")  # space + bang are invalid
        assert client.queries == []

    async def test_object_property_without_domain_range_has_no_edge_map(self):
        source, _ = _graph_source_matching_fixture()
        onto = await source.load("ns")
        assert "RELATED_TO" in onto.edge_types
        assert all(edge != "RELATED_TO" for edge, _, _ in onto.edge_map)


# ── Shape parity between the two sources (Req 3.6) ──────────────────


@pytest.mark.unit
class TestSourceShapeParity:
    async def test_file_and_graph_sources_produce_identical_ontology(self):
        """Both backends return the SAME Ontology shape from equivalent data (Req 3.6).

        Equality of the two frozen :class:`Ontology` instances covers node types,
        edge types, AND the directional source→target ``edge_map`` per edge type.
        """
        file_onto = await OntologyFileSource(FIXTURE_TTL).load("ns")
        graph_source, _ = _graph_source_matching_fixture()
        graph_onto = await graph_source.load("ns")

        assert isinstance(file_onto, Ontology) and isinstance(graph_onto, Ontology)
        assert file_onto == graph_onto
        # Spell out the directional-map parity the requirement calls out.
        assert file_onto.edge_map == graph_onto.edge_map


# ── Lazy-import invariant (Req 12.3) ───────────────────────────────


@pytest.mark.unit
class TestLazyImportInvariant:
    def test_importing_ontology_source_does_not_import_graphrag(self):
        """``import ...ontology.source`` must NOT import ``graphrag_toolkit``.

        Runs in a fresh subprocess (current ``sys.path`` propagated) so a
        ``graphrag_toolkit`` already imported by a sibling test cannot mask a
        regression (mirrors the task-1/6/7 invariant tests)."""
        code = (
            "import sys; "
            "import coa_serve.tier3.agentic.ontology.source; "
            "leaked = sorted(m for m in sys.modules if m == 'graphrag_toolkit' "
            "or m.startswith('graphrag_toolkit.')); "
            "assert not leaked, leaked; "
            "print('OK')"
        )
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        assert result.returncode == 0, (
            "importing ontology.source leaked graphrag_toolkit or failed.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "OK" in result.stdout
