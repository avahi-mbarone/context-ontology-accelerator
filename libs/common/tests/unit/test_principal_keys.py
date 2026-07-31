# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared principal-key sanitizer.

This helper is the single source of truth for encoding principal identifiers
into DynamoDB key components. Every writer (grant handlers) and reader (API
authorizer, serve-layer role resolver) depends on it producing identical
output, so these tests pin the exact encoding contract.
"""

from __future__ import annotations

import pytest
from coa_common import sanitize_principal_key


@pytest.mark.unit
class TestSanitizePrincipalKey:
    def test_plain_email_is_unchanged(self):
        assert sanitize_principal_key("alice@example.com") == "alice@example.com"

    def test_at_and_dot_are_preserved(self):
        # ``@`` and ``.`` are kept raw so emails stay human-readable in keys.
        assert sanitize_principal_key("first.last@sub.example.com") == "first.last@sub.example.com"

    def test_plus_is_encoded(self):
        # The case: ``+`` must be percent-encoded.
        assert sanitize_principal_key("foo+123@amazon.com") == "foo%2B123@amazon.com"

    def test_hash_is_encoded(self):
        # ``#`` is the key delimiter and must never survive unencoded.
        assert sanitize_principal_key("user#tag") == "user%23tag"
        assert sanitize_principal_key("a#b#c") == "a%23b%23c"

    def test_slash_is_encoded(self):
        assert sanitize_principal_key("group/eng") == "group%2Feng"

    def test_no_collision_between_literal_and_encoded_input(self):
        # A literal ``%23`` must not collide with an encoded ``#``.
        assert sanitize_principal_key("user%23name") != sanitize_principal_key("user#name")
