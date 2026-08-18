# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""NeptuneDBGraphStore.store_classes_batch / store_properties_batch.

The batch methods project many classes/properties into the ontology graph in a
FEW chunked ``INSERT DATA`` calls instead of one HTTP round-trip per item (the
triple-loading optimization). These tests patch only ``_sparql_update`` so the
real triple emission is exercised, and assert:
  - batching collapses N items into far fewer SPARQL updates,
  - the batched triples are byte-identical to what store_class/store_property
    emit per-item (shared _class_triples/_property_triples helpers),
  - chunking splits on _INSERT_BATCH_TRIPLES / _INSERT_BATCH_BYTES without
    splitting a single class/property across INSERTs, and loses no triple,
  - isMapped + blank-node-skip semantics are preserved through the batch path.
"""

import logging
from collections import Counter
from unittest.mock import patch

import botocore.exceptions
import httpx
import pytest
from coa_ontology.stores.neptune_db_graph import NeptuneDBGraphStore

pytestmark = pytest.mark.unit

_ONT = "http://example.org/o#"


def _store() -> NeptuneDBGraphStore:
    return NeptuneDBGraphStore(endpoint="https://ndb.example:8182", namespace="ns-test")


def _capture(fn) -> list[str]:
    """Run *fn* with _sparql_update patched; return the list of SPARQL bodies."""
    with patch("coa_ontology.stores.neptune_db_graph._sparql_update") as upd:
        fn()
        return [call.args[0] for call in upd.call_args_list]


def _triples(bodies: list[str]) -> list[str]:
    """Extract the individual triple lines across all INSERT DATA bodies.

    Each body is ``INSERT DATA { GRAPH <g> {\\n  <triple> .\\n  ... }}``; a
    projected triple is any line ending in `` .`` (the GRAPH header and closing
    braces do not), so this recovers the full triple multiset independent of how
    it was chunked.
    """
    out: list[str] = []
    for body in bodies:
        out.extend(line.strip() for line in body.splitlines() if line.strip().endswith(" ."))
    return out


class TestStoreClassesBatch:
    def test_many_classes_collapse_to_one_update(self):
        store = _store()
        classes = [{"class_uri": f"{_ONT}C{i}", "labels": [f"C{i}"]} for i in range(50)]
        bodies = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=classes))
        # 50 classes → a single INSERT DATA, not 50 round-trips.
        assert len(bodies) == 1
        # Every class subject is present in the one body.
        for i in range(50):
            assert f"{_ONT}C{i}" in bodies[0]
        assert bodies[0].count("INSERT DATA") == 1

    def test_batch_triples_identical_to_per_item_store_class(self):
        store = _store()
        spec = {
            "class_uri": f"{_ONT}Orders",
            "labels": ["Orders"],
            "comments": ["An order"],
            "super_classes": [f"{_ONT}Doc"],
            "is_mapped": True,
        }
        # Per-item store_class body.
        single = _capture(lambda: store.store_class(ontology_uri=_ONT, **spec))
        # Batch body for the same single class.
        batch = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=[spec]))
        assert len(single) == 1 and len(batch) == 1
        # Same triples (INSERT DATA wrapper identical too — one class, one graph).
        assert single[0] == batch[0]

    def test_ismapped_preserved_in_batch(self):
        store = _store()
        classes = [
            {"class_uri": f"{_ONT}Mapped", "is_mapped": True},
            {"class_uri": f"{_ONT}Unmapped", "is_mapped": False},
        ]
        body = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=classes))[0]
        # Marker present for the mapped subject line, absent otherwise. The
        # isMapped predicate appears exactly once (only the mapped class).
        assert body.count("coa#isMapped") == 1
        assert '"true"^^' in body

    def test_blank_node_superclass_skipped_in_batch(self):
        store = _store()
        classes = [{"class_uri": f"{_ONT}C", "super_classes": ["_:b0", f"{_ONT}Parent"]}]
        body = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=classes))[0]
        # Named parent kept; blank node dropped (never passed to _iri).
        assert f"{_ONT}Parent" in body
        assert "_:b0" not in body

    def test_chunking_splits_without_losing_or_splitting_a_class(self):
        store = _store()
        # Each class emits 3 triples (type, definedBy, label). A triple budget of
        # 4 admits one class per chunk (adding a 2nd would hit 6 > 4) — so 3
        # classes → 3 INSERTs, and no class is split across a boundary.
        store._INSERT_BATCH_TRIPLES = 4
        classes = [{"class_uri": f"{_ONT}C{i}", "labels": [f"C{i}"]} for i in range(3)]
        chunked = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=classes))
        assert len(chunked) == 3  # split into multiple INSERTs, one class each

        # Every chunk holds a whole number of classes: a chunk that contains a
        # class's rdf:type triple must also contain that class's other triples,
        # i.e. no class straddles two INSERTs.
        for body in chunked:
            for i in range(3):
                subj = f"<{_ONT}C{i}>"
                if f"{subj} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>" in body:
                    assert body.count(f"{subj} ") == 3  # all 3 of this class's triples here

        # And the full triple multiset equals the un-chunked emission (nothing
        # dropped or duplicated at a boundary).
        store_big = _store()  # default large bounds → single INSERT
        unchunked = _capture(lambda: store_big.store_classes_batch(ontology_uri=_ONT, classes=classes))
        assert len(unchunked) == 1
        assert Counter(_triples(chunked)) == Counter(_triples(unchunked))

    def test_byte_budget_splits_chunks(self):
        store = _store()
        # A large comment makes each class's triples big; a small byte budget
        # must force a split even though the triple COUNT is well under 5000.
        store._INSERT_BATCH_BYTES = 500
        big = "x" * 400
        classes = [{"class_uri": f"{_ONT}C{i}", "comments": [big]} for i in range(3)]
        bodies = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=classes))
        assert len(bodies) > 1  # byte bound, not triple count, caused the split
        # No triple lost vs the single-INSERT emission.
        store_big = _store()
        one = _capture(lambda: store_big.store_classes_batch(ontology_uri=_ONT, classes=classes))
        assert Counter(_triples(bodies)) == Counter(_triples(one))

    def test_oversized_single_class_splits_across_inserts(self):
        store = _store()
        # A class whose OWN triples exceed the byte budget is split across
        # multiple INSERTs (not emitted whole) so it cannot exceed Neptune's
        # request-size cap. Budget of 10 bytes < any single triple, so each of
        # the class's triples lands in its own INSERT, and no triple is lost.
        store._INSERT_BATCH_BYTES = 10
        classes = [{"class_uri": f"{_ONT}Big", "labels": ["L1", "L2", "L3"]}]
        bodies = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=classes))
        assert len(bodies) > 1  # split, not one oversized INSERT
        # Same triple multiset as the un-split emission — nothing dropped.
        store_big = _store()
        one = _capture(lambda: store_big.store_classes_batch(ontology_uri=_ONT, classes=classes))
        assert Counter(_triples(bodies)) == Counter(_triples(one))

    def test_oversized_single_class_warns_splitting(self, caplog):
        store = _store()
        # The over-budget element still warns, but the message now says it is
        # being SPLIT (not emitted whole) to stay under Neptune's request limit.
        store._INSERT_BATCH_BYTES = 10
        classes = [{"class_uri": f"{_ONT}Big", "labels": ["L1", "L2", "L3"]}]
        with caplog.at_level(logging.WARNING, logger="coa_ontology.stores.neptune_db_graph"):
            _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=classes))
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        # The element-level "splitting" warning fires (per-triple warnings may
        # also fire since each triple exceeds the tiny 10-byte budget).
        assert any("splitting it across multiple INSERTs" in r.getMessage() for r in warnings)

    def test_flush_error_names_chunk_shape(self):
        # A failed INSERT flush must surface the chunk's triple count + byte size
        # (not a bare transport error), so a mid-batch failure says which INSERT
        # died. httpx transport errors are wrapped; default bounds → one INSERT
        # for a handful of classes.
        store = _store()
        classes = [{"class_uri": f"{_ONT}C{i}", "labels": [f"C{i}"]} for i in range(3)]
        with (
            patch(
                "coa_ontology.stores.neptune_db_graph._sparql_update",
                side_effect=httpx.ConnectError("neptune unreachable"),
            ),
            pytest.raises(RuntimeError, match=r"INSERT flush failed \(\d+ triples, \d+ bytes\)"),
        ):
            store.store_classes_batch(ontology_uri=_ONT, classes=classes)

    def test_credential_error_names_chunk_shape(self):
        # A SigV4/credential failure out of _sign is a BotoCoreError, not an
        # HTTPError — it must still get the chunk-context wrap instead of escaping
        # bare, so a mid-batch auth failure still names which INSERT died.
        store = _store()
        classes = [{"class_uri": f"{_ONT}C{i}", "labels": [f"C{i}"]} for i in range(3)]
        with (
            patch(
                "coa_ontology.stores.neptune_db_graph._sparql_update",
                side_effect=botocore.exceptions.NoCredentialsError(),
            ),
            pytest.raises(RuntimeError, match=r"INSERT flush failed \(\d+ triples, \d+ bytes\)"),
        ):
            store.store_classes_batch(ontology_uri=_ONT, classes=classes)

    def test_later_chunk_failure_leaves_earlier_chunks_whole(self):
        # Atomicity guarantee: a group is never split across INSERTs, so if a
        # later chunk's _sparql_update raises, the classes already flushed in the
        # earlier INSERT went out complete (all their triples, incl. isMapped) —
        # never half-projected. Force one class per chunk, fail on the 2nd INSERT.
        store = _store()
        store._INSERT_BATCH_TRIPLES = 4  # 3 triples/class → one class per chunk
        classes = [
            {"class_uri": f"{_ONT}C0", "labels": ["C0"], "is_mapped": True},
            {"class_uri": f"{_ONT}C1", "labels": ["C1"], "is_mapped": True},
        ]
        emitted: list[str] = []

        def _fail_on_second(body):
            emitted.append(body)
            if len(emitted) == 2:
                raise RuntimeError("boom on chunk 2")

        with (
            patch("coa_ontology.stores.neptune_db_graph._sparql_update", side_effect=_fail_on_second),
            pytest.raises(RuntimeError, match="boom on chunk 2"),
        ):
            store.store_classes_batch(ontology_uri=_ONT, classes=classes)
        # First INSERT was attempted and is a COMPLETE class projection: C0's
        # type, definedBy, isMapped marker and label are all in the one body that
        # went out before the failure — the failure can't have split it.
        assert len(emitted) == 2
        first = emitted[0]
        assert f"<{_ONT}C0>" in first and f"<{_ONT}C1>" not in first
        assert first.count(f"<{_ONT}C0> ") == 4  # type + definedBy + isMapped + label
        assert "coa#isMapped" in first

    def test_empty_batch_is_noop(self):
        store = _store()
        bodies = _capture(lambda: store.store_classes_batch(ontology_uri=_ONT, classes=[]))
        assert bodies == []


class TestStorePropertiesBatch:
    def test_many_properties_collapse_to_one_update(self):
        store = _store()
        props = [{"prop_uri": f"{_ONT}p{i}", "label": f"p{i}"} for i in range(30)]
        bodies = _capture(lambda: store.store_properties_batch(ontology_uri=_ONT, properties=props))
        assert len(bodies) == 1
        for i in range(30):
            assert f"{_ONT}p{i}" in bodies[0]

    def test_batch_triples_identical_to_per_item_store_property(self):
        store = _store()
        spec = {
            "prop_uri": f"{_ONT}hasOrder",
            "label": "has order",
            "comment": "links to order",
            "domains": [f"{_ONT}Customer"],
            "ranges": [f"{_ONT}Order"],
        }
        single = _capture(lambda: store.store_property(ontology_uri=_ONT, **spec))
        batch = _capture(lambda: store.store_properties_batch(ontology_uri=_ONT, properties=[spec]))
        assert len(single) == 1 and len(batch) == 1
        assert single[0] == batch[0]

    def test_blank_node_domain_range_skipped_in_batch(self):
        store = _store()
        props = [{"prop_uri": f"{_ONT}p", "domains": ["_:b0", f"{_ONT}C"], "ranges": ["_:b1", f"{_ONT}D"]}]
        body = _capture(lambda: store.store_properties_batch(ontology_uri=_ONT, properties=props))[0]
        # Named domain/range kept; blank nodes dropped (never passed to _iri).
        assert f"{_ONT}C" in body and f"{_ONT}D" in body
        assert "_:b0" not in body and "_:b1" not in body

    def test_byte_budget_splits_property_chunks(self):
        # store_properties_batch shares _flush_triple_groups with the class side,
        # but guard the property path directly: a small byte budget must split the
        # INSERTs (not the triple count), and lose no triple vs the single-INSERT
        # emission. Fails if the flush logic is ever forked per-type.
        store = _store()
        store._INSERT_BATCH_BYTES = 500
        big = "x" * 400
        props = [{"prop_uri": f"{_ONT}p{i}", "comment": big} for i in range(3)]
        bodies = _capture(lambda: store.store_properties_batch(ontology_uri=_ONT, properties=props))
        assert len(bodies) > 1  # byte bound, not triple count, caused the split
        store_big = _store()
        one = _capture(lambda: store_big.store_properties_batch(ontology_uri=_ONT, properties=props))
        assert Counter(_triples(bodies)) == Counter(_triples(one))

    def test_empty_batch_is_noop(self):
        store = _store()
        bodies = _capture(lambda: store.store_properties_batch(ontology_uri=_ONT, properties=[]))
        assert bodies == []
