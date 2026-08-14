# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared test fixtures for unit tests.

``create_test_token`` produces a genuinely RS256-signed JWT (not the old
unsigned-HS256 stub) because ``extract_caller_identity`` now performs real
signature verification (see auth/claims.py — defense-in-depth behind
AgentCore's own JWT authorizer). ``_mock_jwks`` is an autouse fixture that
points the claims-module authorizer's JWKS lookup at the matching public key,
so every test in this package gets a working verifier without repeating the
mock setup per test.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

_TEST_KID = "test-kid-1"
_TEST_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool"
_TEST_AUDIENCE = "test-audience"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk() -> dict[str, Any]:
    public_numbers = _private_key.public_key().public_numbers()

    def _int_to_base64url(n: int, length: int) -> str:
        return jwt.utils.base64url_encode(n.to_bytes(length, byteorder="big")).decode()

    return {
        "kty": "RSA",
        "kid": _TEST_KID,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(public_numbers.n, 256),
        "e": _int_to_base64url(public_numbers.e, 3),
    }


def create_test_token(
    user_id: str = "test-user",
    agent_id: str = "test-agent",
    namespaces: list[str] | None = None,
    roles: list[str] | None = None,
    exp_offset: int = 3600,
    *,
    issuer: str = _TEST_ISSUER,
    audience: str = _TEST_AUDIENCE,
    email: str | None = None,
) -> str:
    """Create a signed test JWT for local development/testing.

    Signed with a real RSA key matching the JWKS served by the ``_mock_jwks``
    autouse fixture, so ``extract_caller_identity``'s signature check passes
    for legitimately-constructed test tokens.

    Args:
        user_id: Subject claim (delegating user).
        agent_id: Agent identity claim.
        namespaces: Namespace access list.
        roles: Role claims (mapped to ``cognito:groups`` — the test issuer is
            shaped like a Cognito user pool, matching production's IdP).
        exp_offset: Seconds from now until token expires (default 1 hour).
        issuer: ``iss`` claim. Override to test issuer-mismatch rejection.
        audience: ``aud`` claim. Override to test audience-mismatch rejection.
        email: Optional ``email`` claim. Omitted from the payload when ``None``
            (matches Cognito access tokens, which do not carry email); set to
            an address to exercise the email-plumbing path.

    Returns:
        Encoded JWT string.
    """
    payload = {
        "sub": user_id,
        "agent_id": agent_id,
        "namespaces": namespaces or ["default"],
        "cognito:groups": roles or ["viewer"],
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + exp_offset,
    }
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, _private_key, algorithm="RS256", headers={"kid": _TEST_KID})


@pytest.fixture
def test_token_factory():
    """Fixture providing a factory for test JWT tokens."""
    return create_test_token


@pytest.fixture(autouse=True)
def _mock_jwks(monkeypatch):
    """Point claims.py's authorizer at the test JWKS instead of a real network call.

    Sets the env vars claims.py's ``_get_authorizer()`` reads, clears its
    ``lru_cache`` so each test gets a fresh authorizer bound to the current
    monkeypatched env, and mocks the JWKS fetch to return the test key.
    """
    from coa_mcp.auth import claims

    monkeypatch.setenv("JWT_ISSUER_URL", _TEST_ISSUER)
    monkeypatch.setenv("JWT_CLIENT_ID", _TEST_AUDIENCE)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    claims._get_authorizer.cache_clear()

    authorizer = claims._get_authorizer()
    monkeypatch.setattr(authorizer, "_get_jwks", lambda: {"keys": [_jwk()]})

    yield

    claims._get_authorizer.cache_clear()
