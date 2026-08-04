# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Inducer Bedrock clients carry the async backoff config."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_inducer_llm_bedrock_uses_async_config():
    from coa_ontology.inducer.services import llm

    client = llm.LLMClient(region="us-east-1")
    with patch.object(llm.boto3, "client") as mock_client:
        _ = client.client  # triggers lazy construction
        _, kwargs = mock_client.call_args
        assert kwargs["config"].retries["max_attempts"] == 3
        assert kwargs["config"].retries["mode"] == "standard"
        # LLM generation keeps a generous read budget.
        assert kwargs["config"].read_timeout == 120
