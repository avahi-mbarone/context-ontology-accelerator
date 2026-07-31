# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""JWT claims extraction from already-validated tokens.

AgentCore Runtime validates JWT (signature, issuer, audience, expiry)
before the request reaches this server. We only extract claims here —
no re-validation of the signature.

See LLD §3.2.5 and AWS docs: "Skip signature validation as agent runtime
has validated the token already."
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CallerIdentity:
    """Extracted identity from the JWT claims."""

    user_id: str
    agent_id: str | None
    namespaces: list[str]
    roles: list[str]
    raw_claims: dict


class ClaimsExtractionError(Exception):
    """Raised when required claims cannot be extracted."""


def extract_caller_identity(authorization_header: str | None) -> CallerIdentity:
    """Extract delegating user identity from an already-validated JWT.

    The AgentCore Runtime has already validated the token's signature,
    issuer, audience, and expiry. This function only decodes the payload
    to extract the delegating user identity.

    Args:
        authorization_header: The full Authorization header value (e.g., "Bearer <token>").

    Returns:
        CallerIdentity with the delegating user's info.

    Raises:
        ClaimsExtractionError: If the header is missing, malformed, or lacks required claims.
    """
    if not authorization_header:
        raise ClaimsExtractionError("Missing Authorization header")

    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ClaimsExtractionError("Authorization header must be 'Bearer <token>'")

    token = parts[1]

    try:
        # Do NOT verify signature — AgentCore Runtime already did this.
        # We DO verify exp locally: it's cheap and adds defense in depth
        # (guards against clock skew between platform and this service).
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": True,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except jwt.ExpiredSignatureError as e:
        raise ClaimsExtractionError(f"JWT has expired: {e}") from e
    except jwt.DecodeError as e:
        raise ClaimsExtractionError(f"Failed to decode JWT: {e}") from e

    # Extract delegating user identity (the user who authorized the agent)
    user_id = claims.get("sub") or claims.get("user_id") or claims.get("username")
    if not user_id:
        raise ClaimsExtractionError("JWT lacks required 'sub' / 'user_id' claim for delegating user")

    # Agent identity — logged for audit but NOT used for authorization
    agent_id = claims.get("agent_id") or claims.get("client_id") or claims.get("azp")

    # Namespace access (from custom claims or scope)
    namespaces = _extract_list_claim(claims, "namespaces", "custom:namespaces", "scl_namespaces")

    # Roles
    roles = _extract_list_claim(claims, "roles", "custom:roles", "scl_roles", "cognito:groups")

    logger.info(
        "caller_identity_extracted",
        user_id=user_id,
        agent_id=agent_id,
        namespace_count=len(namespaces),
    )

    return CallerIdentity(
        user_id=user_id,
        agent_id=agent_id,
        namespaces=namespaces,
        roles=roles,
        raw_claims=claims,
    )


def _extract_list_claim(claims: dict, *keys: str) -> list[str]:
    """Try multiple claim keys, return the first non-empty list found."""
    for key in keys:
        value = claims.get(key)
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str) and value:
            return [v.strip() for v in value.split(",") if v.strip()]
    return []
