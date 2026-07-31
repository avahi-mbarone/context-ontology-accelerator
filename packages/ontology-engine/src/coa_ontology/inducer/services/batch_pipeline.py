# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Batch document extraction pipeline.

Discovers, deduplicates, and extracts ontology concepts from a directory
tree of documents using parallel Bedrock calls.
"""

import glob
import hashlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from coa_ontology.inducer.services.document_pipeline import (
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    NONE_VALS,
    _parse_tables,
    _to_concepts,
)
from coa_ontology.inducer.services.llm import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_WORKERS = 4
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2


@dataclass
class BatchConfig:
    """Configuration for a batch extraction run over one or more source directories."""

    source_dirs: list[str]
    output_dir: str
    workers: int = DEFAULT_WORKERS
    max_retries: int = DEFAULT_MAX_RETRIES
    file_glob: str = "**/*.md"
    min_size: int = 1024
    exclude_patterns: list[str] | None = None


@dataclass
class ExtractionResult:
    """Per-document result of a batch extraction: counts, timing, and success state."""

    path: str
    repo: str
    uid: str
    classes: int = 0
    props: int = 0
    triples: int = 0
    time_s: float = 0
    ok: bool = False
    error: str = ""
    concepts: list[dict] | None = None


def discover_and_dedup(config: BatchConfig) -> list[dict]:
    """Find all matching files, deduplicate by SHA-256."""
    exclude = set(config.exclude_patterns or ["/.repo/", "/node_modules/", "/.git/"])
    files: list[dict[str, Any]] = []
    for src_dir in config.source_dirs:
        repo = os.path.basename(src_dir.rstrip("/"))
        for f in glob.glob(os.path.join(src_dir, config.file_glob), recursive=True):
            if any(ex in f for ex in exclude):
                continue
            if os.path.getsize(f) < config.min_size:
                continue
            files.append({"path": f, "repo": repo, "size": os.path.getsize(f)})

    seen: dict[str, str] = {}
    unique: list[dict] = []
    for finfo in files:
        with open(finfo["path"], "rb") as fp:
            h = hashlib.sha256(fp.read()).hexdigest()
        if h not in seen:
            seen[h] = finfo["path"]
            finfo["hash"] = h
            unique.append(finfo)

    logger.info(f"Discovered {len(files)} files, {len(unique)} unique after dedup ({len(files) - len(unique)} removed)")
    return unique


def _extract_one(entry: dict, llm: LLMClient, output_dir: str, max_retries: int) -> ExtractionResult:
    """Extract ontology from a single document."""
    from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

    from coa_ontology.inducer.services.document_pipeline import _xsd_uri

    path, repo, uid = entry["path"], entry["repo"], entry["hash"][:8]
    label = os.path.splitext(os.path.basename(path))[0]

    with open(path) as f:
        text = f.read()

    t0 = time.time()
    prompt = EXTRACTION_USER.format(document=text[:30000])

    for attempt in range(max_retries):
        try:
            raw = llm.generate(prompt, system=EXTRACTION_SYSTEM)
            break
        except Exception as e:
            if "throttl" in str(e).lower() or "429" in str(e):
                time.sleep(DEFAULT_BACKOFF_BASE ** (attempt + 1))
            elif attempt == max_retries - 1:
                return ExtractionResult(path=path, repo=repo, uid=uid, time_s=time.time() - t0, error=str(e)[:120])
            else:
                time.sleep(1)

    classes, props = _parse_tables(raw)
    concepts = _to_concepts(classes, props)

    # Assemble OWL
    ns = Namespace("http://example.org/induced#")
    g = Graph()
    g.bind("ind", ns)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)
    g.add((URIRef("http://example.org/induced"), RDF.type, OWL.Ontology))

    for c in concepts:
        uri = ns[c.name]
        if c.is_class:
            g.add((uri, RDF.type, OWL.Class))
            g.add((uri, RDFS.label, Literal(c.label)))
            if c.comment:
                g.add((uri, RDFS.comment, Literal(c.comment)))
            if c.superclass and c.superclass.lower() not in NONE_VALS:
                g.add((uri, RDFS.subClassOf, ns[c.superclass]))
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

    ttl_path = os.path.join(output_dir, f"{repo}_{label}_{uid}.ttl")
    g.serialize(ttl_path, format="turtle")

    return ExtractionResult(
        path=path,
        repo=repo,
        uid=uid,
        ok=True,
        classes=len([c for c in concepts if c.is_class]),
        props=len([c for c in concepts if not c.is_class]),
        triples=len(g),
        time_s=round(time.time() - t0, 1),
        concepts=[{"name": c.name, "is_class": c.is_class, "label": c.label, "comment": c.comment} for c in concepts],
    )


def run_batch(config: BatchConfig, llm: LLMClient) -> list[ExtractionResult]:
    """Run parallel extraction on all discovered documents."""
    manifest = discover_and_dedup(config)
    os.makedirs(config.output_dir, exist_ok=True)

    results = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=config.workers) as pool:
        futures = {pool.submit(_extract_one, e, llm, config.output_dir, config.max_retries): e for e in manifest}
        for i, f in enumerate(as_completed(futures)):
            results.append(f.result())
            if (i + 1) % 50 == 0:
                ok_count = sum(1 for r in results if r.ok)
                logger.info(f"[{i + 1}/{len(manifest)}] {ok_count} ok, {(i + 1) / (time.time() - t0):.1f} docs/s")

    elapsed = time.time() - t0
    ok = [r for r in results if r.ok]
    logger.info(f"Batch complete: {len(ok)}/{len(manifest)} ok in {elapsed:.0f}s")
    return results
