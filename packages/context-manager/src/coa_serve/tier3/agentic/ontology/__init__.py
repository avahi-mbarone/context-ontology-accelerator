# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tier 3 — Agentic Retriever ontology-source abstraction.

The Ontology_Lookup_Tool resolves the determined ontology for a Namespace —
node types, edge types, and the directional source→target mapping per edge type
(Req 3.1) — through a configurable :class:`OntologySource`. Two backends are
provided and return the ontology in the SAME shape (Req 3.6):

- :class:`OntologyGraphSource` — production default; resolves the ontology by
  querying the **RDF ontology graph** with SPARQL over the
  ``urn:orion:{namespace}:published`` named graph via the existing serve-layer
  graph client.
- :class:`OntologyFileSource` — test-oriented; parses a serialized ``.ttl``
  Turtle file with rdflib into the same :class:`Ontology`.

Import discipline (Requirement 12.3): module load of this subpackage MUST NOT
import ``graphrag_toolkit``. The ontology graph is RDF/SPARQL — it never touches
the graphrag-toolkit property graph — and ``rdflib`` (used only by the file
source) is imported lazily inside :meth:`OntologyFileSource.load`, so importing
this package stays cheap and toolkit-free.
"""

from __future__ import annotations

from .source import (
    Ontology,
    OntologyFileSource,
    OntologyGraphSource,
    OntologySource,
)

__all__ = [
    "Ontology",
    "OntologySource",
    "OntologyGraphSource",
    "OntologyFileSource",
]
