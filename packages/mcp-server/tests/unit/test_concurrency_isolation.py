# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Concurrency isolation tests: verifies the CM client doesn't leak state.

Ensures parallel requests with different tokens are forwarded
independently to the Context Manager (no cross-contamination).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from coa_mcp.tools.execution import execute_query


@pytest.mark.unit
class TestConcurrencyIsolation:
    """Ensure no identity bleed across concurrent requests."""

    @pytest.mark.asyncio
    async def test_parallel_requests_use_separate_tokens(self):
        """Two concurrent CM invocations with different tokens must not cross-contaminate."""
        captured_calls: list = []

        async def capture_invoke(payload, bearer_token):
            captured_calls.append({"payload": payload, "bearer_token": bearer_token})
            await asyncio.sleep(0.01)
            return {"result": {"tier": 2, "confidence": {"score": 0.9, "rationale": "test"}, "resultRows": []}}

        mock_cm = AsyncMock()
        mock_cm.invoke = AsyncMock(side_effect=capture_invoke)

        profile_a = {"namespace": "sales", "userId": "user-a", "globalRoles": ["viewer"]}
        profile_b = {"namespace": "hr", "userId": "user-b", "globalRoles": ["viewer"]}

        await asyncio.gather(
            execute_query(mock_cm, "revenue", "sales", profile_a, "token-a"),
            execute_query(mock_cm, "headcount", "hr", profile_b, "token-b"),
        )

        assert len(captured_calls) == 2

        tokens_seen = [c["bearer_token"] for c in captured_calls]
        assert "token-a" in tokens_seen
        assert "token-b" in tokens_seen

        namespaces_seen = [c["payload"]["namespace"] for c in captured_calls]
        assert "sales" in namespaces_seen
        assert "hr" in namespaces_seen

    @pytest.mark.asyncio
    async def test_bearer_tokens_forwarded_independently(self):
        """Each call must forward its own bearer token."""
        captured_tokens: list = []

        async def capture_token(payload, bearer_token):
            captured_tokens.append(bearer_token)
            return {"result": {"tier": 1, "confidence": {"score": 1.0, "rationale": "test"}, "resultRows": []}}

        mock_cm = AsyncMock()
        mock_cm.invoke = AsyncMock(side_effect=capture_token)

        await asyncio.gather(
            execute_query(mock_cm, "q1", "ns", {}, "token-user-A"),
            execute_query(mock_cm, "q2", "ns", {}, "token-user-B"),
        )

        assert "token-user-A" in captured_tokens
        assert "token-user-B" in captured_tokens

    @pytest.mark.asyncio
    async def test_namespace_is_per_call_not_cached(self):
        """Each call must use its own namespace in the payload."""
        mock_cm = AsyncMock()
        mock_cm.invoke = AsyncMock(
            return_value={"result": {"tier": 1, "confidence": {"score": 1.0, "rationale": "test"}, "resultRows": []}}
        )

        await execute_query(mock_cm, "q1", "ns-alpha", {}, "tok1")
        await execute_query(mock_cm, "q2", "ns-beta", {}, "tok2")

        call1_payload = mock_cm.invoke.call_args_list[0][0][0]
        call2_payload = mock_cm.invoke.call_args_list[1][0][0]
        assert call1_payload["namespace"] == "ns-alpha"
        assert call2_payload["namespace"] == "ns-beta"
