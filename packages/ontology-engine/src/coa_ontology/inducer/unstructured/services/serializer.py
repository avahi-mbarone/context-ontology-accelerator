# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Turtle serialization for the unstructured induction pipeline.

This module is the **terminal stage** of the unstructured induction
pipeline (Task 14, Requirement 17). It accepts the merged
:class:`rdflib.Graph` produced by Rules 1–5 (and optionally the
entailment engine) and emits:

1. A standalone Turtle string suitable for storage as a versioned
   artifact.
2. The same content as an :class:`rdflib.Graph` instance, with all
   prefixes bound and the ``owl:Ontology`` declaration added.

The function guarantees a **round-trip isomorphism** check
(Req 17.4): the Turtle output, when re-parsed, is structurally
identical to the input graph (modulo blank-node renaming).

Inputs
------

The pipeline orchestrator (Task 16) merges per-rule graphs into a
single graph before calling this serializer. So this module's input
is always one fully-merged graph; it does NOT know or care which
rules ran. That decoupling is intentional — the serializer is a
pure I/O primitive.

The function takes:

- ``graph``: the merged :class:`rdflib.Graph`. If empty, the function
  still emits a valid Turtle file (just the prefix declarations and
  the ``owl:Ontology`` declaration block).
- ``namespace_name``: the local name of the namespace (e.g.
  ``"my-graph"``). Used as the ``rdfs:label`` on the ``owl:Ontology``
  declaration and as the prefix string for the custom namespace.
- ``namespace_iri``: the base IRI of the ontology. The
  ``owl:Ontology`` subject IRI is this string with any trailing
  ``/`` or ``#`` stripped — matching the convention used in the
  structured induction code.
- ``timestamp``: a :class:`datetime.datetime` for the run. Tagged
  with UTC (Req 17.3 specifies ``"YYYY-MM-DDTHH:MM:SSZ"``); naive
  inputs are assumed UTC. Used for ``owl:versionInfo`` (string) and
  ``dcterms:created`` (xsd:dateTime).

Outputs
-------

The function returns a tuple ``(turtle_string, graph)``:

- ``turtle_string``: UTF-8 encoded Turtle. Capped at 50 MB
  (Req 17.5) — if the graph would produce a larger output, the
  function raises :class:`ValueError` rather than silently
  truncating.
- ``graph``: the input graph **with** the ``owl:Ontology`` declaration
  block added and all prefixes bound. The caller may persist this
  Graph directly (e.g. into a triplestore) or re-serialize.

Determinism
-----------

The Turtle byte stream is **not** byte-stable across runs (rdflib
applies its own ordering, which can vary). The semantic content is
stable and can be compared via :func:`rdflib.compare.isomorphic`.

Round-trip verification
-----------------------

After serialization the function parses the Turtle back into a
fresh Graph and asserts isomorphism with the augmented input
(Req 17.4). On mismatch the function raises :class:`RuntimeError`
— this would be a serializer bug worth crashing on. The
verification cost is one rdflib parse pass, which is O(triples)
and bounded by the 50 MB cap.

Usage
-----

