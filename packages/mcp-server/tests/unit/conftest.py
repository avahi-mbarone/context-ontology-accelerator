# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared test fixtures for unit tests."""

from __future__ import annotations

import time

import jwt
import pytest


def create_test_token(
    user_id: str = "test-user",
    agent_id: str = "test-agent",
    namespaces: list[str] | None = None,
    roles: list[str] | None = None,
    exp_offset: int = 3600,
) -> str:
    """Create a signed test JWT for local development/testing.

    Args:
        user_id: Subject claim (delegating user).
        agent_id: Agent identity claim.
        namespaces: Namespace access list.
        roles: Role claims.
        exp_offset: Seconds from now until token expires (default 1 hour).

    Returns:
        Encoded JWT string.
    """
    payload = {
        "sub": user_id,
        "agent_id": agent_id,
        "namespaces": namespaces or ["default"],
        "roles": roles or ["viewer"],
        "iss": "test-issuer",
        "aud": "test-audience",
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, "test-secret", algorithm="HS256")


@pytest.fixture
def test_token_factory():
    """Fixture providing a factory for test JWT tokens."""
    return create_test_token
