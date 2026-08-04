# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for repo-root VERSION propagation (scripts/sync_version.py).

The risk in a regex-driven manifest rewriter is not crashing — it is matching the
WRONG span (a nested ``"version"`` in a package.json, a ``version`` key in a
non-``[project]`` TOML table) or matching FEWER files than intended, either of
which silently leaves a package on a stale version. These tests pin both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import sync_version

pytestmark = pytest.mark.unit


# --- pattern targeting -------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_pyproject_rewrites_only_the_project_table(tmp_path):
    """A ``version`` key in another table must be left alone."""
    path = _write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "x"\nversion = "0.0.1"\n\n'
        '[tool.other]\nversion = "9.9.9"\n\n'
        '[build-system]\nrequires = ["hatchling"]\n',
    )
    sync_version.write_version(path, "1.2.3")
    out = path.read_text(encoding="utf-8")
    assert 'version = "1.2.3"' in out
    assert 'version = "9.9.9"' in out  # [tool.other] untouched
    assert sync_version.current_version(path) == "1.2.3"


def test_package_json_rewrites_only_the_top_level_version(tmp_path):
    """A nested ``"version"`` (deeper indent) must not be rewritten."""
    path = _write(
        tmp_path,
        "package.json",
        '{\n  "name": "x",\n  "version": "0.0.1",\n  "nested": {\n    "version": "8.8.8"\n  }\n}\n',
    )
    sync_version.write_version(path, "1.2.3")
    out = path.read_text(encoding="utf-8")
    assert '  "version": "1.2.3"' in out
    assert '"version": "8.8.8"' in out  # nested object untouched


@pytest.mark.parametrize(
    "declaration",
    ['__version__ = "0.0.1"', '__version__: str = "0.0.1"'],
)
def test_dunder_version_rewritten_with_and_without_annotation(tmp_path, declaration):
    path = _write(tmp_path, "__init__.py", f'"""Doc."""\n\n{declaration}\n')
    sync_version.write_version(path, "1.2.3")
    assert sync_version.current_version(path) == "1.2.3"


def test_init_without_version_is_not_a_manifest(tmp_path):
    """Most __init__.py files declare no version and must not gain one."""
    path = _write(tmp_path, "__init__.py", '"""Doc."""\n')
    assert sync_version.current_version(path) is None


def test_unrecognized_filename_has_no_pattern(tmp_path):
    assert sync_version.pattern_for(tmp_path / "setup.cfg") is None


# --- VERSION validation ------------------------------------------------------


@pytest.mark.parametrize("raw", ["v0.1.0", "0.1", "1.0.0.0", "not-a-version", ""])
def test_invalid_version_file_exits(tmp_path, monkeypatch, raw):
    """A leading 'v' or stray content would produce an invalid PEP 621 / npm manifest."""
    version_file = _write(tmp_path, "VERSION", f"{raw}\n")
    monkeypatch.setattr(sync_version, "VERSION_FILE", version_file)
    with pytest.raises(SystemExit):
        sync_version.read_version()


@pytest.mark.parametrize("raw", ["0.1.0", "1.2.3", "0.1.0-rc1", "0.1.0+build.5"])
def test_valid_version_file_is_stripped(tmp_path, monkeypatch, raw):
    version_file = _write(tmp_path, "VERSION", f"{raw}\n")
    monkeypatch.setattr(sync_version, "VERSION_FILE", version_file)
    assert sync_version.read_version() == raw


# --- repo-wide coverage ------------------------------------------------------


def test_every_manifest_kind_is_discovered():
    """Guards the real failure mode: a pattern silently matching nothing."""
    assert sync_version.missing_kinds(sync_version.discover_manifests()) == []


def test_repo_manifests_agree_with_version_file():
    """The committed tree must already be in sync (`make lint` enforces this)."""
    version = sync_version.read_version()
    stale = {
        str(p.relative_to(sync_version.REPO_ROOT)): sync_version.current_version(p)
        for p in sync_version.discover_manifests()
        if sync_version.current_version(p) != version
    }
    assert stale == {}, f"run `make version` — these disagree with VERSION={version}: {stale}"


def test_generated_and_vendored_trees_are_excluded():
    """smithy-generated is overwritten by codegen; rewriting it would be lost work."""
    for path in sync_version.discover_manifests():
        assert sync_version.EXCLUDED_PARTS.isdisjoint(path.parts)
