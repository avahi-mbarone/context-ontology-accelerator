# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Env-tunability guard for the first-pass grounding/rerank ThreadPool width.

The first-pass grounding pool in ``match_concepts`` sizes its width via a tuned
constant (default 24), with ``INDUCER_GROUNDING_WORKERS`` as an escape hatch for
sweeps. This locks the tuned default AND that the env var still overrides it, so
the load-test duration lever stays wired up. The default is coupled to the
shared bedrock client's connection cap (see test_grounding_pool.py).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from coa_ontology.inducer.services.pipeline import _grounding_workers


def test_grounding_workers_defaults_to_24(monkeypatch) -> None:
    monkeypatch.delenv("INDUCER_GROUNDING_WORKERS", raising=False)
    assert _grounding_workers() == 24


def test_grounding_workers_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("INDUCER_GROUNDING_WORKERS", "32")
    assert _grounding_workers() == 32


def test_grounding_workers_reads_small_override(monkeypatch) -> None:
    monkeypatch.setenv("INDUCER_GROUNDING_WORKERS", "4")
    assert _grounding_workers() == 4
