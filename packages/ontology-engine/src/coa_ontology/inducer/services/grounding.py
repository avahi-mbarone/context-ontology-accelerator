# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Centralized grounding service.

Layered pipeline:
  1. Exact-name match (normalized label equality → score 1.0)
  2. Embedding recall (top-K via vector search)
  3. LLM rerank (discriminative: pick best match or abstain)
  4. Score-thresholded tier classification (exact / high_confidence / ambiguous / novel)

Modes (controlled by ``grounding_mode`` param):
  - NONE:     skip grounding entirely, all concepts → novel
  - STANDARD: layers 1 + 2 only (deterministic, no LLM, cheap)
  - ENHANCED: full pipeline including LLM rerank (default)
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass

import boto3
from coa_common import async_boto_config
from coa_common.bedrock_metrics import CostTracker

from coa_ontology.inducer.schemas import ConceptMatch, MatchCandidate

log = logging.getLogger(__name__)

GROUNDING_MODES = ("NONE", "STANDARD", "ENHANCED")

# Connection-pool cap for the shared bedrock-runtime client. The rerank
# ThreadPool (pipeline.py, _grounding_workers default 24) has ALL threads share
# this one lazily-built client; botocore's default max_pool_connections=10
# throttles a multi-threaded pool ("Connection pool is full, discarding
# connection"). Sized above the worker pool (24) so no rerank thread starves on
# a connection.
_BEDROCK_MAX_POOL_CONNECTIONS = 32

_RERANK_SYSTEM = (
    "You are an ontology grounding expert. Given a source database table "
    "(with its columns and description) and a list of candidate ontology "
    "classes (each with its formal definition), decide which candidate "
    "the table should be grounded to.\n\n"
    "Output EXACTLY one JSON object with these fields:\n"
    '  {"choice": "<localName or NONE>", '
    '"relationship": "<exactMatch|closeMatch|broadMatch|'
    'narrowMatch|relatedMatch|none>", '
    '"confidence": <0.0-1.0>, "reason": "<one sentence>"}\n\n'
    "Rules:\n"
    "- If a candidate's name matches or closely describes the table's "
    "purpose, PICK IT. Prefer the candidate with a definition that aligns "
    "with the table's columns and description.\n"
    "- When multiple candidates share the same name (e.g. from different "
    "ontologies), pick the one whose definition best matches the table's "
    "domain. If one has a definition and the other doesn't, prefer the "
    "one with a definition.\n"
    "- Pick NONE only if no candidate genuinely represents the same or "
    "closely related concept — i.e., the table is a truly novel domain "
    "concept not covered by any candidate.\n"
    "- exactMatch: table IS this concept (same meaning, same scope)\n"
    "- closeMatch: nearly interchangeable, minor scope difference\n"
    "- broadMatch: candidate is a broader/parent concept\n"
    "- narrowMatch: candidate is a narrower/child concept\n"
    "- relatedMatch: conceptually associated but distinct\n"
    "- Output valid JSON only. No markdown, no explanation outside the JSON."
)

# Class-flavored variant of _RERANK_SYSTEM used when grounding an induced
# ontology CLASS (e.g. from the unstructured / lexical-graph pipeline) rather
# than a database table. The recall/exact-match internals are identical; only
# the LLM framing changes so the reranker judges class-vs-class alignment
# instead of table-vs-class. Keeping the JSON contract byte-identical means the
# same parser handles both.
_RERANK_SYSTEM_CLASS = (
    "You are an ontology grounding expert. Given a source ontology class "
    "(with its label and definition) and a list of candidate ontology "
    "classes (each with its formal definition), decide which candidate "
    "the source class should be grounded to.\n\n"
    "Output EXACTLY one JSON object with these fields:\n"
    '  {"choice": "<localName or NONE>", '
    '"relationship": "<exactMatch|closeMatch|broadMatch|'
    'narrowMatch|relatedMatch|none>", '
    '"confidence": <0.0-1.0>, "reason": "<one sentence>"}\n\n'
    "Rules:\n"
    "- If a candidate's name matches or closely describes the source class's "
    "meaning, PICK IT. Prefer the candidate whose definition aligns with the "
    "source class's definition.\n"
    "- When multiple candidates share the same name (e.g. from different "
    "ontologies), pick the one whose definition best matches the source "
    "class's domain. If one has a definition and the other doesn't, prefer "
    "the one with a definition.\n"
    "- Pick NONE only if no candidate genuinely represents the same or "
    "closely related concept — i.e., the source class is a truly novel domain "
    "concept not covered by any candidate.\n"
    "- exactMatch: the source class IS this concept (same meaning, same scope)\n"
    "- closeMatch: nearly interchangeable, minor scope difference\n"
    "- broadMatch: candidate is a broader/parent concept\n"
    "- narrowMatch: candidate is a narrower/child concept\n"
    "- relatedMatch: conceptually associated but distinct\n"
    "- Output valid JSON only. No markdown, no explanation outside the JSON."
)


