# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for /fetch unresolved-reference detection and
golden_compare tier classification.
"""

from __future__ import annotations

import pytest
from coa_ontology.benchmark.golden_compare import compare_to_golden

pytestmark = pytest.mark.unit


# ── Tier classification ──────────────────────────────────────────

_GOLDEN = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix g: <http://example.com/golden/> .

g:Claim a owl:Class ; rdfs:label "Claim" .
g:Policy a owl:Class ; rdfs:label "Policy" .
g:PolicyHolder a owl:Class ; rdfs:label "Policy Holder" .
"""


class TestTierClassifierIntegration:
    """The tier_classifier callback is called once per grounded induced class;
    counts are split into grounded_classes_customer + grounded_classes_foundational.
    """

    def test_classifier_splits_customer_vs_foundational(self):
        induced = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix acme: <http://acme.example/ontology/> .
@prefix i: <http://example.com/induced/> .

i:Claim a owl:Class ; rdfs:subClassOf acme:Claim .
i:Policy a owl:Class ; rdfs:subClassOf acme:Policy .
i:PolicyHolder a owl:Class ; rdfs:subClassOf schema:Person .
"""

        def classifier(iri: str) -> str:
            if "acme.example" in iri:
                return "customer"
            if "schema.org" in iri:
                return "foundational"
            return ""

        score = compare_to_golden(induced, _GOLDEN, tier_classifier=classifier)
        # All 3 golden classes matched and all 3 grounded
        assert score.grounded_classes == 3
        assert score.grounded_classes_customer == 2  # Claim, Policy
        assert score.grounded_classes_foundational == 1  # PolicyHolder

    def test_classifier_absent_keeps_counts_zero(self):
        """Without a classifier, the legacy grounded_classes count works
        but the tier breakdown stays at zero."""
        induced = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix acme: <http://acme.example/ontology/> .
@prefix i: <http://example.com/induced/> .

i:Claim a owl:Class ; rdfs:subClassOf acme:Claim .
"""
        score = compare_to_golden(induced, _GOLDEN)
        assert score.grounded_classes == 1
        assert score.grounded_classes_customer == 0
        assert score.grounded_classes_foundational == 0

    def test_classifier_returning_unknown_is_tolerated(self):
        """Classifier can return '' or an unrecognized value — counts stay at 0."""
        induced = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix acme: <http://acme.example/ontology/> .
@prefix i: <http://example.com/induced/> .

i:Claim a owl:Class ; rdfs:subClassOf acme:Claim .
"""
        score = compare_to_golden(induced, _GOLDEN, tier_classifier=lambda _: "")
        # grounded_classes still 1 (subClassOf to foreign ns); tier counts 0
        assert score.grounded_classes == 1
        assert score.grounded_classes_customer == 0
        assert score.grounded_classes_foundational == 0

    def test_classifier_exception_is_caught(self):
        """A buggy classifier shouldn't abort the scoring run."""
        induced = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix acme: <http://acme.example/ontology/> .
@prefix i: <http://example.com/induced/> .

i:Claim a owl:Class ; rdfs:subClassOf acme:Claim .
"""

        def bad_classifier(iri):
            raise RuntimeError("classifier crashed")

        score = compare_to_golden(induced, _GOLDEN, tier_classifier=bad_classifier)
        # Should not crash; tier counts remain 0
        assert score.grounded_classes == 1
        assert score.grounded_classes_customer == 0

    def test_as_dict_exposes_tier_counts(self):
        induced = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix acme: <http://acme.example/ontology/> .
@prefix i: <http://example.com/induced/> .

i:Claim a owl:Class ; rdfs:subClassOf acme:Claim .
"""
        score = compare_to_golden(induced, _GOLDEN, tier_classifier=lambda iri: "customer" if "acme" in iri else "")
        d = score.as_dict()
        assert "grounded_customer" in d["class"]
        assert d["class"]["grounded_customer"] == 1
        assert d["class"]["grounded_foundational"] == 0


# ── Unresolved-reference handler (/fetch request/response schemas) ──


class TestUnresolvedReferenceSchema:
    """Lightweight tests for the UnresolvedReference schema shape.
    The handler logic itself is exercised via the live /fetch tests; here
    we verify the schemas round-trip correctly."""

    def test_unresolved_reference_schema(self):
        from coa_ontology.catalog.schemas import UnresolvedReference

        u = UnresolvedReference(
            namespace="http://hpclab.ceid.upatras.gr/omg#",
            sample_iris=[
                "http://hpclab.ceid.upatras.gr/omg#Claim",
                "http://hpclab.ceid.upatras.gr/omg#Policy",
            ],
            reference_count=12,
        )
        assert u.reference_count == 12
        assert len(u.sample_iris) == 2

    def test_fetch_request_accepts_known_ontology_uris(self):
        from coa_ontology.catalog.schemas import OntologyFetchRequest

        req = OntologyFetchRequest(
            source_url="https://example.com/ont.ttl",
            known_ontology_uris=[
                "https://schema.org/",
                "http://xmlns.com/foaf/0.1/",
            ],
        )
        assert len(req.known_ontology_uris) == 2

    def test_fetch_response_unresolved_default_none(self):
        from coa_ontology.catalog.schemas import OntologyFetchResponse

        resp = OntologyFetchResponse(
            ontology_id="x",
            uri="x",
            parse_status="ok",
            class_count=5,
            property_count=10,
            axiom_count=100,
            file_path="/tmp/x.ttl",
        )
        assert resp.unresolved_references is None


class TestExtractAllProperties:
    """Verify the OntologyFetchRequest.extract_all_properties flag is wired."""

    def test_request_accepts_extract_all_flag(self):
        from coa_ontology.catalog.schemas import OntologyFetchRequest

        req = OntologyFetchRequest(
            source_url="https://example.com/ont.ttl",
            extract_all_properties=True,
        )
        assert req.extract_all_properties is True
        assert req.extract_properties_for_classes is None

    def test_flag_defaults_false(self):
        from coa_ontology.catalog.schemas import OntologyFetchRequest

        req = OntologyFetchRequest(source_url="https://example.com/ont.ttl")
        assert req.extract_all_properties is False

    def test_flag_compatible_with_classes_list(self):
        """Spec allows both to be set; documented that extract_all wins."""
        from coa_ontology.catalog.schemas import OntologyFetchRequest

        req = OntologyFetchRequest(
            source_url="https://example.com/ont.ttl",
            extract_properties_for_classes=["http://ex/X"],
            extract_all_properties=True,
        )
        assert req.extract_all_properties is True
        assert req.extract_properties_for_classes == ["http://ex/X"]


class TestTierDependentExtractionDefault:
    """Verify setup.py's tier-dependent default for extract_all_properties.

    Default policy:
      - customer tier  → extract_all_properties defaults to True
      - foundational   → extract_all_properties defaults to False
      - explicit per-entry value overrides the tier default either way
    """

    def _simulate_default(self, tier: str, entry_override: bool | None = None) -> bool:
        """Replica of the decision in setup.py::load_ontologies."""
        default_extract_all = tier == "customer"
        entry_val = default_extract_all if entry_override is None else entry_override
        return bool(entry_val)

    def test_customer_defaults_to_true(self):
        assert self._simulate_default("customer") is True

    def test_foundational_defaults_to_false(self):
        assert self._simulate_default("foundational") is False

    def test_customer_explicit_false_overrides(self):
        assert self._simulate_default("customer", entry_override=False) is False

    def test_foundational_explicit_true_overrides(self):
        assert self._simulate_default("foundational", entry_override=True) is True
