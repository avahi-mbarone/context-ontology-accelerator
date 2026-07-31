# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for turtle_export.format_grouped_turtle."""

import pytest
from coa_ontology.catalog.turtle_export import format_grouped_turtle

SAMPLE_TURTLE = """\
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.org/onto#> a owl:Ontology ;
    rdfs:label "Test Ontology" .

<https://example.org/onto#Customer> a owl:Class ;
    rdfs:label "Customer" .

<https://example.org/onto#Policy> a owl:Class ;
    rdfs:label "Policy" .

<https://example.org/onto#customer_name> a rdf:Property , owl:DatatypeProperty ;
    rdfs:label "Name" ;
    rdfs:domain <https://example.org/onto#Customer> ;
    rdfs:range xsd:string .

<https://example.org/onto#customer_policy> a rdf:Property , owl:ObjectProperty ;
    rdfs:label "Has Policy" ;
    rdfs:domain <https://example.org/onto#Customer> ;
    rdfs:range <https://example.org/onto#Policy> .
"""


@pytest.mark.unit
class TestFormatGroupedTurtle:
    def test_groups_by_type(self):
        result = format_grouped_turtle(SAMPLE_TURTLE)
        # Should have section headers
        assert "# ── Ontology" in result
        assert "# ── Classes" in result
        assert "# ── Object properties" in result
        assert "# ── Datatype properties" in result

    def test_binds_ontology_prefix(self):
        result = format_grouped_turtle(SAMPLE_TURTLE)
        # The ontology namespace should be bound as the empty prefix
        assert "@prefix : <https://example.org/onto#>" in result

    def test_uses_short_prefixes(self):
        result = format_grouped_turtle(SAMPLE_TURTLE)
        # Classes should use the short prefix form
        assert ":Customer" in result
        assert ":Policy" in result

    def test_classes_before_properties(self):
        result = format_grouped_turtle(SAMPLE_TURTLE)
        classes_pos = result.index("# ── Classes")
        obj_pos = result.index("# ── Object properties")
        dt_pos = result.index("# ── Datatype properties")
        assert classes_pos < obj_pos < dt_pos

    def test_preserves_all_triples(self):
        result = format_grouped_turtle(SAMPLE_TURTLE)
        # Key content should survive the reformat
        assert "Customer" in result
        assert "Policy" in result
        assert "Has Policy" in result
        assert "Name" in result

    def test_invalid_turtle_returns_original(self):
        bad = "this is not valid turtle @@@"
        result = format_grouped_turtle(bad)
        assert result == bad

    def test_empty_input(self):
        result = format_grouped_turtle("")
        # Empty input parses as empty graph — should produce minimal output
        assert isinstance(result, str)

    def test_no_unused_prefixes(self):
        result = format_grouped_turtle(SAMPLE_TURTLE)
        # Should NOT have rdflib's auto-bound prefixes like brick, csvw, etc.
        assert "brick:" not in result
        assert "csvw:" not in result
        assert "foaf:" not in result

    def test_ontology_declaration_in_ontology_section(self):
        result = format_grouped_turtle(SAMPLE_TURTLE)
        onto_section_start = result.index("# ── Ontology")
        classes_section_start = result.index("# ── Classes")
        # The ontology declaration should be between these two markers
        assert "owl:Ontology" in result[onto_section_start:classes_section_start]