@dataclass
class GroundingCandidate:
    """A candidate foundational entity for grounding, with lexical and rerank scores."""

    entity_uri: str
    ontology_id: str | None
    label: str
    definition: str
    lexical_sim: float
    rerank_score: float | None = None
    rerank_relationship: str | None = None
    rerank_reason: str | None = None


@dataclass
class GroundingResult:
    """Result of grounding one source column: the chosen match, tier, and rationale."""

    source_table: str
    source_column: str
    candidates: list[GroundingCandidate]
    chosen: GroundingCandidate | None
    match_type: str  # exact | high_confidence | ambiguous | novel
    relationship: str | None  # SKOS relationship from reranker
    confidence: float | None  # reranker confidence or cosine sim
    reason: str | None  # reranker's justification
    mode: str  # which mode produced this result


def _normalize(s: str) -> str:
    """Normalize a label for exact-match comparison."""
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return s


def _local_name(uri: str) -> str:
    """Extract local name from an IRI."""
    if "#" in uri:
        return uri.rsplit("#", 1)[1]
    return uri.rsplit("/", 1)[-1]


def classify_score_tier(score: float | None, *, has_rerank: bool = True, confidence_threshold: float = 0.80) -> str:
    """Classify a single match score into a grounding tier.

    Tiering is purely score-thresholded: the reranked ladder
    (``has_rerank=True``, the default, matching how production induction scores
    LLM-reranked candidates) and the STANDARD embedding ladder each map an
    absolute score to ``exact``/``high_confidence``/``ambiguous``/``novel``.
    ``None`` (no candidate) is ``novel``.
    """
    if score is None:
        return "novel"
    if has_rerank:
        if score >= 0.85:
            return "exact"
        if score >= 0.65:
            return "high_confidence"
        if score >= 0.40:
            return "ambiguous"
        return "novel"
    # STANDARD mode: use embedding scores with original thresholds
    if score >= 0.95:
        return "exact"
    if score >= confidence_threshold:
        return "high_confidence"
    if score >= 0.50:
        return "ambiguous"
    return "novel"


