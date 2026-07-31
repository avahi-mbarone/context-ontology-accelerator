# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Document-based ontology induction pipeline.

Extracts ontology concepts from unstructured text via LLM,
then matches against the ontology-catalog using the same
embedding + SKOS alignment approach as schema-based induction.

Steps:
  1. Read document text
  2. LLM extraction → pipe-separated tables (classes + properties)
  3. Parse tables into SourceConcepts
  4. Embed concepts via embedding-generator
  5. VSS match against ontology-catalog
  6. Build OWL with SKOS alignment predicates
  7. Store to ontology-catalog
"""

import re
from dataclasses import dataclass, field

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SKOS

from coa_ontology.inducer.schemas import ConceptMatch, InductionReport, MatchCandidate
from coa_ontology.inducer.services.embedding_generator import EmbeddingGeneratorClient
from coa_ontology.inducer.services.llm import LLMClient
from coa_ontology.inducer.services.ontology_catalog import OntologyCatalogClient

EXTRACTION_SYSTEM = """You are an ontology engineer. \
Given a document, extract concepts and relationships as pipe-separated tables.

Output EXACTLY two tables, separated by a blank line. No markdown fences, no commentary.

TABLE 1 — CLASSES (header: class|superclass|label|comment)
TABLE 2 — PROPERTIES (header: property|type|domain|range|label|comment)

Rules:
- class: CamelCase. superclass: CamelCase or NONE. type: object or datatype.
- range for datatype: xsd:string, xsd:integer, xsd:dateTime, xsd:boolean, xsd:decimal, xsd:float.
- Every class in domain/range/superclass must appear in TABLE 1.
- Use | as separator. No markdown."""

EXTRACTION_USER = """Extract all ontology concepts and relationships from this document:

