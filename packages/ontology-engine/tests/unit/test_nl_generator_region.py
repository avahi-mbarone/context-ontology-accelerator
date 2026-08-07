# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Region defaulting for the ontology-shape NL generation Bedrock call.

The ontology ECS task sets ``BEDROCK_REGION``/``LLM_REGION`` but NOT
``AWS_REGION`` (:func:`_default_bedrock_region`). If the default resolved to
``resolve_region()`` alone it would silently misfile the guardrail decision
metrics to ``us-east-1`` while the LLM call ran in the deployed region. These
tests pin the precedence ``BEDROCK_REGION → LLM_REGION → resolve_region()`` so a
regression surfaces here instead of on an empty dashboard.
"""

from __future__ import annotations

import pytest
from coa_ontology.validation.shapes.nl_generator import _default_bedrock_region

pytestmark = pytest.mark.unit

_REGION_ENV_VARS = ("BEDROCK_REGION", "LLM_REGION", "AWS_REGION", "AWS_DEFAULT_REGION")


@pytest.fixture(autouse=True)
def _clean_region_env(monkeypatch):
    """Start every case from no region env at all so precedence is unambiguous."""
    for var in _REGION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def test_bedrock_region_wins_over_everything(monkeypatch):
    # All four set; BEDROCK_REGION is the most specific and must win.
    monkeypatch.setenv("BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("LLM_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
    assert _default_bedrock_region() == "us-west-2"


def test_llm_region_used_when_bedrock_region_absent(monkeypatch):
    monkeypatch.setenv("LLM_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    assert _default_bedrock_region() == "eu-west-1"


def test_falls_back_to_resolve_region_aws_region(monkeypatch):
    # No BEDROCK_REGION/LLM_REGION → resolve_region() picks up AWS_REGION.
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    assert _default_bedrock_region() == "ap-south-1"


def test_falls_back_to_resolve_region_aws_default_region(monkeypatch):
    # resolve_region() honours AWS_DEFAULT_REGION when AWS_REGION is unset — a
    # lone os.getenv("AWS_REGION", ...) at this call site would have missed it.
    monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
    assert _default_bedrock_region() == "sa-east-1"


def test_final_fallback_is_resolve_region_default(monkeypatch):
    # Nothing set anywhere → the resolve_region() built-in default.
    assert _default_bedrock_region() == "us-east-1"


def test_empty_bedrock_region_does_not_shadow_llm_region(monkeypatch):
    # An empty string is falsy, so precedence must skip to LLM_REGION rather than
    # returning "" (which would build a client for a bogus region).
    monkeypatch.setenv("BEDROCK_REGION", "")
    monkeypatch.setenv("LLM_REGION", "eu-west-1")
    assert _default_bedrock_region() == "eu-west-1"
