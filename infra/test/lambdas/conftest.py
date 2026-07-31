# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for VKG reload Lambda tests.

Patch the boto3 factory to mock the cloudwatch client so it survives the in-test
`importlib.reload(index)` and never makes real PutMetricData calls.
"""

from unittest.mock import MagicMock

import boto3
import pytest


@pytest.fixture(autouse=True)
def _mock_cloudwatch_client(monkeypatch):
    real_client = boto3.client

    def fake_client(name, *args, **kwargs):
        if name == "cloudwatch":
            return MagicMock()
        return real_client(name, *args, **kwargs)

    monkeypatch.setattr(boto3, "client", fake_client)