---
{document}
---"""

NONE_VALS = frozenset({"none", "n/a", "na", "", "-"})


@dataclass
class DocConcept:
    """A class or property extracted from a document, plus its embedding text and vector."""

    name: str
    label: str
    comment: str
    is_class: bool
    superclass: str = ""
    prop_type: str = ""  # "object" or "datatype"
    domain: str = ""
    range: str = ""
    embedding_text: str = ""
    vector: list[float] = field(default_factory=list)


class DocumentPipeline:
    """End-to-end pipeline that induces an OWL ontology from free-text documents.

    Extracts concepts via an LLM, embeds them, matches them against the ontology
    catalog, builds an RDF graph, and stores the result.
    """

    def __init__(
        self,
        llm: LLMClient,
        embedding_generator: EmbeddingGeneratorClient,
        ontology_catalog: OntologyCatalogClient,
    ):
        """Wire up the LLM, embedding generator, and ontology catalog clients.

        Args:
            llm: Client used to extract concepts from document text.
            embedding_generator: Client that produces lexical embeddings for concepts.
            ontology_catalog: Client used to search for and persist ontologies.
        """
        self.llm = llm
        self.eg = embedding_generator
        self.oc = ontology_catalog

    # ── Step 1-2: Extract via LLM ───────────────────────────────────

    async def extract_concepts(self, document_text: str, max_chars: int = 30000) -> list[DocConcept]:
        """Extract classes and properties from document text via the LLM.

        Args:
            document_text: Raw document text to analyze.
            max_chars: Truncate the document to this many characters before prompting.

        Returns:
            The parsed list of :class:`DocConcept` extracted from the document.
        """
        text = document_text[:max_chars]
        prompt = EXTRACTION_USER.format(document=text)
        raw = self.llm.generate(prompt, system=EXTRACTION_SYSTEM)
        classes, props = _parse_tables(raw)
        return _to_concepts(classes, props)

    # ── Step 3: Embed ───────────────────────────────────────────────

    async def embed_concepts(
        self,
        concepts: list[DocConcept],
        backend: str | None = None,
    ) -> tuple[list[DocConcept], str]:
        """Compute and attach lexical embedding vectors to each concept.

        Args:
            concepts: Concepts to embed; their ``vector`` fields are populated in place.
            backend: Optional embedding backend override; defaults to the service default.

        Returns:
            The (mutated) concepts and the model id that produced the embeddings.
        """
        inputs = [{"class_uri": f"doc:{c.name}", "labels": [c.embedding_text], "comments": []} for c in concepts]
        if not inputs:
            return concepts, ""
        results, model_id = self.eg.generate_lexical(
            ontology_id="",
            classes=inputs,
            backend=backend,
            store=False,
        )
        for concept, result in zip(concepts, results, strict=False):
            concept.vector = result["vector"]
        return concepts, model_id

    # ── Step 4: Match against catalog ───────────────────────────────

    async def match_concepts(
        self,
        concepts: list[DocConcept],
        model_id: str,
        confidence_threshold: float = 0.80,
        top_k: int = 10,
    ) -> list[ConceptMatch]:
        """Match embedded concepts against catalog entities to ground or mark them novel.

        Each concept is compared by cosine similarity to the top-K catalog candidates and
        classified as exact, high-confidence, ambiguous, or novel based on the best score.

        Args:
            concepts: Concepts carrying embedding vectors from :meth:`embed_concepts`.
            model_id: Embedding model id, used to select the matching catalog index.
            confidence_threshold: Minimum similarity to accept a high-confidence match.
            top_k: Number of catalog candidates to retrieve per concept.

        Returns:
            One :class:`ConceptMatch` per concept, in input order.
        """
        matches = []
        for c in concepts:
            if not c.vector:
                matches.append(_novel_match(c))
                continue
            entity_type = "class" if c.is_class else "property"
            try:
                results = self.oc.search_embeddings(
                    vector=c.vector,
                    embedding_type="lexical",
                    model_id=model_id,
                    entity_type=entity_type,
                    top_k=top_k,
                )
            except Exception:
                matches.append(_novel_match(c))
                continue

            candidates = []
            for r in results:
                if not r.get("vector"):
                    continue
                sim = _cosine(c.vector, r["vector"])
                candidates.append(
                    {
                        "entity_uri": r["entity_uri"],
                        "ontology_id": r.get("ontology_id"),
                        "lexical_sim": sim,
                    }
                )

            if not candidates:
                matches.append(_novel_match(c))
                continue

            best = max(candidates, key=lambda x: x["lexical_sim"])
            sim = best["lexical_sim"]
            if sim >= 0.95:
                mt = "exact"
            elif sim >= confidence_threshold:
                mt = "high_confidence"
            elif sim >= 0.50:
                mt = "ambiguous"
            else:
                mt = "novel"

            matches.append(
                ConceptMatch(
                    source_column=c.name if not c.is_class else "",
                    source_table=c.name if c.is_class else c.domain,
                    matched_class_uri=best["entity_uri"],
                    matched_ontology_id=best["ontology_id"],
                    similarity=sim,
                    match_type=mt,
                    scoring_strategy="lexical",
                    candidates=[
                        MatchCandidate(
                            entity_uri=x["entity_uri"], ontology_id=x["ontology_id"], lexical_sim=x["lexical_sim"]
                        )
                        for x in sorted(candidates, key=lambda x: x["lexical_sim"], reverse=True)[:5]
                    ],
                )
            )
        return matches

    # ── Step 5: Build OWL ───────────────────────────────────────────

    def build_ontology(
        self,
        uri_prefix: str,
        concepts: list[DocConcept],
        matches: list[ConceptMatch],
        source_label: str = "",
    ) -> Graph:
        """Build an OWL RDF graph from concepts and their grounding matches.

        Classes and properties are emitted with labels, comments, hierarchy, and
        domain/range, plus alignment axioms and match-confidence annotations.

        Args:
            uri_prefix: Namespace prefix for minting concept URIs.
            concepts: Concepts to emit into the graph.
            matches: Grounding matches aligned positionally with ``concepts``.
            source_label: Human-readable label for the induced ontology.

        Returns:
            The populated :class:`rdflib.Graph`.
        """
        g = Graph()
        ns = Namespace(uri_prefix)
        g.bind("ind", ns)
        g.bind("owl", OWL)
        g.bind("rdfs", RDFS)
        g.bind("xsd", XSD)
        g.bind("skos", SKOS)

        ont = URIRef(uri_prefix.rstrip("#").rstrip("/"))
        g.add((ont, RDF.type, OWL.Ontology))
        g.add((ont, RDFS.label, Literal(source_label or "Document-Induced Ontology")))

        conf_prop = ns["matchConfidence"]
        g.add((conf_prop, RDF.type, OWL.AnnotationProperty))

        match_map = {}
        for c, m in zip(concepts, matches, strict=False):
            match_map[c.name] = m

        for c, m in zip(concepts, matches, strict=False):
            uri = ns[c.name]
            if c.is_class:
                g.add((uri, RDF.type, OWL.Class))
                g.add((uri, RDFS.label, Literal(c.label)))
                if c.comment:
                    g.add((uri, RDFS.comment, Literal(c.comment)))
                if c.superclass and c.superclass.lower() not in NONE_VALS:
                    g.add((uri, RDFS.subClassOf, ns[c.superclass]))
                _add_alignment(g, uri, m, conf_prop, is_class=True)
            else:
                ptype = OWL.ObjectProperty if c.prop_type == "object" else OWL.DatatypeProperty
                g.add((uri, RDF.type, ptype))
                g.add((uri, RDFS.label, Literal(c.label)))
                if c.comment:
                    g.add((uri, RDFS.comment, Literal(c.comment)))
                if c.domain and c.domain.lower() not in NONE_VALS:
                    g.add((uri, RDFS.domain, ns[c.domain]))
                if c.range and c.range.lower() not in NONE_VALS:
                    if c.prop_type == "datatype":
                        r = c.range if ":" in c.range else f"xsd:{c.range}"
                        g.add((uri, RDFS.range, _xsd_uri(r)))
                    else:
                        g.add((uri, RDFS.range, ns[c.range]))
                _add_alignment(g, uri, m, conf_prop, is_class=False)

        return g

    # ── Step 6: Store ───────────────────────────────────────────────

    async def store(self, uri_prefix: str, label: str, graph: Graph, matches: list[ConceptMatch]) -> dict:
        """Persist the induced ontology to the catalog, uploading its Turtle serialization.

        Args:
            uri_prefix: Ontology URI, used as its catalog identifier.
            label: Human-readable title for the catalog record.
            graph: The RDF graph to serialize and upload.
            matches: Grounding matches, used to describe how many concepts aligned.

        Returns:
            The ontology-catalog record created for the stored ontology.
        """
        owl_turtle = graph.serialize(format="turtle")
        data = {
            "uri": uri_prefix,
            "title": label,
            "ontology_type": "induced",
            "description": f"Document-induced ontology ({sum(1 for m in matches if m.match_type != 'novel')} aligned)",
            "format": "turtle",
            "license": "proprietary",
            "license_tier": "restricted",
            "source_registry": "document",
            "domain_tags": ["induced", "unstructured"],
        }
        result = self.oc.create_ontology(data)
        if not result.get("file_path"):
            self.oc.upload_ontology_file(result["id"], owl_turtle.encode("utf-8"))
        return result

    # ── Full pipeline ───────────────────────────────────────────────

    async def run(
        self,
        document_text: str,
        uri_prefix: str,
        label: str = "Document-Induced Ontology",
        confidence_threshold: float = 0.80,
        embedding_backend: str | None = None,
        source_label: str = "",
    ) -> tuple[InductionReport, Graph]:
        """Run the full document-to-ontology pipeline end to end.

        Extracts concepts, embeds them, matches them against the catalog, builds the
        OWL graph, stores it, and assembles a summary report.

        Args:
            document_text: Raw document text to induce an ontology from.
            uri_prefix: Namespace prefix for minting concept URIs.
            label: Catalog title for the stored ontology.
            confidence_threshold: Minimum similarity to accept a high-confidence match.
            embedding_backend: Optional embedding backend override.
            source_label: Human-readable label recorded on the ontology.

        Returns:
            The :class:`InductionReport` summarizing the run and the built RDF graph.
        """
        concepts = await self.extract_concepts(document_text)
        concepts, model_id = await self.embed_concepts(concepts, backend=embedding_backend)
        matches = await self.match_concepts(concepts, model_id, confidence_threshold)
        graph = self.build_ontology(uri_prefix, concepts, matches, source_label)
        stored = await self.store(uri_prefix, label, graph, matches)

        [c for c in concepts if c.is_class]
        novel = sum(1 for c, m in zip(concepts, matches, strict=False) if c.is_class and m.match_type == "novel")

        report = InductionReport(
            job_id="",
            ontology_uri_prefix=uri_prefix,
            tables_processed=0,
            columns_processed=0,
            matches=matches,
            novel_classes_created=novel,
            grounding_ontologies_used=list(
                {
                    m.matched_class_uri.rsplit("#", 1)[0]
                    for m in matches
                    if m.matched_class_uri and m.match_type in ("exact", "high_confidence")
                }
            ),
            induced_ontology_id=stored.get("id"),
            induced_ontology_uri=uri_prefix,
        )
        return report, graph


# ── Helpers ─────────────────────────────────────────────────────────


def _parse_tables(raw: str):
    raw = re.sub(r"```\w*", "", raw).strip()
    classes, props = [], []
    current = None
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if "class|" in lower and "superclass" in lower:
            current = "c"
            continue
        if "property|" in lower and "type|" in lower:
            current = "p"
            continue
        if line.startswith("#") or line.startswith("TABLE"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if current == "c" and len(parts) >= 3:
            c = parts[0]
            if c and c.lower() != "class":
                classes.append(
                    {
                        "class": c,
                        "superclass": parts[1] if len(parts) > 1 else "",
                        "label": parts[2] if len(parts) > 2 else c,
                        "comment": parts[3] if len(parts) > 3 else "",
                    }
                )
        elif current == "p" and len(parts) >= 4:
            p = parts[0]
            if p and p.lower() != "property":
                props.append(
                    {
                        "property": p,
                        "type": (parts[1] or "object").lower(),
                        "domain": parts[2] if len(parts) > 2 else "",
                        "range": parts[3] if len(parts) > 3 else "",
                        "label": parts[4] if len(parts) > 4 else p,
                        "comment": parts[5] if len(parts) > 5 else "",
                    }
                )
    return classes, props


def _to_concepts(classes, props):
    declared = {c["class"] for c in classes}
    referenced = set()
    for c in classes:
        if c["superclass"] and c["superclass"].lower() not in NONE_VALS:
            referenced.add(c["superclass"])
    for p in props:
        if p["domain"] and p["domain"].lower() not in NONE_VALS:
            referenced.add(p["domain"])
        if p["type"] == "object" and p["range"] and p["range"].lower() not in NONE_VALS:
            referenced.add(p["range"])
    for name in referenced - declared:
        classes.append({"class": name, "superclass": "", "label": name, "comment": "Auto-declared."})

    concepts = []
    for c in classes:
        n = c["class"]
        if not n or n.lower() in NONE_VALS:
            continue
        text = c["label"]
        if c["comment"]:
            text += f" {c['comment']}"
        concepts.append(
            DocConcept(
                name=n,
                label=c["label"],
                comment=c["comment"],
                is_class=True,
                superclass=c["superclass"],
                embedding_text=text,
            )
        )
    for p in props:
        n = p["property"]
        if not n or n.lower() in NONE_VALS:
            continue
        text = p["label"]
        if p["comment"]:
            text += f" {p['comment']}"
        concepts.append(
            DocConcept(
                name=n,
                label=p["label"],
                comment=p["comment"],
                is_class=False,
                prop_type=p["type"],
                domain=p["domain"],
                range=p["range"],
                embedding_text=text,
            )
        )
    return concepts


def _novel_match(c: DocConcept) -> ConceptMatch:
    return ConceptMatch(
        source_column=c.name if not c.is_class else "",
        source_table=c.name if c.is_class else c.domain,
        matched_class_uri=None,
        matched_ontology_id=None,
        similarity=None,
        match_type="novel",
        scoring_strategy="lexical",
    )


def _add_alignment(g, uri, match, conf_prop, is_class):
    if not match.matched_class_uri:
        return
    target = URIRef(match.matched_class_uri)
    conf = Literal(match.similarity, datatype=XSD.float)
    if match.match_type == "exact":
        if is_class:
            g.add((uri, RDFS.subClassOf, target))
        else:
            g.add((uri, OWL.equivalentProperty, target))
        g.add((uri, SKOS.exactMatch, target))
        g.add((uri, conf_prop, conf))
    elif match.match_type == "high_confidence":
        if is_class:
            g.add((uri, RDFS.subClassOf, target))
        else:
            g.add((uri, OWL.equivalentProperty, target))
        g.add((uri, SKOS.closeMatch, target))
        g.add((uri, conf_prop, conf))
    elif match.match_type == "ambiguous":
        g.add((uri, SKOS.relatedMatch, target))
        g.add((uri, conf_prop, conf))


import math  # noqa: E402  — module-level import placed at the end to keep _cosine close to its caller


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


_XSD_MAP = {
    "xsd:string": XSD.string,
    "xsd:integer": XSD.integer,
    "xsd:boolean": XSD.integer,  # QL: boolean→integer
    "xsd:dateTime": XSD.dateTime,
    "xsd:decimal": XSD.decimal,
    "xsd:float": XSD.decimal,
    "xsd:double": XSD.decimal,  # QL: float/double→decimal
    "xsd:long": XSD.long,
    "xsd:anyURI": XSD.anyURI,
    "string": XSD.string,
    "integer": XSD.integer,
    "boolean": XSD.integer,
    "dateTime": XSD.dateTime,
    "float": XSD.decimal,
    "double": XSD.decimal,
}


def _xsd_uri(s):
    return _XSD_MAP.get(s, XSD.string)
