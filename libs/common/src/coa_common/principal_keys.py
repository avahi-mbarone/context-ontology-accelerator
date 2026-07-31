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

    This must be the single source of truth for principal-key encoding across
    every writer and reader of the ResourceRoleMappings table.
    """
    return urllib.parse.quote(value, safe="@.")
