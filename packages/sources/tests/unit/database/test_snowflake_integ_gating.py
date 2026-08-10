# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Snowflake integ suite's failure classifier.

The classifier decides whether a red Snowflake integ run is a REGRESSION or a
dead trial account, so getting it wrong is expensive in both directions: too
broad and it swallows the defects the suite exists to catch, too narrow and the
pipeline reports a code failure nobody can fix. It is pure string logic, so it
is tested here (CI runs only ``tests/unit``) rather than left to a run that
needs a live Snowflake account.

The integ module is loaded by path because ``tests/integ`` is not a package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_MODULE_PATH = Path(__file__).resolve().parents[2] / "integ" / "test_sources_snowflake_integ.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("snowflake_integ_module", _MODULE_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {_MODULE_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mod = _load()


@pytest.mark.parametrize(
    "message",
    [
        "Your trial has ended. Please add a payment method.",
        "250001 (08001): Incorrect username or password was specified.",
        "Account is suspended due to lack of a payment method",
        "The account has been locked",
        "User access is disabled",
    ],
)
def test_account_level_failures_are_recognised(message: str) -> None:
    """These are environment death: no change to this repo can make them pass."""
    assert _mod._account_unavailable_reason(message) is not None


@pytest.mark.parametrize(
    "message",
    [
        # The three defects the suite exists to catch — must NEVER be tolerated.
        "InvalidInputException: [WAREHOUSE are missing in the request object]",
        "InvalidInputException: [ROLE are not allowed in the request object.]",
        "Warehouse 'COMPUTE_WH' does not exist or not authorized.",
        "Snowflake federation requires a warehouse: set jdbcConfiguration.warehouse on the source.",
        # Ordinary breakage that should stay red.
        "Could not connect: timed out after 30s",
        "AccessDeniedException: secretsmanager:GetSecretValue",
        "",
    ],
)
def test_real_failures_are_not_tolerated(message: str) -> None:
    assert _mod._account_unavailable_reason(message) is None


def test_missing_error_message_is_not_tolerated() -> None:
    """A failure with no message is unexplained, so it must stay a failure.

    This also covers the case where the scan-job lookup could not retrieve a
    message at all (helper returns ""): unexplained stays red rather than being
    quietly attributed to an expired trial.
    """
    assert _mod._account_unavailable_reason("") is None
    assert _mod._account_unavailable_reason(None) is None  # type: ignore[arg-type]


def test_matching_is_case_insensitive() -> None:
    assert _mod._account_unavailable_reason("ACCOUNT IS SUSPENDED") is not None


def test_skip_helper_skips_only_on_account_failure() -> None:
    """The skip path fires for a dead account and stays out of the way otherwise."""
    with pytest.raises(BaseException) as excinfo:
        _mod._skip_if_account_unavailable("Your trial has ended")
    assert "Snowflake account unavailable" in str(excinfo.value)

    # A genuine failure returns cleanly so the caller's assertion runs and fails.
    assert (
        _mod._skip_if_account_unavailable("InvalidInputException: [WAREHOUSE are missing in the request object]")
        is None
    )
