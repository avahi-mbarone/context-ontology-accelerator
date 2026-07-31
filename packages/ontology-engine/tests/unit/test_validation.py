# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ontology-validation validators (excluding OoPS)."""

import pytest
from coa_ontology.validation.validators.tier1 import ConnectivityValidator, TaxonomyCycleValidator
from coa_ontology.validation.validators.tier2 import StructuralMetricsValidator
from coa_ontology.validation.validators.tier3 import AmbiguousMatchValidator, LabelCompletenessValidator
from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SKOS

pytestmark = pytest.mark.unit


def _g(*triples):
    g = Graph()
    for t in triples:
        g.add(t)
    return g


EX = Namespace("http://ex.org/")


# ── TaxonomyCycleValidator ──


def test_cycle_none():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.B, RDF.type, OWL.Class),
        (EX.B, RDFS.subClassOf, EX.A),
    )
    findings = TaxonomyCycleValidator().validate(g)
    assert all(f.code != "TAXONOMY_CYCLE" for f in findings)


def test_cycle_detected():
    g = _g(
        (EX.A, RDFS.subClassOf, EX.B),
        (EX.B, RDFS.subClassOf, EX.A),
    )
    findings = TaxonomyCycleValidator().validate(g)
    assert any(f.code == "TAXONOMY_CYCLE" for f in findings)


# ── ConnectivityValidator ──


def test_connected():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.B, RDF.type, OWL.Class),
        (EX.B, RDFS.subClassOf, EX.A),
    )
    findings = ConnectivityValidator().validate(g)
    assert any(f.code == "CONNECTED" for f in findings)


def test_disconnected():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.B, RDF.type, OWL.Class),
        (EX.C, RDF.type, OWL.Class),
        (EX.B, RDFS.subClassOf, EX.A),
    )
    findings = ConnectivityValidator().validate(g)
    assert any(f.code == "DISCONNECTED_CLASSES" for f in findings)


def test_connected_via_object_property():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.B, RDF.type, OWL.Class),
        (EX.p, RDF.type, OWL.ObjectProperty),
        (EX.p, RDFS.domain, EX.A),
        (EX.p, RDFS.range, EX.B),
    )
    findings = ConnectivityValidator().validate(g)
    assert any(f.code == "CONNECTED" for f in findings)


# ── StructuralMetricsValidator ──


def test_structural_metrics():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.B, RDF.type, OWL.Class),
        (EX.B, RDFS.subClassOf, EX.A),
        (EX.p, RDF.type, OWL.ObjectProperty),
        (EX.q, RDF.type, OWL.DatatypeProperty),
    )
    metrics_out = {}
    StructuralMetricsValidator().validate(g, _metrics_out=metrics_out)
    assert metrics_out["class_count"] == 2
    assert metrics_out["object_property_count"] == 1
    assert metrics_out["datatype_property_count"] == 1
    assert metrics_out["max_depth"] == 1
    assert metrics_out["inheritance_richness"] == 0.5


def test_structural_metrics_empty():
    g = Graph()
    metrics_out = {}
    StructuralMetricsValidator().validate(g, _metrics_out=metrics_out)
    assert metrics_out["class_count"] == 0


# ── LabelCompletenessValidator ──


def test_label_complete():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.A, RDFS.label, Literal("A")),
        (EX.A, RDFS.comment, Literal("Class A")),
    )
    findings = LabelCompletenessValidator().validate(g)
    assert not findings


def test_label_missing():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
    )
    findings = LabelCompletenessValidator().validate(g)
    codes = [f.code for f in findings]
    assert "MISSING_LABEL" in codes
    assert "MISSING_COMMENT" in codes


# ── AmbiguousMatchValidator ──


def test_ambiguous_match_flagged():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.A, SKOS.relatedMatch, URIRef("http://schema.org/Thing")),
        (EX.A, URIRef("http://ex.org/matchConfidence"), Literal(0.55, datatype=XSD.float)),
    )
    findings = AmbiguousMatchValidator().validate(g)
    assert len(findings) == 1
    assert findings[0].code == "AMBIGUOUS_MATCH"
    assert abs(findings[0].details["confidence"] - 0.55) < 0.01


def test_no_ambiguous_matches():
    g = _g(
        (EX.A, RDF.type, OWL.Class),
        (EX.A, SKOS.exactMatch, URIRef("http://schema.org/Product")),
    )
    findings = AmbiguousMatchValidator().validate(g)
    assert not findings
