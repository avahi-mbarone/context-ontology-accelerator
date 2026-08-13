# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for constructing DynamoDB principal key components.

Grants are stored in the ResourceRoleMappings table keyed by ``principalKey``
(e.g. ``User::alice@example.com``). Both the writers (grant-creation handlers)
and the readers (the API authorizer and the serve-layer role resolver) must
encode the principal identifier identically, or a grant written under one
encoding will never be found under another.

writers stored raw identifiers while the authorizer queried
URL-encoded ones, so grants for emails with special characters (e.g.
``foo+123@example.com``) were silently unresolvable. Centralizing the encoding
here ensures every read and write site stays in lockstep.
"""

from __future__ import annotations

import urllib.parse


def sanitize_principal_key(value: str) -> str:
    """URL-encode a value used as a DynamoDB principal key component.

    Encodes characters that would otherwise corrupt the ``<type>::<id>`` key
    layout (e.g. ``+``, ``#``, ``/``) while leaving ``@`` and ``.`` intact so
    that email addresses remain human-readable in the stored keys.

    Identifiers containing ``@`` — treated as email addresses by convention
    across this codebase — are lowercased and stripped before encoding, so
    ``Alice@Example.com`` and ``alice@example.com`` produce the same key.
    Emails have case-insensitive local-part semantics in practice and every
    IdP we support (Cognito, Okta, EntraID) emits them with case that varies
    between the ``email`` claim and the user-pool records. Without this
    normalization, a grant written by the UI under one case would be invisible
    to a reader query built from the JWT emitted in another — the exact
    silent-miss failure mode this centralization exists to prevent.

    Non-email identifiers (Cognito ``sub`` UUIDs, group names, arbitrary
    principal ids) are passed through verbatim: ``sub`` is opaque and
    case-sensitive, and group names may intentionally be mixed-case.

    This must be the single source of truth for principal-key encoding across
    every writer and reader of the ResourceRoleMappings table.
    """
    if "@" in value:
        value = value.strip().lower()
    return urllib.parse.quote(value, safe="@.")


def build_principal_keys(
    *,
    user_id: str,
    email: str,
    groups: list[str],
) -> list[str]:
    """Build the PrincipalIndex GSI lookup keys for a caller.

    Grants can be written under any identifier the caller presents at query
    time (sub, email, group membership). Every known identifier is included
    so a grant written under one form resolves regardless of which identifier
    the JWT primarily surfaces. Duplicates (e.g. sub == email post-encoding)
    are collapsed to keep the DDB query count at the minimum.

    Every reader of the ResourceRoleMappings PrincipalIndex GSI must use this
    helper. Skipping the email lookup or hardcoding a single principal form
    silently hides grants written under the omitted identifier — the same
    class of bug that landed the MCP-server grant resolver in production
    returning "No grants found" for otherwise-authorized users.

    Case-insensitivity for emails is handled by :func:`sanitize_principal_key`
    (an identifier containing ``@`` is strip+lowered before encoding), so
    writers and readers converge on the same key regardless of the case the
    JWT / grant form supplied.

    Args:
        user_id: The JWT sub (or upstream fallback identifier).
        email: The JWT email claim; empty when the token has none.
        groups: The caller's group memberships from the JWT.

    Returns:
        Ordered list of ``User::…`` and ``Group::…`` keys, deduplicated.
        Order matters only for readability of downstream logs — grants under
        every key are merged equally by the caller.
    """
    seen: set[str] = set()
    keys: list[str] = []
    for identifier in (user_id, email):
        if not identifier:
            continue
        key = f"User::{sanitize_principal_key(identifier)}"
        if key not in seen:
            seen.add(key)
            keys.append(key)
    for group in groups:
        key = f"Group::{sanitize_principal_key(group)}"
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys
