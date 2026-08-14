# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the document-based induction pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from coa_ontology.inducer.schemas import ConceptMatch
from coa_ontology.inducer.services.document_pipeline import (
    DocConcept,
    DocumentPipeline,
    _add_alignment,
    _cosine,
    _novel_match,
    _parse_tables,
    _to_concepts,
    _xsd_uri,
)
from rdflib import OWL, RDF, RDFS, XSD, Graph, Namespace, URIRef
from rdflib.namespace import SKOS

pytestmark = pytest.mark.unit


# ── _parse_tables ────────────────────────────────────────────────────


def test_parse_tables_splits_classes_and_properties() -> None:
    raw = (
        "class|superclass|label|comment\n"
        "Agreement|NONE|Agreement|A negotiated deal\n"
        "\n"
        "property|type|domain|range|label|comment\n"
        "hasParty|object|Agreement|Party|has party|the party\n"
    )
    classes, props = _parse_tables(raw)
    assert len(classes) == 1
    assert classes[0]["class"] == "Agreement"
    assert classes[0]["comment"] == "A negotiated deal"
    assert len(props) == 1
    assert props[0]["property"] == "hasParty"
    assert props[0]["type"] == "object"
    assert props[0]["domain"] == "Agreement"


def test_parse_tables_strips_code_fences_and_header_rows() -> None:
    raw = (
        "```markdown\n"
        "class|superclass|label|comment\n"
        "class|superclass|label|comment\n"  # duplicate header row must be skipped
        "Policy|NONE|Policy|An insurance policy\n"
        "```"
    )
    classes, props = _parse_tables(raw)
    assert [c["class"] for c in classes] == ["Policy"]
    assert props == []


def test_parse_tables_defaults_missing_property_type_to_object() -> None:
    raw = "property|type|domain|range|label|comment\nrelatesTo||A|B||\n"
    _classes, props = _parse_tables(raw)
    assert props[0]["type"] == "object"


# ── _to_concepts ─────────────────────────────────────────────────────


def test_to_concepts_auto_declares_referenced_classes() -> None:
    classes = [{"class": "Agreement", "superclass": "Contract", "label": "Agreement", "comment": ""}]
    props = [
        {"property": "hasParty", "type": "object", "domain": "Agreement", "range": "Party", "label": "", "comment": ""}
    ]
    concepts = _to_concepts(classes, props)
    class_names = {c.name for c in concepts if c.is_class}
    # Contract (superclass) and Party (object range) are auto-declared.
    assert {"Agreement", "Contract", "Party"} <= class_names


def test_to_concepts_skips_none_valued_names() -> None:
    classes = [{"class": "NONE", "superclass": "", "label": "x", "comment": ""}]
    props = [{"property": "", "type": "object", "domain": "", "range": "", "label": "", "comment": ""}]
    concepts = _to_concepts(classes, props)
    assert concepts == []


def test_to_concepts_builds_embedding_text_from_label_and_comment() -> None:
    classes = [{"class": "Claim", "superclass": "NONE", "label": "Claim", "comment": "a request for payment"}]
    concepts = _to_concepts(classes, [])
    claim = next(c for c in concepts if c.name == "Claim")
    assert claim.embedding_text == "Claim a request for payment"


# ── _cosine ──────────────────────────────────────────────────────────


def test_cosine_identical_vectors_is_one() -> None:
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero() -> None:
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector_returns_zero() -> None:
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── _xsd_uri ─────────────────────────────────────────────────────────


def test_xsd_uri_maps_known_types() -> None:
    assert _xsd_uri("xsd:integer") == XSD.integer
    assert _xsd_uri("xsd:boolean") == XSD.integer  # QL: boolean→integer
    assert _xsd_uri("float") == XSD.decimal


def test_xsd_uri_unknown_falls_back_to_string() -> None:
    assert _xsd_uri("xsd:madeup") == XSD.string


# ── _novel_match ─────────────────────────────────────────────────────


def test_novel_match_for_class_uses_table_slot() -> None:
    c = DocConcept(name="Agreement", label="Agreement", comment="", is_class=True)
    m = _novel_match(c)
    assert m.match_type == "novel"
    assert m.source_table == "Agreement"
    assert m.source_column == ""
    assert m.matched_class_uri is None


def test_novel_match_for_property_uses_column_slot() -> None:
    c = DocConcept(name="hasParty", label="", comment="", is_class=False, domain="Agreement")
    m = _novel_match(c)
    assert m.source_column == "hasParty"
    assert m.source_table == "Agreement"


# ── _add_alignment ───────────────────────────────────────────────────


def _conf_prop() -> URIRef:
    return URIRef("http://ex.org/matchConfidence")


def test_add_alignment_exact_class_emits_subclass_and_exactmatch() -> None:
    g = Graph()
    uri = URIRef("http://ex.org/Agreement")
    target = "http://fibo/Agreement"
    m = ConceptMatch(
        source_column="",
        source_table="Agreement",
        matched_class_uri=target,
        matched_ontology_id="fibo",
        similarity=0.99,
        match_type="exact",
    )
    _add_alignment(g, uri, m, _conf_prop(), is_class=True)
    assert (uri, RDFS.subClassOf, URIRef(target)) in g
    assert (uri, SKOS.exactMatch, URIRef(target)) in g


def test_add_alignment_high_confidence_property_emits_equivalent_and_closematch() -> None:
    g = Graph()
    uri = URIRef("http://ex.org/hasParty")
    target = "http://fibo/hasParty"
    m = ConceptMatch(
        source_column="hasParty",
        source_table="Agreement",
        matched_class_uri=target,
        matched_ontology_id="fibo",
        similarity=0.85,
        match_type="high_confidence",
    )
    _add_alignment(g, uri, m, _conf_prop(), is_class=False)
    assert (uri, OWL.equivalentProperty, URIRef(target)) in g
    assert (uri, SKOS.closeMatch, URIRef(target)) in g


def test_add_alignment_ambiguous_emits_only_related_match() -> None:
    g = Graph()
    uri = URIRef("http://ex.org/Thing")
    target = "http://fibo/Thing"
    m = ConceptMatch(
        source_column="",
        source_table="Thing",
        matched_class_uri=target,
        matched_ontology_id="fibo",
        similarity=0.6,
        match_type="ambiguous",
    )
    _add_alignment(g, uri, m, _conf_prop(), is_class=True)
    assert (uri, SKOS.relatedMatch, URIRef(target)) in g
    assert (uri, RDFS.subClassOf, URIRef(target)) not in g


def test_add_alignment_novel_emits_nothing() -> None:
    g = Graph()
    uri = URIRef("http://ex.org/Novel")
    m = _novel_match(DocConcept(name="Novel", label="", comment="", is_class=True))
    _add_alignment(g, uri, m, _conf_prop(), is_class=True)
    assert len(g) == 0


@pytest.mark.parametrize("is_class", [True, False])
@pytest.mark.parametrize("match_type", ["exact", "high_confidence", "ambiguous"])
def test_add_alignment_self_match_emits_nothing(match_type, is_class) -> None:
    """A self-match (target IRI == subject IRI) must emit no alignment triple:
    a reflexive rdfs:subClassOf is a Tier-1 taxonomy-cycle self-loop and a self
    skos:* / owl:equivalentProperty is vacuous."""
    g = Graph()
    uri = URIRef("http://ex.org/Agreement")
    m = ConceptMatch(
        source_column="" if is_class else "Agreement",
        source_table="Agreement",
        matched_class_uri=str(uri),  # self-match
        matched_ontology_id="fibo",
        similarity=0.99,
        match_type=match_type,
    )
    _add_alignment(g, uri, m, _conf_prop(), is_class=is_class)
    assert len(g) == 0


# ── DocumentPipeline.extract_concepts ────────────────────────────────


def _pipeline() -> tuple[DocumentPipeline, MagicMock, MagicMock, MagicMock]:
    llm = MagicMock()
    eg = MagicMock()
    oc = MagicMock()
    return DocumentPipeline(llm=llm, embedding_generator=eg, ontology_catalog=oc), llm, eg, oc


async def test_extract_concepts_parses_llm_output() -> None:
    pipeline, llm, _eg, _oc = _pipeline()
    llm.generate.return_value = "class|superclass|label|comment\nAgreement|NONE|Agreement|A deal\n"
    concepts = await pipeline.extract_concepts("some document text")
    assert [c.name for c in concepts] == ["Agreement"]
    llm.generate.assert_called_once()


async def test_extract_concepts_truncates_to_max_chars() -> None:
    pipeline, llm, _eg, _oc = _pipeline()
    llm.generate.return_value = "class|superclass|label|comment\n"
    await pipeline.extract_concepts("x" * 100, max_chars=10)
    prompt = llm.generate.call_args[0][0]
    # The 10-char truncated document is embedded in the prompt template.
    assert "x" * 10 in prompt
    assert "x" * 11 not in prompt


# ── DocumentPipeline.embed_concepts ──────────────────────────────────


async def test_embed_concepts_empty_returns_empty_model() -> None:
    pipeline, _llm, eg, _oc = _pipeline()
    concepts, model_id = await pipeline.embed_concepts([])
    assert concepts == []
    assert model_id == ""
    eg.generate_lexical.assert_not_called()


async def test_embed_concepts_assigns_vectors() -> None:
    pipeline, _llm, eg, _oc = _pipeline()
    eg.generate_lexical.return_value = ([{"vector": [0.1, 0.2]}], "titan-v2")
    c = DocConcept(name="Agreement", label="Agreement", comment="", is_class=True, embedding_text="Agreement")
    concepts, model_id = await pipeline.embed_concepts([c], backend="bedrock")
    assert concepts[0].vector == [0.1, 0.2]
    assert model_id == "titan-v2"
    assert eg.generate_lexical.call_args.kwargs["backend"] == "bedrock"


# ── DocumentPipeline.match_concepts ──────────────────────────────────


async def test_match_concepts_no_vector_is_novel() -> None:
    pipeline, _llm, _eg, oc = _pipeline()
    c = DocConcept(name="Agreement", label="Agreement", comment="", is_class=True)
    matches = await pipeline.match_concepts([c], model_id="titan")
    assert matches[0].match_type == "novel"
    oc.search_embeddings.assert_not_called()


async def test_match_concepts_exact_when_similarity_high() -> None:
    pipeline, _llm, _eg, oc = _pipeline()
    oc.search_embeddings.return_value = [
        {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "vector": [1.0, 0.0]},
    ]
    c = DocConcept(name="Agreement", label="Agreement", comment="", is_class=True, vector=[1.0, 0.0])
    matches = await pipeline.match_concepts([c], model_id="titan")
    assert matches[0].match_type == "exact"
    assert matches[0].matched_class_uri == "http://fibo/Agreement"
    assert matches[0].similarity == pytest.approx(1.0)


async def test_match_concepts_high_confidence_band() -> None:
    pipeline, _llm, _eg, oc = _pipeline()
    # cosine ~0.857 → between 0.80 and 0.95 → high_confidence
    oc.search_embeddings.return_value = [
        {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "vector": [3.0, 1.0]},
    ]
    c = DocConcept(name="Agreement", label="Agreement", comment="", is_class=True, vector=[1.0, 1.0])
    matches = await pipeline.match_concepts([c], model_id="titan", confidence_threshold=0.80)
    assert matches[0].match_type == "high_confidence"


async def test_match_concepts_search_error_is_novel() -> None:
    pipeline, _llm, _eg, oc = _pipeline()
    oc.search_embeddings.side_effect = RuntimeError("catalog down")
    c = DocConcept(name="Agreement", label="Agreement", comment="", is_class=True, vector=[1.0, 0.0])
    matches = await pipeline.match_concepts([c], model_id="titan")
    assert matches[0].match_type == "novel"


