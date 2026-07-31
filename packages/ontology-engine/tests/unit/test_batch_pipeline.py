# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the batch document extraction pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from coa_ontology.inducer.services.batch_pipeline import (
    BatchConfig,
    ExtractionResult,
    _extract_one,
    discover_and_dedup,
    run_batch,
)
from rdflib import Graph

pytestmark = pytest.mark.unit

_LLM_OUTPUT = (
    "class|superclass|label|comment\n"
    "Agreement|NONE|Agreement|A negotiated deal\n"
    "\n"
    "property|type|domain|range|label|comment\n"
    "amount|datatype|Agreement|decimal|amount|the amount\n"
)


def _write(path: Path, size: int) -> None:
    path.write_text("x" * size)


# ── discover_and_dedup ───────────────────────────────────────────────


def test_discover_and_dedup_removes_duplicates(tmp_path: Path) -> None:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "a.md").write_text("same content " * 200)
    (d / "b.md").write_text("same content " * 200)  # identical → dedup
    (d / "c.md").write_text("different content " * 200)
    config = BatchConfig(source_dirs=[str(d)], output_dir=str(tmp_path / "out"), min_size=10)
    unique = discover_and_dedup(config)
    # Two distinct hashes remain out of three files.
    assert len(unique) == 2
    assert all("hash" in u for u in unique)
    assert {u["repo"] for u in unique} == {"repo"}


def test_discover_and_dedup_skips_small_and_excluded(tmp_path: Path) -> None:
    d = tmp_path / "repo"
    (d / ".git").mkdir(parents=True)
    (d / "big.md").write_text("y" * 5000)
    (d / "small.md").write_text("y" * 5)  # below min_size
    (d / ".git" / "excluded.md").write_text("y" * 5000)  # excluded path
    config = BatchConfig(source_dirs=[str(d)], output_dir=str(tmp_path / "out"), min_size=1024)
    unique = discover_and_dedup(config)
    assert [Path(u["path"]).name for u in unique] == ["big.md"]


# ── _extract_one ─────────────────────────────────────────────────────


def test_extract_one_writes_turtle_and_reports_counts(tmp_path: Path) -> None:
    src = tmp_path / "doc.md"
    src.write_text("some document text")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    entry = {"path": str(src), "repo": "repo", "hash": "abcdef1234567890"}
    llm = MagicMock()
    llm.generate.return_value = _LLM_OUTPUT

    result = _extract_one(entry, llm, str(out_dir), max_retries=3)

    assert result.ok is True
    assert result.classes == 1
    assert result.props == 1
    assert result.triples > 0
    # A .ttl file is written and is valid turtle.
    ttl_files = list(out_dir.glob("*.ttl"))
    assert len(ttl_files) == 1
    g = Graph()
    g.parse(ttl_files[0], format="turtle")
    assert len(g) == result.triples


def test_extract_one_persistent_error_returns_failure(tmp_path: Path) -> None:
    src = tmp_path / "doc.md"
    src.write_text("text")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    entry = {"path": str(src), "repo": "repo", "hash": "deadbeefcafef00d"}
    llm = MagicMock()
    llm.generate.side_effect = RuntimeError("bedrock boom")

    result = _extract_one(entry, llm, str(out_dir), max_retries=1)
    assert result.ok is False
    assert "bedrock boom" in result.error
    assert list(out_dir.glob("*.ttl")) == []


# ── run_batch ────────────────────────────────────────────────────────


def test_run_batch_processes_all_and_returns_results(tmp_path: Path) -> None:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "a.md").write_text("content a " * 200)
    (d / "b.md").write_text("content b " * 200)
    out_dir = tmp_path / "out"
    config = BatchConfig(source_dirs=[str(d)], output_dir=str(out_dir), min_size=10, workers=1)
    llm = MagicMock()
    llm.generate.return_value = _LLM_OUTPUT

    results = run_batch(config, llm)
    assert len(results) == 2
    assert all(isinstance(r, ExtractionResult) for r in results)
    assert all(r.ok for r in results)
    # Output directory was created and populated.
    assert out_dir.exists()
    assert len(list(out_dir.glob("*.ttl"))) == 2
