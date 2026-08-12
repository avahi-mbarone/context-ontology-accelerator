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


# ── --peer-stack-name: resolve the requester by stack instead of raw id ────────

_DATA_VPC = "vpc-0data"
_CHOSEN_VPC = "vpc-0chosen"
_OTHER_VPC = "vpc-0other"
_CHOSEN_PCX = "pcx-0chosen"
_OTHER_PCX = "pcx-0other"

# Two peerings into one data VPC — the shape that made the demo pipeline's
# configure-peering job fail. `coa-demo-network` resolves to the second one.
_AWS_STUB_TWO_PEERINGS = f"""#!/usr/bin/env bash
args="$*"
case "$args" in
  *"describe-stacks"*"coa-demo-network"*)  echo "{_CHOSEN_VPC}" ;;
  *"describe-stacks"*)                     echo "{_DATA_VPC}" ;;
  *"describe-security-groups"*)            echo "sg-0test" ;;
  *"--vpc-peering-connection-ids"*)        echo "active" ;;
  *"describe-vpc-peering-connections"*)
    printf '%s\\t%s\\n' "{_OTHER_PCX}" "{_OTHER_VPC}"
    printf '%s\\t%s\\n' "{_CHOSEN_PCX}" "{_CHOSEN_VPC}"
    ;;
  *"describe-subnets"*)                    echo "10.9.0.0/24" ;;
  *"--route-table-ids"*)                   echo "None" ;;
  *"describe-route-tables"*)               echo "rtb-0test" ;;
  *"create-route"*)                        echo "{{}}" ;;
  *"authorize-security-group-ingress"*)    echo "{{}}" ;;
  *) echo "STUB: unexpected call: $args" >&2; exit 99 ;;
esac
"""


@pytest.fixture
def stub_aws_two_peerings(tmp_path: Path) -> str:
    """A PATH whose `aws` reports two peerings into the data VPC."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "aws"
    stub.write_text(_AWS_STUB_TWO_PEERINGS)
    stub.chmod(0o755)
    return f"{stub_dir}{os.pathsep}{os.environ['PATH']}"


@pytest.mark.skipif(not _HAS_BASH4, reason="script requires bash 4+ (mapfile)")
def test_peer_stack_name_selects_that_deployments_peering(stub_aws_two_peerings: str) -> None:
    """`--peer-stack-name` resolves the stack's VpcId and wires only that peering.

    Two peerings is otherwise a hard error ("refusing to guess"), which is what
    broke the demo pipeline: the caller knew which deployment it had just
    deployed but had no way to say so.
    """
    result = subprocess.run(
        [str(_SCRIPT), "--peer-stack-name", "coa-demo-network"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": stub_aws_two_peerings},
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "refusing to guess" not in result.stderr
    assert _CHOSEN_PCX in result.stdout
    assert _OTHER_PCX not in result.stdout, "wired the peering belonging to another deployment"


@pytest.mark.skipif(not _HAS_BASH4, reason="script requires bash 4+ (mapfile)")
def test_two_peerings_without_a_flag_aborts_and_lists_the_candidates(stub_aws_two_peerings: str) -> None:
    """The refusal is only actionable if it names what to choose between."""
    result = subprocess.run(
        [str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": stub_aws_two_peerings},
    )

    assert result.returncode != 0
    assert "refusing to guess" in result.stderr
    for expected in (_CHOSEN_PCX, _CHOSEN_VPC, _OTHER_PCX, _OTHER_VPC):
        assert expected in result.stderr, f"{expected} missing from the candidate list"


@pytest.mark.skipif(not _HAS_BASH4, reason="script requires bash 4+ (mapfile)")
def test_peer_stack_name_without_a_vpcid_output_is_an_error(tmp_path: Path) -> None:
    """A stack name that resolves to nothing must abort, not fall back to guessing."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "aws"
    stub.write_text('#!/usr/bin/env bash\necho "None"\n')
    stub.chmod(0o755)

    result = subprocess.run(
        [str(_SCRIPT), "--peer-stack-name", "typo-network"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "could not resolve a VpcId output" in result.stderr


@pytest.mark.skipif(not _HAS_BASH4, reason="script requires bash 4+ (mapfile)")
def test_both_peer_flags_together_is_an_error() -> None:
    """They name the same thing; a silent precedence rule wires the wrong VPC."""
    result = subprocess.run(
        [str(_SCRIPT), "--peer-stack-name", "coa-demo-network", "--peer-vpc-id", _OTHER_VPC],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "not both" in result.stderr


# ── Every CI caller must disambiguate ─────────────────────────────────────────


def _script_invocations(text: str) -> list[str]:
    """Each `connect-cross-network.sh ...` call as one string, backslash continuations joined."""
    lines = text.splitlines()
    calls: list[str] = []
    for i, line in enumerate(lines):
        if "connect-cross-network.sh" not in line:
            continue
        block = [line]
        j = i
        while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
            j += 1
            block.append(lines[j])
        calls.append("\n".join(block))
    return calls


def test_every_ci_invocation_names_the_deployment_to_wire() -> None:
    """A CI caller that does not disambiguate is a job that fails the first time
    a second deployment peers into the same data VPC.

    The script refuses to guess between multiple peerings — correct, since it
    rewrites the data VPC's return routes and DB security group for whichever
    requester it picks. That refusal is only actionable if every automated caller
    already says which deployment it means. The demo pipeline's
    `demo-3-configure-peering` did not, and failed as soon as a second deployment
    was peered in.
    """
    ci_dir = _REPO_ROOT / "ci"
    undisambiguated: list[str] = []
    checked = 0
    for ci_file in sorted(ci_dir.glob("*.yml")):
        for call in _script_invocations(ci_file.read_text()):
            checked += 1
            if "--peer-stack-name" not in call and "--peer-vpc-id" not in call:
                undisambiguated.append(f"{ci_file.name}: {call.splitlines()[0].strip()}")

    assert checked, "no CI invocations found — the scan itself is broken"
    assert not undisambiguated, (
        "these CI invocations of connect-cross-network.sh do not say which deployment "
        f"to wire, so they break as soon as the data VPC has a second peering: {undisambiguated}"
    )
