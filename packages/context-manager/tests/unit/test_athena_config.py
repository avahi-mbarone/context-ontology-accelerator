# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Athena client carries the sync fail-fast retry/timeout config."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_athena_client_uses_sync_config():
    from coa_serve.clients import athena

    with patch.object(athena.boto3, "client") as mock_client:
        athena.AthenaQueryExecutor(region="us-east-1", sources_registry=object())
        _, kwargs = mock_client.call_args
        cfg = kwargs["config"]
        assert cfg.connect_timeout == 2
        assert cfg.read_timeout == 8
        assert cfg.retries["max_attempts"] == 2
