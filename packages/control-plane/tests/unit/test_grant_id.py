# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for grant_id encode/decode utility."""

from __future__ import annotations

import base64

import pytest
from coa_control_plane.grants.grant_id import decode_grant_id, encode_grant_id

pytestmark = pytest.mark.unit

VALID_NS_ID = "550e8400-e29b-41d4-a716-446655440000"


class TestEncodeDecodeGrantId:
    def test_roundtrip(self):
        pk = f"Namespace::{VALID_NS_ID}#User::alice@company.com"
        sk = "ROLE#analyst"
        encoded = encode_grant_id(pk, sk)
        decoded_pk, decoded_sk = decode_grant_id(encoded)
        assert decoded_pk == pk
        assert decoded_sk == sk

    def test_url_safe(self):
        pk = f"Namespace::{VALID_NS_ID}#User::alice@company.com"
        sk = "ROLE#analyst"
        encoded = encode_grant_id(pk, sk)
        # No characters that need URL encoding
        assert "+" not in encoded
        assert "/" not in encoded
        assert "=" not in encoded

    def test_deterministic(self):
        pk = f"Namespace::{VALID_NS_ID}#Group::data-team"
        sk = "ROLE#data-steward"
        assert encode_grant_id(pk, sk) == encode_grant_id(pk, sk)

    def test_decode_invalid_base64_raises(self):
        with pytest.raises(ValueError, match="cannot decode"):
            decode_grant_id("not!valid!base64!!!")

    def test_decode_missing_separator_raises(self):
        encoded = base64.urlsafe_b64encode(b"no-separator-here").decode().rstrip("=")
        with pytest.raises(ValueError, match="missing separator"):
            decode_grant_id(encoded)
