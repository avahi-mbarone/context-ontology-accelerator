# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Glue catalog-id resolution used by the Redshift-engine integ suite.

The suite previously read ``INTEG_GLUE_CATALOG_ID`` with an empty-string default.
CI never sets that variable, and ``catalogId`` is length-constrained to an AWS
account id, so all four onboarding tests failed on every run with
``400 "String should have at least 12 characters"`` — never reaching the engine
behaviour they exist to check. The resolution is pure logic plus one STS call, so
it is pinned here (CI runs ``tests/unit`` only) rather than discovered on a
deployed environment.

The integ module is loaded by path because ``tests/integ`` is not a package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_MODULE_PATH = Path(__file__).resolve().parents[1] / "integ" / "test_glue_redshift_engine.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("glue_redshift_integ_module", _MODULE_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {_MODULE_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    module = _load()
    module._glue_catalog_id.cache_clear()
    return module


def test_falls_back_to_the_callers_account_when_unset(mod: ModuleType, monkeypatch) -> None:
    """An unset override must resolve from STS, never yield an empty catalogId."""
    monkeypatch.delenv("INTEG_GLUE_CATALOG_ID", raising=False)
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}

    with patch.object(mod.boto3, "client", return_value=sts):
        assert mod._glue_catalog_id() == "123456789012"


def test_resolved_id_satisfies_the_api_length_constraint(mod: ModuleType, monkeypatch) -> None:
    """The regression: a shorter value is rejected 400 before any engine logic runs."""
    monkeypatch.delenv("INTEG_GLUE_CATALOG_ID", raising=False)
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}

    with patch.object(mod.boto3, "client", return_value=sts):
        assert len(mod._glue_catalog_id()) >= 12


def test_explicit_override_wins_and_is_not_overridden_by_sts(mod: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("INTEG_GLUE_CATALOG_ID", "210987654321")
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}

    with patch.object(mod.boto3, "client", return_value=sts) as client:
        assert mod._glue_catalog_id() == "210987654321"
        client.assert_not_called()  # no STS call needed when told the answer


def test_blank_override_is_treated_as_unset(mod: ModuleType, monkeypatch) -> None:
    """A CI variable defined-but-empty must not reintroduce the empty catalogId."""
    monkeypatch.setenv("INTEG_GLUE_CATALOG_ID", "   ")
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}

    with patch.object(mod.boto3, "client", return_value=sts):
        assert mod._glue_catalog_id() == "123456789012"


def test_resolution_is_cached_so_the_suite_makes_one_sts_call(mod: ModuleType, monkeypatch) -> None:
    monkeypatch.delenv("INTEG_GLUE_CATALOG_ID", raising=False)
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}

    with patch.object(mod.boto3, "client", return_value=sts) as client:
        mod._glue_catalog_id()
        mod._glue_catalog_id()
        assert client.call_count == 1