::

    from datetime import datetime, timezone
    from coa_ontology.inducer.unstructured.services.serializer import (
        serialize,
    )

    turtle, augmented_graph = serialize(
        graph=merged_rdflib_graph,
        namespace_name="my-graph",
        namespace_iri="http://coa.amazon.com/namespace/my-graph/ontology/my-onto/",
        timestamp=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS, PROV, SKOS

log = logging.getLogger(__name__)


# Hard cap on the serialized size (Req 17.5). 50 MB is generous for
# a single ontology — even the dev graph's full induced output is
# only a few MB. A run that overflows this cap is almost certainly
# a bug (e.g. accidental A-Box dump).
_MAX_TURTLE_BYTES = 50 * 1024 * 1024


def serialize(
    graph: Graph,
    namespace_name: str,
    namespace_iri: str,
    timestamp: datetime,
) -> tuple[str, Graph]:
    """Serialize the induced ontology graph as Turtle.

    Implements Requirement 17. Binds the standard prefixes, adds the
    ``owl:Ontology`` declaration block, serializes via rdflib, and
    verifies round-trip isomorphism.

    Args:
        graph: The merged :class:`rdflib.Graph` produced by the
            induction rules. May be empty; in that case the output is
            a valid Turtle file containing only the prefix
            declarations and the ``owl:Ontology`` block. The function
            mutates this graph in place (binds prefixes, adds the
            ontology block); pass a copy if you need the original
            untouched.
        namespace_name: The local name of the namespace (e.g.
            ``"my-graph"``). Used for ``rdfs:label`` on the
            ``owl:Ontology`` declaration and as the prefix string for
            the custom namespace binding.
        namespace_iri: The base IRI of the ontology. Trailing ``/``
            or ``#`` is stripped before use as the ``owl:Ontology``
            subject IRI.
        timestamp: The pipeline run timestamp. Naive datetimes are
            assumed UTC; aware datetimes are converted to UTC.

    Returns:
        A 2-tuple ``(turtle_string, graph)``:

        - ``turtle_string`` is a UTF-8 encoded Turtle representation,
          ≤ 50 MB.
        - ``graph`` is the augmented graph (input graph plus the
          ``owl:Ontology`` declaration and all prefixes bound). The
          caller may use this directly or re-serialize.

    Raises:
        ValueError: If ``namespace_name`` or ``namespace_iri`` is
            empty, or if the serialized Turtle exceeds the 50 MB cap.
        RuntimeError: If the Turtle output fails to round-trip
            (parsed-back graph is not isomorphic to the augmented
            input). This indicates a serializer bug; the function
            does not silently swallow it.
    """
    if not namespace_name:
        raise ValueError("serialize: namespace_name is required")
    if not namespace_iri:
        raise ValueError("serialize: namespace_iri is required")

    # Normalize timestamp to UTC. Req 17.3 specifies the
    # ``"YYYY-MM-DDTHH:MM:SSZ"`` form; we always emit UTC with the
    # ``Z`` suffix, regardless of the caller's timezone.
    ts_utc = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
    ts_iso_z = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Strip the trailing ``/`` or ``#`` for the ontology subject IRI
    # — matches the structured induction convention (see
    # ``inducer/services/pipeline.py:_init_graph``). The serialized
    # IRI in Turtle will look like ``<base>`` rather than ``<base/>``.
    ontology_subject_iri = namespace_iri.rstrip("/").rstrip("#")
    ontology_uri = URIRef(ontology_subject_iri)

    # Bind standard prefixes. ``override=True`` ensures that even if
    # the input graph already has conflicting bindings, our canonical
    # set wins for serialization.
    _bind_standard_prefixes(graph, namespace_name, namespace_iri)

    # Req 17.3 — owl:Ontology declaration block. The function is
    # idempotent: if the caller already added an owl:Ontology
    # declaration, we replace its annotations with the canonical set
    # rather than emitting a duplicate.
    _add_ontology_declaration(
        graph,
        ontology_uri=ontology_uri,
        namespace_name=namespace_name,
        timestamp_iso_z=ts_iso_z,
    )

    # Req 17.1 — serialize via rdflib's Turtle serializer.
    turtle_str = graph.serialize(format="turtle")

    # Req 17.5 — enforce the 50 MB cap. We measure the UTF-8 byte
    # length, not the string length, since the cap is on the wire
    # size of the artifact.
    byte_len = len(turtle_str.encode("utf-8"))
    if byte_len > _MAX_TURTLE_BYTES:
        raise ValueError(
            f"serialize: serialized Turtle exceeds 50 MB cap "
            f"(actual size = {byte_len} bytes; limit = "
            f"{_MAX_TURTLE_BYTES} bytes). Reduce the input graph "
            f"size (e.g. disable include_individuals) before "
            f"retrying."
        )

    # Req 17.4 — round-trip isomorphism check.
    reparsed = Graph()
    reparsed.parse(data=turtle_str, format="turtle")
    if not isomorphic(graph, reparsed):
        raise RuntimeError(
            "serialize: round-trip isomorphism check failed — the "
            "parsed-back graph is not isomorphic to the original. "
            "This indicates a serializer bug; please open an issue "
            "with the failing input graph."
        )

    log.info(
        "serialize: emitted %d bytes of Turtle (%d triples, %d namespace prefixes bound)",
        byte_len,
        len(graph),
        sum(1 for _ in graph.namespaces()),
    )

    return turtle_str, graph


def _bind_standard_prefixes(graph: Graph, namespace_name: str, namespace_iri: str) -> None:
    """Bind the canonical set of prefixes on ``graph`` (Req 17.2).

    The bindings are:

    - ``owl``  → http://www.w3.org/2002/07/owl#
    - ``rdf``  → http://www.w3.org/1999/02/22-rdf-syntax-ns#
    - ``rdfs`` → http://www.w3.org/2000/01/rdf-schema#
    - ``xsd``  → http://www.w3.org/2001/XMLSchema#
    - ``skos`` → http://www.w3.org/2004/02/skos/core#
    - ``dcterms`` → http://purl.org/dc/terms/
    - ``prov`` → http://www.w3.org/ns/prov#
    - ``<namespace_name lowercased>`` → ``<namespace_iri>``

    All bindings use ``override=True`` so they win against any prior
    bindings on the input graph.
    """
    graph.bind("owl", OWL, override=True)
    graph.bind("rdf", RDF, override=True)
    graph.bind("rdfs", RDFS, override=True)
    graph.bind("xsd", XSD, override=True)
    graph.bind("skos", SKOS, override=True)
    graph.bind("dcterms", DCTERMS, override=True)
    graph.bind("prov", PROV, override=True)

    # The custom prefix is the namespace name, lowercased. The
    # bound IRI ends with the same separator the caller passed in
    # (we don't strip ``/``/``#`` here — that's only for the
    # owl:Ontology subject IRI). This way the resulting Turtle uses
    # the prefix consistently with how IRIs are minted upstream.
    custom_prefix = namespace_name.lower()
    graph.bind(custom_prefix, Namespace(namespace_iri), override=True)


def _add_ontology_declaration(
    graph: Graph,
    ontology_uri: URIRef,
    namespace_name: str,
    timestamp_iso_z: str,
) -> None:
    """Add (or refresh) the ``owl:Ontology`` declaration block (Req 17.3).

    Always idempotent: the function first removes any prior
    ``rdfs:label``, ``owl:versionInfo``, and ``dcterms:created``
    triples on this subject, then re-adds the canonical set. The
    ``rdf:type owl:Ontology`` triple is added once (set semantics
    make a duplicate a no-op).

    The ``owl:versionInfo`` triple uses a plain Literal (no
    datatype) per the convention in the structured induction code.
    The ``dcterms:created`` triple uses ``xsd:dateTime``, which is
    the standard datatype for date-time literals.
    """
    # Req 17.3 — exactly one owl:Ontology declaration. The set
    # semantics of rdflib mean adding the same triple twice is a
    # no-op; we don't need to check.
    graph.add((ontology_uri, RDF.type, OWL.Ontology))

    # Replace any prior annotation triples on this subject so the
    # serializer is idempotent (calling serialize twice on the same
    # graph does not duplicate annotations).
    graph.remove((ontology_uri, RDFS.label, None))
    graph.remove((ontology_uri, OWL.versionInfo, None))
    graph.remove((ontology_uri, DCTERMS.created, None))

    # rdfs:label — namespace name as a plain string literal. The
    # Req 17.3 wording says "set to the namespace name" without
    # specifying datatype; we use xsd:string for consistency with
    # all the other rdfs:label triples emitted by Rules 1–5.
    graph.add((ontology_uri, RDFS.label, Literal(namespace_name, datatype=XSD.string)))

    # owl:versionInfo — Req 17.3 specifies a plain string literal of
    # form "YYYY-MM-DDTHH:MM:SSZ". Note the explicit lack of
    # datatype: owl:versionInfo's range is rdfs:Literal, and the
    # convention in the OWL community is plain strings.
    graph.add((ontology_uri, OWL.versionInfo, Literal(timestamp_iso_z)))

    # dcterms:created — Req 17.3 specifies xsd:dateTime literal of
    # the same timestamp.
    graph.add(
        (
            ontology_uri,
            DCTERMS.created,
            Literal(timestamp_iso_z, datatype=XSD.dateTime),
        )
    )