async def test_match_concepts_no_candidates_with_vectors_is_novel() -> None:
    pipeline, _llm, _eg, oc = _pipeline()
    # Results present but none carry a vector → no candidates → novel.
    oc.search_embeddings.return_value = [{"entity_uri": "http://fibo/X", "ontology_id": "fibo"}]
    c = DocConcept(name="Agreement", label="Agreement", comment="", is_class=True, vector=[1.0, 0.0])
    matches = await pipeline.match_concepts([c], model_id="titan")
    assert matches[0].match_type == "novel"


# ── DocumentPipeline.build_ontology ──────────────────────────────────


def test_build_ontology_emits_class_and_property_triples() -> None:
    pipeline, _llm, _eg, _oc = _pipeline()
    ns = Namespace("http://ex.org/doc#")
    concepts = [
        DocConcept(name="Agreement", label="Agreement", comment="A deal", is_class=True, superclass="Contract"),
        DocConcept(
            name="hasParty",
            label="has party",
            comment="",
            is_class=False,
            prop_type="object",
            domain="Agreement",
            range="Party",
        ),
        DocConcept(
            name="amount",
            label="amount",
            comment="",
            is_class=False,
            prop_type="datatype",
            domain="Agreement",
            range="decimal",
        ),
    ]
    matches = [_novel_match(c) for c in concepts]
    g = pipeline.build_ontology("http://ex.org/doc#", concepts, matches, source_label="Docs")
    assert (ns["Agreement"], RDF.type, OWL.Class) in g
    assert (ns["Agreement"], RDFS.subClassOf, ns["Contract"]) in g
    assert (ns["hasParty"], RDF.type, OWL.ObjectProperty) in g
    assert (ns["hasParty"], RDFS.range, ns["Party"]) in g
    assert (ns["amount"], RDF.type, OWL.DatatypeProperty) in g
    assert (ns["amount"], RDFS.range, XSD.decimal) in g


# ── DocumentPipeline.store ───────────────────────────────────────────


async def test_store_uploads_file_when_no_file_path() -> None:
    pipeline, _llm, _eg, oc = _pipeline()
    oc.create_ontology.return_value = {"id": "ont-1"}  # no file_path
    g = Graph()
    g.add((URIRef("http://ex.org/doc"), RDF.type, OWL.Ontology))
    result = await pipeline.store("http://ex.org/doc#", "Docs", g, matches=[])
    assert result == {"id": "ont-1"}
    oc.upload_ontology_file.assert_called_once()
    assert oc.upload_ontology_file.call_args[0][0] == "ont-1"


async def test_store_skips_upload_when_file_path_present() -> None:
    pipeline, _llm, _eg, oc = _pipeline()
    oc.create_ontology.return_value = {"id": "ont-1", "file_path": "s3://x"}
    result = await pipeline.store("http://ex.org/doc#", "Docs", Graph(), matches=[])
    assert result["id"] == "ont-1"
    oc.upload_ontology_file.assert_not_called()


# ── DocumentPipeline.run ─────────────────────────────────────────────


async def test_run_full_pipeline_produces_report() -> None:
    pipeline, llm, eg, oc = _pipeline()
    llm.generate.return_value = "class|superclass|label|comment\nAgreement|NONE|Agreement|A deal\n"
    eg.generate_lexical.return_value = ([{"vector": [1.0, 0.0]}], "titan-v2")
    oc.search_embeddings.return_value = [
        {"entity_uri": "http://fibo/Agreement", "ontology_id": "fibo", "vector": [1.0, 0.0]},
    ]
    oc.create_ontology.return_value = {"id": "ont-9"}

    report, graph = await pipeline.run(
        document_text="doc text",
        uri_prefix="http://ex.org/doc#",
        label="Docs",
    )
    assert report.induced_ontology_id == "ont-9"
    assert report.ontology_uri_prefix == "http://ex.org/doc#"
    assert len(graph) > 0
    # The single Agreement class matched exactly → not counted as novel.
    assert report.novel_classes_created == 0
    # matched_class_uri has no '#', so the whole URI is kept as the source.
    assert "http://fibo/Agreement" in report.grounding_ontologies_used
