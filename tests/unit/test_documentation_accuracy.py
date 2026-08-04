# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Test that documentation examples match actual codebase patterns."""

from __future__ import annotations

import re
from pathlib import Path


def test_package_guide_references_real_packages() -> None:
    """Verify that package-guide.md references real packages in the monorepo."""
    package_guide = Path(__file__).parent.parent.parent / "external-docs" / "content" / "package-guide.md"
    packages_dir = Path(__file__).parent.parent.parent / "packages"
    libs_dir = Path(__file__).parent.parent.parent / "libs"

    content = package_guide.read_text()

    parts = content.split("## Packages")
    assert len(parts) >= 2, "package-guide.md must contain a '## Packages' section"
    section_parts = parts[1].split("## Shared Libraries")
    packages_section = section_parts[0]

    package_table_pattern = r"\| `([^`]+)`\s+\|"
    documented_packages = re.findall(package_table_pattern, packages_section)

    existing_packages = {p.name for p in packages_dir.iterdir() if p.is_dir()}

    for pkg in documented_packages:
        assert pkg in existing_packages, f"Package '{pkg}' is documented but doesn't exist in packages/"

    assert "libs/common" in content
    assert (libs_dir / "common").exists()


def test_package_guide_pyproject_example_matches_pattern() -> None:
    """Verify pyproject.toml example matches real package patterns."""
    package_guide = Path(__file__).parent.parent.parent / "external-docs" / "content" / "package-guide.md"
    sources_pyproject = Path(__file__).parent.parent.parent / "packages" / "sources" / "pyproject.toml"

    guide_content = package_guide.read_text()
    real_pyproject = sources_pyproject.read_text()

    assert "[project]" in real_pyproject
    assert "requires-python" in real_pyproject
    assert "[build-system]" in real_pyproject
    assert "[tool.pytest.ini_options]" in real_pyproject
    assert "[tool.uv.sources]" in real_pyproject

    assert "[project]" in guide_content
    assert "[build-system]" in guide_content
    assert "[tool.pytest.ini_options]" in guide_content


def test_package_guide_project_json_example_matches_pattern() -> None:
    """Verify project.json example matches real Nx configuration."""
    package_guide = Path(__file__).parent.parent.parent / "external-docs" / "content" / "package-guide.md"
    sources_project = Path(__file__).parent.parent.parent / "packages" / "sources" / "project.json"

    guide_content = package_guide.read_text()
    real_project_json = sources_project.read_text()

    assert '"lint"' in real_project_json
    assert '"test"' in real_project_json
    assert '"format"' in real_project_json

    assert '"lint"' in guide_content
    assert '"test"' in guide_content
    assert '"format"' in guide_content


def test_package_guide_references_common_lib() -> None:
    """Verify package-guide.md correctly references libs/common utilities."""
    package_guide = Path(__file__).parent.parent.parent / "external-docs" / "content" / "package-guide.md"
    common_src = Path(__file__).parent.parent.parent / "libs" / "common" / "src" / "coa_common"

    guide_content = package_guide.read_text()

    assert "coa_common.config" in guide_content
    assert "coa_common.logging" in guide_content
    assert "coa_common.exceptions" in guide_content
    assert "coa_common.s3" in guide_content
    assert "coa_common.dao" in guide_content
    assert "coa_common.constants" in guide_content

    # Verify the referenced modules actually exist (some are packages, some are .py files)
    for module in ("config", "logging", "exceptions", "s3", "dao", "constants"):
        is_file = (common_src / f"{module}.py").exists()
        is_pkg = (common_src / module / "__init__.py").exists()
        assert is_file or is_pkg, f"libs/common module '{module}' should exist"


def test_workspace_members_registration_matches_reality() -> None:
    """Verify root pyproject.toml workspace matches documented pattern."""
    root_pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"

    content = root_pyproject.read_text()

    assert "[tool.uv.workspace]" in content
    assert "members = [" in content

    assert '"packages/sources"' in content
    assert '"libs/common"' in content


def test_getting_started_package_guide_link_is_valid() -> None:
    """Verify getting-started.md links to package-guide.md correctly."""
    getting_started = Path(__file__).parent.parent.parent / "external-docs" / "content" / "getting-started.md"
    package_guide = Path(__file__).parent.parent.parent / "external-docs" / "content" / "package-guide.md"

    getting_started_content = getting_started.read_text()

    assert "package-guide.md" in getting_started_content
    assert package_guide.exists(), "package-guide.md should exist"

    package_guide_content = package_guide.read_text()
    assert "Adding a New Package" in package_guide_content
    assert "Implementing a Package" in package_guide_content
