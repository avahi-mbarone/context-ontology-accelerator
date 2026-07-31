# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Grant ID encoding — derives external ID from DynamoDB PK+SK."""

from __future__ import annotations

import base64

_SEPARATOR = "|"


def encode_grant_id(pk: str, sk: str) -> str:
    """Encode PK+SK into a URL-safe opaque grant identifier."""
    return base64.urlsafe_b64encode(f"{pk}{_SEPARATOR}{sk}".encode()).decode().rstrip("=")


def decode_grant_id(grant_id: str) -> tuple[str, str]:
    """Decode a grant identifier back into (PK, SK).

    Raises ValueError on any malformed input.
    """
    try:
        padded = grant_id + "=" * (-len(grant_id) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid grant ID: cannot decode") from exc
    parts = decoded.split(_SEPARATOR, 1)
    if len(parts) != 2:
        raise ValueError("Invalid grant ID format: missing separator")
    return parts[0], parts[1]
