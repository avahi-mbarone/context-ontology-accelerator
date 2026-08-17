# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Every third-party module the namespace Lambdas import must be in the bundle.

The namespace Lambdas are bundled by ``bundlePython`` from
``packages/control-plane/requirements.txt`` (see namespace-stack.ts). That file is
hand-maintained and is NOT resolved transitively from ``coa-common``'s
dependencies — so an import that resolves perfectly in the uv workspace can still
be absent from the deployed bundle.

Nothing catches that before deploy: unit tests import from the workspace, ruff and
mypy do not look at requirements.txt, and ``cdk synth`` only builds the asset. The
failure surfaces at invoke time as::

    Runtime.ImportModuleError: Unable to import module
    'coa_control_plane.namespace.deletion_pipeline.delete_sources':
    No module named 'opensearchpy'

which is what happened: ``namespace/cleanup.py`` gained
``from coa_common.opensearch import AossVectorClient`` and every deletion_pipeline
handler imports cleanup, so four Lambdas broke at once — including ``finalize``,
the pipeline's must-succeed step. The state machine burned its 3 retries per step
and landed the namespace in DELETE_FAILED.

This test walks imports from the handler entry points, following first-party
modules, and asserts every third-party top-level module it reaches is provided by
a distribution listed in requirements.txt. Module-to-distribution mapping comes
from installed metadata rather than a hardcoded table, so cases where the import
name differs from the package name (``opensearchpy`` → ``opensearch-py``, ``jwt``
→ ``PyJWT``) resolve correctly.
"""

from __future__ import annotations

import ast
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _find_repo_root(start: Path) -> Path:
    """Walk up to the workspace root (the dir holding both packages/ and libs/)."""
    for candidate in [start, *start.parents]:
        if (candidate / "packages").is_dir() and (candidate / "libs").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate repo root above {start}")


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())
_REQUIREMENTS = _REPO_ROOT / "packages" / "control-plane" / "requirements.txt"

# Source roots bundled into the namespace Lambdas (srcDirs in namespace-stack.ts).
_FIRST_PARTY_ROOTS = {
    "coa_control_plane": _REPO_ROOT / "packages" / "control-plane" / "src",
    "coa_common": _REPO_ROOT / "libs" / "common" / "src",
    "coa_control_plane_server": _REPO_ROOT / "smithy-generated" / "control-plane-python-server" / "src",
}

# Provided by the AWS Lambda Python runtime, so intentionally not in requirements.
_RUNTIME_PROVIDED = {"boto3", "botocore"}

# Lambda handler entry points defined on the shared bundle.
_ENTRY_POINTS = (
    "coa_control_plane.namespace.deletion_pipeline.delete_sources",
    "coa_control_plane.namespace.deletion_pipeline.delete_ontology",
    "coa_control_plane.namespace.deletion_pipeline.delete_metrics",
    "coa_control_plane.namespace.deletion_pipeline.delete_platform",
    "coa_control_plane.namespace.deletion_pipeline.finalize",
    "coa_control_plane.namespace.deletion_pipeline.mark_failed",
    "coa_control_plane.namespace.namespace_api_handler",
)


def _normalize(dist: str) -> str:
    return dist.lower().replace("_", "-")


def _declared_distributions() -> set[str]:
    """Distribution names listed in the Lambda bundle's requirements file."""
    names: set[str] = set()
    for raw in _REQUIREMENTS.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        for sep in (">=", "==", "<=", "~=", ">", "<", "["):
            if sep in line:
                line = line.split(sep, 1)[0]
                break
        names.add(_normalize(line.strip()))
    return names


def _module_path(module: str) -> Path | None:
    """Resolve a first-party dotted module to a file inside a bundled src root."""
    top = module.split(".", 1)[0]
    root = _FIRST_PARTY_ROOTS.get(top)
    if root is None:
        return None
    rel = Path(*module.split("."))
    for candidate in (root / rel.with_suffix(".py"), root / rel / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imports_in(path: Path) -> set[str]:
    """Top-level dotted module names imported at MODULE SCOPE by one file.

    Only module-scope imports are collected, because only those run when Lambda
    imports the handler — and therefore only those can raise
    ``Runtime.ImportModuleError``. Imports nested inside a function, class,
    ``if TYPE_CHECKING`` block, or ``try/except ImportError`` are deliberately
    ignored: they are lazy or guarded, so a missing distribution degrades to a
    failure on one code path instead of killing the whole Lambda. (Concretely,
    ``coa_common.embeddings`` imports ``llama_index`` inside a function for its
    optional LlamaIndex adapter; the namespace Lambdas never call it, so bundling
    llama-index into them would be dead weight.)
    """
    found: set[str] = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def _reachable_third_party() -> dict[str, str]:
    """Third-party top-level module -> the first-party file that pulled it in."""
    seen: set[Path] = set()
    queue = [p for ep in _ENTRY_POINTS if (p := _module_path(ep)) is not None]
    third_party: dict[str, str] = {}

    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for module in _imports_in(path):
            top = module.split(".", 1)[0]
            if top in _FIRST_PARTY_ROOTS:
                if (dep := _module_path(module)) is not None:
                    queue.append(dep)
                continue
            if top in sys.stdlib_module_names:
                continue
            third_party.setdefault(top, str(path.relative_to(_REPO_ROOT)))
    return third_party


class TestNamespaceLambdaBundleDependencies:
    def test_entry_points_exist(self):
        """Guards the walk against silently covering nothing if a handler moves."""
        for ep in _ENTRY_POINTS:
            assert _module_path(ep) is not None, f"Lambda handler entry point not found: {ep}"

    def test_every_third_party_import_is_in_requirements(self):
        declared = _declared_distributions()
        name_to_dists = packages_distributions()
        missing: list[str] = []

        for module, importer in sorted(_reachable_third_party().items()):
            if module in _RUNTIME_PROVIDED:
                continue
            candidates = {_normalize(d) for d in name_to_dists.get(module, [])} or {_normalize(module)}
            if not (candidates & declared):
                missing.append(f"{module} (imported by {importer}; provide one of: {sorted(candidates)})")

        assert not missing, (
            "These modules are imported by the namespace Lambdas but no distribution "
            f"providing them is listed in {_REQUIREMENTS.relative_to(_REPO_ROOT)}:\n  "
            + "\n  ".join(missing)
            + "\n\nThe uv workspace resolves them transitively, so tests and lint pass, but "
            "the deployed bundle installs ONLY that file — the deploy fails at invoke time "
            "with Runtime.ImportModuleError."
        )

    def test_opensearchpy_specifically_is_bundled(self):
        """Regression pin for the import that actually broke a deployment.

        namespace/cleanup.py drops the namespace's AOSS indexes on teardown, and
        every deletion_pipeline handler imports cleanup — so dropping this entry
        breaks four Lambdas, finalize (must-succeed) among them.
        """
        assert "opensearch-py" in _declared_distributions()
        assert "opensearchpy" in _reachable_third_party()
