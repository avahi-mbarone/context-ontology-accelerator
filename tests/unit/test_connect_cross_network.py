# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for connect-cross-network.sh's failure handling.

The script rewrites a live VPC's return routes and DB security group. Its one
unrecoverable failure mode is not an error — it is *reporting success having
wired nothing*, because the next thing to fail is an integration test timing out
against a database, several jobs later, with no hint that the wiring step was
the cause.

`set -euo pipefail` covers the ordinary cases (a failed `aws` command, a failed
command substitution). It does NOT cover `mapfile < <(aws ...)`: process
substitution runs in a child whose exit status the parent never observes, so a
failed peering describe silently read back as an empty array — which the script
interprets as "no peering exists yet, nothing to wire" and exits 0.

The `aws` CLI is stubbed on PATH, so these tests make no AWS calls.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "tests" / "cdk" / "scripts" / "connect-cross-network.sh"

# `tests/unit/` is published to the public mirror but `tests/cdk/` is not (see the
# allowlist in .npmignore), so the script under test is absent there.
if not _SCRIPT.exists():
    pytest.skip("tests/cdk/ is absent from this checkout (public mirror)", allow_module_level=True)

# The script uses `mapfile`, so it needs bash 4+ (macOS ships 3.2 at /bin/bash;
# its shebang is `env bash`, which finds a modern one when installed).
_HAS_BASH4 = (
    subprocess.run(["bash", "-c", "type -t mapfile"], capture_output=True, text=True, check=False).stdout.strip()
    == "builtin"
)

# Stub `aws`: succeeds for the two discovery calls the script makes before the
# peering lookup, then fails the peering describe the way a real API error does
# (non-zero exit, message on stderr, nothing on stdout).
_AWS_STUB = """#!/usr/bin/env bash
args="$*"
case "$args" in
  *"cloudformation describe-stacks"*) echo "vpc-0test" ;;
  *"describe-security-groups"*)       echo "sg-0test" ;;
  *"describe-vpc-peering-connections"*)
    echo "An error occurred (RequestExpired) when calling the DescribeVpcPeeringConnections operation" >&2
    exit 255
    ;;
  *) echo "STUB: unexpected call: $args" >&2; exit 99 ;;
esac
"""


@pytest.fixture
def stub_aws_path(tmp_path: Path) -> str:
    """A PATH whose `aws` is the stub above, with the real shell utils still present."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "aws"
    stub.write_text(_AWS_STUB)
    stub.chmod(0o755)
    return f"{stub_dir}{os.pathsep}{os.environ['PATH']}"


@pytest.mark.skipif(not _HAS_BASH4, reason="script requires bash 4+ (mapfile)")
def test_failed_peering_describe_aborts_instead_of_reporting_nothing_to_wire(
    stub_aws_path: str,
) -> None:
    """An API failure must not be read as "no peering exists" and exit 0.

    Pre-fix this ran the describe inside `mapfile < <(...)`, so the failure was
    invisible: exit 0, "skipping cross-network wiring", nothing configured.
    """
    result = subprocess.run(
        [str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": stub_aws_path},
    )

    assert result.returncode != 0, (
        f"a failed peering describe exited 0.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "skipping cross-network wiring" not in result.stdout
    assert "Cross-network connectivity wired" not in result.stdout


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_script_passes_shellcheck() -> None:
    """No unquoted-expansion / masked-return-value regressions in the script."""
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
