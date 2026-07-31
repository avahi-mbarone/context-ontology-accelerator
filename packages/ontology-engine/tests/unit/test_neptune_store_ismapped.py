# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""NeptuneDBGraphStore.store_class emits the coa:isMapped marker correctly.

This exercises the REAL store_class SPARQL emission (only the network call
``_sparql_update`` is patched), so the exact INSERT DATA triple — including the
coa:isMapped IRI and the ``"true"^^xsd:boolean`` literal the serve T-Box filter
matches against — is verified. Everything else in the pipeline mocks store_class,
so without this the actual triple syntax would be untested until deploy.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from coa_common.constants import GRAPH_BASE_URI

pytestmark = pytest.mark.unit

from coa_ontology.stores.neptune_db_graph import NeptuneDBGraphStore

_ISMAPPED_IRI = f"{GRAPH_BASE_URI}/vocab/coa#isMapped"
_XSD_BOOL = "http://www.w3.org/2001/XMLSchema#boolean"


def _capture_store_class(*, is_mapped: bool) -> str:
    """Run the real store_class with _sparql_update patched; return the SPARQL."""
    store = NeptuneDBGraphStore(endpoint="https://ndb.example:8182", namespace="ns-test")
    with patch("coa_ontology.stores.neptune_db_graph._sparql_update") as upd:
        store.store_class(
            ontology_uri="http://example.org/o#",
            class_uri="http://example.org/o#Orders",
            labels=["Orders"],
            is_mapped=is_mapped,
        )
        assert upd.call_count == 1, "store_class must issue exactly one SPARQL update"
        return upd.call_args[0][0]


class TestStoreClassIsMappedEmission:
    def test_mapped_class_emits_ismapped_boolean_triple(self):
        sparql = _capture_store_class(is_mapped=True)
        # The exact triple the serve filter (?class <scl#isMapped> true) matches.
        assert _ISMAPPED_IRI in sparql
        assert f'"true"^^<{_XSD_BOOL}>' in sparql
        # Sanity: it's inside an INSERT DATA and carries the class as subject.
        assert "INSERT DATA" in sparql
        assert "http://example.org/o#Orders" in sparql

    def test_unmapped_class_omits_ismapped_triple(self):
        sparql = _capture_store_class(is_mapped=False)
        # Absent marker == unmapped == hidden by the serve filter. No isMapped
        # triple, and definitely no "false" (we never emit a negative).
        assert _ISMAPPED_IRI not in sparql
        # Class is still stored as an owl:Class (just without the marker).
        assert "http://example.org/o#Orders" in sparql
        assert "2002/07/owl#Class" in sparql

    def test_written_triple_matches_serve_filter_pattern_via_rdflib(self):
        """Round-trip: the literal store_class WRITES must satisfy the term the
        serve T-Box filter QUERIES (``?class <scl#isMapped> true``).

        The write side emits ``"true"^^xsd:boolean``; the read side uses the
        SPARQL keyword ``true``. This asserts, via rdflib, that they are the
        SAME term — so the real Neptune write→read actually matches (the one
        thing mocks can't prove short of a live cluster)."""
        import re

        from rdflib import Graph

        # Pull the ACTUAL isMapped triple line store_class emitted (not a
        # hand-written copy), load it into rdflib, and confirm the serve filter's
        # `true` keyword matches the written "true"^^xsd:boolean term.
        sparql = _capture_store_class(is_mapped=True)
        m = re.search(rf"(\S+\s+<{re.escape(_ISMAPPED_IRI)}>\s+\S+\s*\.)", sparql)
        assert m, f"could not find the isMapped triple in emitted SPARQL:\n{sparql}"
        triple = m.group(1)

        g = Graph()
        g.parse(data=triple, format="turtle")
        ask = g.query(f"ASK {{ ?c <{_ISMAPPED_IRI}> true }}")
        assert bool(ask), (
            f"serve filter `<isMapped> true` must match the boolean literal store_class actually wrote: {triple!r}"
        )
