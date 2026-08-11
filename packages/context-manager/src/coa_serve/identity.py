# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Identity resolution for the invoke entrypoint.

Trust Model
-----------
There are two trusted sources of user identity, depending on the caller:

1. **JWT in Authorization header** (highest trust): AgentCore validates the JWT
   (signature, expiry, audience) before forwarding the request. We decode without
   signature check because AgentCore already did that. This gives us the 'sub'
   (user_id) and 'email' claims. The data-layer Lambda also forwards the original
   JWT when invoking via AgentCore, so JWT is always present for authenticated callers.

2. **profile.userId** (fallback only): For any future internal caller that invokes
   the runtime without forwarding a Bearer token. This path should NOT override
   a validated JWT since the request body is attacker-controlled for direct callers.

Priority: JWT sub > JWT email > profile.userId. The JWT takes precedence because
it is cryptographically validated by AgentCore before the request reaches this code.
The profile path is a fallback for edge cases where no JWT is forwarded.

_resolve_user_id does NOT perform token validation itself. It trusts that
upstream infrastructure (AgentCore Runtime) already verified the token before
the request reached this code.
"""

from __future__ import annotations

import structlog

from .auth import TokenClaims

logger = structlog.get_logger(__name__)


def extract_jwt_identity(context) -> tuple[str, str, list[str]]:
    """Extract user identity from the AgentCore request context.

    Returns (user_id, email, groups) from the JWT forwarded by AgentCore.
    AgentCore validates the token before forwarding, so we only decode.
    Returns empty strings/list if context is None or extraction fails.
    """
    if not context:
        return "", "", []

    try:
        claims = TokenClaims.from_request_context(context)
        if claims:
            return claims.user_id, claims.email, claims.groups
    except Exception as e:
        logger.warning("jwt_extraction_failed", error=str(e), context_type=type(context).__name__)

    return "", "", []


def resolve_user_id(payload: dict, jwt_user_id: str, jwt_email: str) -> str:
    """Resolve the authoritative user ID with explicit priority.

    Priority order (JWT is authoritative when present):
    1. JWT sub (user_id) - from AgentCore-validated Bearer token
    2. JWT email - fallback when sub is unavailable
    3. profile.userId - fallback for internal callers without JWT forwarding

    This function does not validate tokens. Validation is performed by
    AgentCore Runtime before the request reaches this code.
    """
    if jwt_user_id:
        return jwt_user_id
    if jwt_email:
        return jwt_email
    profile = payload.get("profile") or {}
    return profile.get("userId", "") if isinstance(profile, dict) else ""


def display_principal(profile: dict | None) -> str | None:
    """Human-readable caller identity for response metadata and trace details.

    ``profile["userId"]`` is the JWT ``sub`` — a Cognito UUID or equivalent, and
    the right key for grant lookup, Cedar, and session tracking, since it is the
    one claim every IdP guarantees. It means nothing to the person reading it, so
    prefer the ``email`` claim when the role resolver injected one: the Playground
    renders these values verbatim, and "alice@example.com" tells the reader whose
    grants produced the answer where a UUID does not.

    A display label only — it never feeds authorization, which reads ``userId``.
    The substitution is honest rather than cosmetic: email IS a principal identity
    in the grant model (:func:`role_resolver.build_principal_keys` resolves grants
    under both ``User::<sub>`` and ``User::<email>``), so the two name the same
    principal. Only the JWT-derived email reaches the profile — ``main.py`` strips
    a client-supplied ``email`` before ``ResolvedProfile.inject_into`` writes the
    validated one — so this cannot be spoofed by the request body.

    Accepts ``None`` so no call site needs its own ``profile or {}`` guard;
    forgetting that guard is what kept the Tier-3 paths on the raw sub.
    """
    p = profile or {}
    return p.get("email") or p.get("userId")