class GroundingService:
    """Shared grounding service used by all induction strategies."""

    def __init__(
        self,
        ontology_catalog,
        embedding_generator,
        llm_region: str = "us-east-1",
        llm_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        namespace: str | None = None,
        cost_tracker: CostTracker | None = None,
    ):
        """Configure the catalog, embedding, and LLM dependencies for grounding.

        Args:
            ontology_catalog: Client used to recall candidate foundational entities.
            embedding_generator: Client used to embed source concepts.
            llm_region: AWS region for the Bedrock rerank client.
            llm_model_id: Bedrock model id used to rerank candidates.
            namespace: Namespace whose per-namespace recall index to query; None uses
                the default-namespace index.
            cost_tracker: Optional per-job Bedrock usage tracker for rerank calls.
        """
        self.oc = ontology_catalog
        self.eg = embedding_generator
        self._llm_region = llm_region
        self._llm_model_id = llm_model_id
        self._bedrock = None
        # Optional per-job Bedrock usage tracker. When present, every rerank
        # converse call records its token usage under the "rerank" stage.
        self._cost_tracker = cost_tracker
        # Namespace whose per-namespace OpenSearch index the recall must
        # query. When None the catalog client omits ?namespace= and the
        # endpoint falls back to the default-namespace (bare) index — correct
        # ONLY for default-namespace deployments. Pass the real namespace on
        # multi-namespace deployments or recall hits the empty bare index.
        self._namespace = namespace

    @property
    def bedrock(self):
        """Lazily create and cache the Bedrock runtime client for rerank calls."""
        if self._bedrock is None:
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=self._llm_region,
                config=async_boto_config(read_timeout=120, max_pool_connections=_BEDROCK_MAX_POOL_CONNECTIONS),
            )
        return self._bedrock

    def ground_class(
        self,
        class_label: str,
        class_description: str,
        concept_vector: list[float],
        model_id: str,
        confidence_threshold: float = 0.80,
        grounding_mode: str = "ENHANCED",
        ontology_ids: list[str] | None = None,
        top_k: int = 30,
        exclude_entity_uri: str | None = None,
    ) -> GroundingResult:
        """Ground an induced ontology CLASS against loaded ontologies.

        Thin wrapper over :meth:`ground_table` that shares the entire
        recall → exact-name → LLM-rerank pipeline, but frames the LLM
        reranker as judging class-vs-class alignment (via
        :data:`_RERANK_SYSTEM_CLASS`) instead of table-vs-class. A class
        has no columns, so ``columns=[]`` and the rerank prompt omits the
        column section. Used by the unstructured (lexical-graph) induction
        path so document-derived classes ground to foundational ontologies
        exactly the way structured tables do.

        The returned :class:`GroundingResult` carries the class label in
        ``source_table`` (the field is strategy-agnostic despite its name);
        callers emit ``skos:*Match`` / ``rdfs:subClassOf`` from
        ``result.chosen`` + ``result.relationship``.
        """
        return self.ground_table(
            table_name=class_label,
            table_description=class_description,
            columns=[],
            concept_vector=concept_vector,
            model_id=model_id,
            confidence_threshold=confidence_threshold,
            grounding_mode=grounding_mode,
            ontology_ids=ontology_ids,
            top_k=top_k,
            exclude_entity_uri=exclude_entity_uri,
            _rerank_system=_RERANK_SYSTEM_CLASS,
            _subject_kind="class",
        )

    def ground_table(
        self,
        table_name: str,
        table_description: str,
        columns: list[dict],
        concept_vector: list[float],
        model_id: str,
        confidence_threshold: float = 0.80,
        grounding_mode: str = "ENHANCED",
        ontology_ids: list[str] | None = None,
        top_k: int = 30,
        exclude_entity_uri: str | None = None,
        *,
        _rerank_system: str = _RERANK_SYSTEM,
        _subject_kind: str = "table",
    ) -> GroundingResult:
        """Ground a source table against the provided ontology pool.

        Layered pipeline: embedding recall (top-K by cosine similarity) →
        exact-name shortcut → LLM rerank of the survivors.

        Args:
            table_name: Name of the source table (or class, for ``ground_class``).
            table_description: Free-text description used in the rerank prompt.
            columns: Column metadata dicts; included in the rerank context.
            concept_vector: Pre-computed embedding of the subject concept.
            model_id: Embedding model id used for recall.
            confidence_threshold: Minimum rerank confidence to accept a match.
            grounding_mode: ``ENHANCED``/``STANDARD`` run the pipeline;
                ``NONE`` short-circuits to a novel result (no grounding).
            ontology_ids: The resolved grounding pool — grounding is scoped to
                EXACTLY these ontologies. An empty pool (``[]`` or ``None``)
                means "no grounding scope": recall returns no candidates and the
                subject is classified novel. There is no unscoped/global recall —
                an empty pool never falls back to a namespace-wide search (which
                would match loaded-but-unselected ontologies; the grounding
                opt-out bug).
            top_k: Number of recall candidates to fetch per ontology.
            exclude_entity_uri: IRI to drop from recall so the subject can't
                ground to itself (incremental induction grounds against a pool
                that includes its own ontology).

        Returns:
            A ``GroundingResult`` with the chosen match (or ``match_type
            == "novel"`` when nothing grounds).
        """
        log.info(
            "ground_%s: name=%s mode=%s ontology_ids=%s vector_len=%d model=%s",
            _subject_kind,
            table_name,
            grounding_mode,
            ontology_ids[:2] if ontology_ids else None,
            len(concept_vector),
            model_id,
        )
        if grounding_mode == "NONE":
            return GroundingResult(
                source_table=table_name,
                source_column="",
                candidates=[],
                chosen=None,
                match_type="novel",
                relationship=None,
                confidence=None,
                reason="Grounding disabled (mode=NONE)",
                mode="NONE",
            )

        # Layer 1: Embedding recall (top-K candidates). When grounding against a
        # pool that includes the subject's OWN ontology (e.g. incremental
        # induction grounds new classes against the namespace's already-accepted
        # ontologies), the subject can recall — and then "ground to" — ITSELF.
        # Exclude its own IRI from the candidate set. Fetch one extra so removing
        # self doesn't shrink the effective top-K.
        recall_k = top_k + 1 if exclude_entity_uri else top_k
        raw_candidates = self._recall(concept_vector, model_id, ontology_ids, recall_k)
        if exclude_entity_uri:
            _self = exclude_entity_uri.rstrip("/")
            raw_candidates = [c for c in raw_candidates if c.entity_uri.rstrip("/") != _self][:top_k]
        if not raw_candidates:
            return GroundingResult(
                source_table=table_name,
                source_column="",
                candidates=[],
                chosen=None,
                match_type="novel",
                relationship=None,
                confidence=None,
                reason="No candidates returned from embedding search",
                mode=grounding_mode,
            )

        # Layer 2: Exact-name match check.
        # In STANDARD mode (no LLM): auto-ground single matches, pick best for multiple.
        # In ENHANCED mode: ALWAYS defer to LLM for domain verification — a name match
        # is NOT sufficient (e.g. Dublin Core "Policy" ≠ insurance "policy").
        exact_matches = self._exact_name_matches(table_name, raw_candidates)
        if exact_matches and grounding_mode == "STANDARD":
            if len(exact_matches) == 1:
                exact = exact_matches[0]
                return GroundingResult(
                    source_table=table_name,
                    source_column="",
                    candidates=raw_candidates,
                    chosen=exact,
                    match_type="exact",
                    relationship="exactMatch",
                    confidence=1.0,
                    reason=f"Exact name match: {table_name} == {exact.label}",
                    mode="STANDARD",
                )
            else:
                best = max(exact_matches, key=lambda c: c.lexical_sim)
                return GroundingResult(
                    source_table=table_name,
                    source_column="",
                    candidates=raw_candidates,
                    chosen=best,
                    match_type="high_confidence",
                    relationship="closeMatch",
                    confidence=best.lexical_sim,
                    reason=(
                        f"Multiple exact-name matches ({len(exact_matches)}); "
                        "picked by embedding score (no LLM in STANDARD mode)"
                    ),
                    mode="STANDARD",
                )
        if exact_matches and grounding_mode == "ENHANCED":
            log.info(
                "ground_table: %d exact-name match(es) for '%s' — deferring to LLM for domain verification",
                len(exact_matches),
                table_name,
            )
        # In ENHANCED mode: fall through to LLM rerank below (always)

        if grounding_mode == "STANDARD":
            # No LLM — classify purely on embedding score
            best = raw_candidates[0]
            match_type = classify_score_tier(
                best.lexical_sim, has_rerank=False, confidence_threshold=confidence_threshold
            )
            return GroundingResult(
                source_table=table_name,
                source_column="",
                candidates=raw_candidates,
                chosen=best if match_type != "novel" else None,
                match_type=match_type,
                relationship="closeMatch"
                if match_type in ("exact", "high_confidence")
                else ("relatedMatch" if match_type == "ambiguous" else None),
                confidence=best.lexical_sim,
                reason=None,
                mode="STANDARD",
            )

        # Layer 3: LLM rerank (ENHANCED mode)
        rerank_result = self._llm_rerank(
            table_name,
            table_description,
            columns,
            raw_candidates,
            rerank_system=_rerank_system,
            subject_kind=_subject_kind,
        )

        if rerank_result is None or rerank_result.get("choice") == "NONE":
            # LLM abstained — novel
            return GroundingResult(
                source_table=table_name,
                source_column="",
                candidates=raw_candidates,
                chosen=None,
                match_type="novel",
                relationship=None,
                confidence=None,
                reason=rerank_result.get("reason", "LLM abstained") if rerank_result else "LLM call failed",
                mode="ENHANCED",
            )

        # LLM picked a candidate
        choice_name = rerank_result["choice"]
        chosen = next(
            (c for c in raw_candidates if _normalize(_local_name(c.entity_uri)) == _normalize(choice_name)),
            None,
        )
        if not chosen:
            # LLM named something not in the candidate list — treat as novel
            log.warning("LLM chose '%s' which is not in candidates for table '%s'", choice_name, table_name)
            return GroundingResult(
                source_table=table_name,
                source_column="",
                candidates=raw_candidates,
                chosen=None,
                match_type="novel",
                relationship=None,
                confidence=None,
                reason=f"LLM chose '{choice_name}' not in candidates",
                mode="ENHANCED",
            )

        try:
            llm_confidence = float(rerank_result.get("confidence", 0.5))
        except (TypeError, ValueError):
            llm_confidence = 0.5
        relationship = rerank_result.get("relationship", "relatedMatch")
        match_type = classify_score_tier(llm_confidence, has_rerank=True, confidence_threshold=confidence_threshold)

        chosen.rerank_score = llm_confidence
        chosen.rerank_relationship = relationship
        chosen.rerank_reason = rerank_result.get("reason")

        return GroundingResult(
            source_table=table_name,
            source_column="",
            candidates=raw_candidates,
            chosen=chosen,
            match_type=match_type,
            relationship=relationship,
            confidence=llm_confidence,
            reason=rerank_result.get("reason"),
            mode="ENHANCED",
        )

    def _recall(
        self, vector: list[float], model_id: str, ontology_ids: list[str] | None, top_k: int
    ) -> list[GroundingCandidate]:
        """Embedding-based recall: top-K candidates by cosine similarity.

        Scope semantics of ``ontology_ids`` (the resolved grounding pool):
          - a non-empty list → search each ontology separately and merge/dedup;
          - an empty pool (``[]`` or ``None``) → return no candidates. The
            caller resolved a grounding pool and it is empty (the user selected
            no ontologies and the namespace has no accepted induced ontologies).
            We do NOT fall back to a namespace-wide search — that fallback would
            match loaded-but-unselected ontologies, defeating the user's choice
            not to ground against them (the grounding opt-out bug). Grounding is
            always scoped to exactly the pool the caller provides; there is no
            unscoped/global recall.
        """
        if not ontology_ids:
            log.info("grounding_recall: empty grounding scope — returning no candidates (all-novel)")
            return []
        ids_to_search: list[str] = list(ontology_ids)

        log.info(
            "grounding_recall: vector_len=%d model_id=%s ontology_ids=%s top_k=%d",
            len(vector),
            model_id,
            ids_to_search[:3],
            top_k,
        )

        all_results: list[dict] = []
        for oid in ids_to_search:
            try:
                hits = self.oc.search_embeddings(
                    vector=vector,
                    embedding_type="lexical",
                    model_id=model_id,
                    entity_type="class",
                    ontology_id=oid,
                    top_k=top_k,
                    namespace=self._namespace,
                )
                log.info(
                    "grounding_recall: ontology_id=%s returned %d hits, first=%s",
                    oid,
                    len(hits),
                    hits[0].get("entity_uri", "")[:60] if hits else "EMPTY",
                )
                if hits:
                    sample = hits[0]
                    log.info(
                        "grounding_recall: sample_hit keys=%s score=%s vector_len=%d",
                        list(sample.keys())[:8],
                        sample.get("score"),
                        len(sample.get("vector") or []),
                    )
                all_results.extend(hits)
            except Exception as e:
                # Re-raise so an incomplete recall fails the job rather than
                # dropping this ontology's candidates and misclassifying the
                # subject 'novel'.
                log.error("grounding_recall: FAILED ontology_id=%s error=%s", oid, e, exc_info=True)
                raise

        log.info("grounding_recall: total_results=%d across %d ontology searches", len(all_results), len(ids_to_search))

        if not all_results:
            return []

        import math

        def _cosine(a, b):
            n = min(len(a), len(b))
            if n == 0:
                return 0.0
            dot = sum(a[i] * b[i] for i in range(n))
            na = math.sqrt(sum(a[i] ** 2 for i in range(n)))
            nb = math.sqrt(sum(b[i] ** 2 for i in range(n)))
            return dot / (na * nb) if na and nb else 0.0

        # Deduplicate: first by normalized URI, then by (local_name, ontology_id)
        # to collapse duplicates from http/https variants or multiple embedding runs.
        seen_uri: dict[str, dict] = {}
        for r in all_results:
            uri = r.get("entity_uri", "").rstrip("/")
            score = r.get("score") or 0.0
            if not uri:
                continue
            if uri in seen_uri:
                if score > (seen_uri[uri].get("score") or 0):
                    seen_uri[uri] = r
            else:
                seen_uri[uri] = r
        # Secondary dedup: same local name + same ontology → keep highest score
        seen_name: dict[tuple[str, str], dict] = {}
        for r in seen_uri.values():
            uri = r.get("entity_uri", "")
            local = _local_name(uri)
            oid = r.get("ontology_id") or ""
            key = (local.lower(), oid)
            existing = seen_name.get(key)
            if existing is None or (r.get("score") or 0) > (existing.get("score") or 0):
                seen_name[key] = r
        deduped = list(seen_name.values())

        candidates = []
        for r in deduped:
            uri = r.get("entity_uri", "")
            if not uri:
                continue
            # Prefer the pre-computed score from the vector store (kNN);
            # fall back to local cosine if the raw vector is available.
            sim = r.get("score") or 0.0
            if not sim and r.get("vector"):
                sim = _cosine(vector, r["vector"])
            if sim <= 0:
                continue
            # Use the 'text' field from AOSS as the definition — it contains
            # the label + definition text that was embedded. This is more
            # reliable than the Neptune graph lookup (which fails for classes
            # ingested before the skos:definition fix).
            raw_text = r.get("text") or ""
            # Strip the label prefix from the text to get just the definition.
            # Handle both exact label ("Organization ...") and split CamelCase
            # ("Data Catalog ...") since _text_for uses _split_camel at embed time.
            label = _local_name(uri)
            split_label = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", label)
            defn = raw_text
            if raw_text.lower().startswith(label.lower()):
                defn = raw_text[len(label) :].strip()
            elif raw_text.lower().startswith(split_label.lower()):
                defn = raw_text[len(split_label) :].strip()

            candidates.append(
                GroundingCandidate(
                    entity_uri=uri,
                    ontology_id=r.get("ontology_id"),
                    label=label,
                    definition=defn,
                    lexical_sim=sim,
                )
            )
        candidates.sort(key=lambda c: -c.lexical_sim)
        top = candidates[:top_k]

        return top

    def _exact_name_matches(self, table_name: str, candidates: list[GroundingCandidate]) -> list[GroundingCandidate]:
        """Return all candidates whose label is an exact normalized match to the table name."""
        norm_table = _normalize(table_name)
        return [c for c in candidates if _normalize(c.label) == norm_table]

    def _llm_rerank(
        self,
        table_name: str,
        description: str,
        columns: list[dict],
        candidates: list[GroundingCandidate],
        rerank_system: str = _RERANK_SYSTEM,
        subject_kind: str = "table",
    ) -> dict | None:
        """Ask the LLM to pick the best candidate or abstain.

        ``subject_kind`` ("table" or "class") + ``rerank_system`` let the
        shared reranker frame the source correctly: tables get a
        ``Columns:`` section; classes (no columns) omit it and are labeled
        SOURCE CLASS. The JSON contract and parsing are identical.
        """
        is_class = subject_kind == "class"
        # Build the prompt with source context + candidate definitions.
        # A class has no columns, so the column section is omitted for it.
        col_lines = []
        for col in columns[:20]:
            parts = [f"  - {col.get('name', '')} : {col.get('dataType', '')}"]
            if col.get("description"):
                parts.append(f"-- {col['description'][:80]}")
            if col.get("constraint"):
                parts.append(f"[{col['constraint']}]")
            col_lines.append(" ".join(parts))

        cand_lines = []
        for c in candidates[:8]:
            defn = c.definition or "(no definition available)"
            source = _local_name(c.ontology_id) if c.ontology_id else "unknown"
            cand_lines.append(f"  - {c.label} [from {source}]: {defn[:200]}")

        header = f"SOURCE {'CLASS' if is_class else 'TABLE'}: {table_name}\n"
        columns_block = "" if is_class else ("Columns:\n" + "\n".join(col_lines) + "\n")
        prompt = (
            header + f"Description: {description or '(none)'}\n" + columns_block + "\n"
            "CANDIDATE ONTOLOGY CLASSES:\n" + "\n".join(cand_lines) + "\n\n"
            f"Which candidate should this {subject_kind} ground to (or NONE)?"
        )

        try:
            # Warm the lazy bedrock client BEFORE timing but INSIDE the try — first
            # access constructs the boto3 client + service model (~100-300ms), which
            # must NOT be counted as rerank latency (_t0 is captured after the client
            # is ready, so _t0→converse-return measures only the round-trip). Keeping
            # the warm-up inside the try means a construction failure (e.g. bad region)
            # is caught below and abstains, exactly like a converse() failure — never
            # escaping to fail the whole induction job.
            bedrock = self.bedrock
            _t0 = time.monotonic()
            resp = bedrock.converse(
                modelId=self._llm_model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                system=[{"text": rerank_system}],
                inferenceConfig={"maxTokens": 200, "temperature": 0},
            )
            # Record token usage on the success path, right after converse returns
            # — usage is present even if the JSON body later fails to parse.
            if self._cost_tracker is not None:
                self._cost_tracker.record_from_converse(
                    "rerank",
                    self._llm_model_id,
                    resp,
                    latency_ms=(time.monotonic() - _t0) * 1000.0,
                )
            raw = resp["output"]["message"]["content"][0]["text"].strip()
            # Parse JSON response
            # Handle cases where LLM wraps in markdown
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
            log.info(
                "grounding_rerank table=%s choice=%s confidence=%.2f reason=%s",
                table_name,
                result.get("choice"),
                result.get("confidence", 0),
                result.get("reason", ""),
            )
            return result
        except json.JSONDecodeError as e:
            log.warning("LLM rerank returned non-JSON for table '%s': %s", table_name, e)
            return None
        except Exception as e:
            log.error("LLM rerank failed for table '%s': %s", table_name, e)
            return None

    def to_concept_match(self, result: GroundingResult) -> ConceptMatch:
        """Convert a GroundingResult to the existing ConceptMatch schema."""
        return ConceptMatch(
            source_column=result.source_column,
            source_table=result.source_table,
            matched_class_uri=result.chosen.entity_uri if result.chosen else None,
            matched_ontology_id=result.chosen.ontology_id if result.chosen else None,
            similarity=result.confidence,
            match_type=result.match_type,
            relationship=result.relationship,
            scoring_strategy=f"grounding_{result.mode.lower()}",
            reason=result.reason,
            candidates=[
                MatchCandidate(
                    entity_uri=c.entity_uri,
                    ontology_id=c.ontology_id,
                    lexical_sim=c.lexical_sim,
                    structural_sim=None,
                    fused_score=c.rerank_score,
                    definition=c.definition or None,
                )
                for c in result.candidates[:10]
            ]
            if result.candidates
            else None,
        )
