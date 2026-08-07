# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for libs/common unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_cloudwatch():
    """Keep guardrail decision metrics off the real CloudWatch API.

    Every guardrail allow/block decision emits metrics now, so any test
    exercising a decision path would otherwise build a real client and let
    ``put_metric_data`` retry against the network. Emission swallows its own
    errors, so this is about test speed and noise, not correctness. Tests that
    assert on the emitted metrics patch the same seam with their own mock.
    """
    with patch("coa_common.guardrail_metrics._cloudwatch_client", return_value=MagicMock()) as factory:
        yield factory
