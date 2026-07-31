# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for JWT claims extraction."""

import pytest
from coa_mcp.auth.claims import (
    ClaimsExtractionError,
    extract_caller_identity,
)

from .conftest import create_test_token


@pytest.mark.unit
class TestExtractCallerIdentity:
    """Test JWT claims extraction — platform validates, we just extract."""

    def test_valid_token_extracts_user_id(self):
        token = create_test_token(user_id="alice", namespaces=["sales", "hr"])
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.user_id == "alice"

    def test_valid_token_extracts_agent_id(self):
        token = create_test_token(user_id="alice", agent_id="claude-agent-1")
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.agent_id == "claude-agent-1"

    def test_valid_token_extracts_namespaces(self):
        token = create_test_token(user_id="alice", namespaces=["sales", "hr"])
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.namespaces == ["sales", "hr"]

    def test_valid_token_extracts_roles(self):
        token = create_test_token(user_id="alice", roles=["admin", "viewer"])
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.roles == ["admin", "viewer"]

    def test_does_not_revalidate_signature(self):
        """Claims extraction must NOT re-validate — platform already did."""
        # Create a token with an arbitrary secret (we don't verify it)
        import jwt

        payload = {"sub": "bob", "namespaces": ["ns1"]}
        token = jwt.encode(payload, "some-random-secret", algorithm="HS256")
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.user_id == "bob"

    def test_missing_authorization_header_raises(self):
        with pytest.raises(ClaimsExtractionError, match="Missing Authorization header"):
            extract_caller_identity(None)

    def test_empty_authorization_header_raises(self):
        with pytest.raises(ClaimsExtractionError, match="Missing Authorization header"):
            extract_caller_identity("")

    def test_malformed_bearer_prefix_raises(self):
        with pytest.raises(ClaimsExtractionError, match="must be 'Bearer"):
            extract_caller_identity("Basic dXNlcjpwYXNz")

    def test_invalid_token_payload_raises(self):
        with pytest.raises(ClaimsExtractionError, match="Failed to decode JWT"):
            extract_caller_identity("Bearer not.a.valid.jwt")

    def test_token_without_sub_claim_raises(self):
        import jwt

        payload = {"namespaces": ["ns1"]}  # No 'sub' or 'user_id'
        token = jwt.encode(payload, "secret", algorithm="HS256")
        with pytest.raises(ClaimsExtractionError, match="lacks required"):
            extract_caller_identity(f"Bearer {token}")

    def test_expired_token_raises(self):
        """Local exp check must reject expired tokens even though signature is not verified."""
        token = create_test_token(user_id="alice", exp_offset=-10)
        with pytest.raises(ClaimsExtractionError, match="expired"):
            extract_caller_identity(f"Bearer {token}")

    def test_comma_separated_string_namespaces_parsed_to_list(self):
        """A scope-style comma-separated string claim is split into a list."""
        import time

        import jwt

        payload = {
            "sub": "alice",
            "namespaces": "sales, hr ,  finance",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, "secret", algorithm="HS256")
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.namespaces == ["sales", "hr", "finance"]

    def test_user_id_from_username_claim_when_no_sub(self):
        """Falls back to 'username' claim for the delegating user id."""
        import time

        import jwt

        payload = {"username": "carol", "exp": int(time.time()) + 3600}
        token = jwt.encode(payload, "secret", algorithm="HS256")
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.user_id == "carol"


@pytest.mark.unit
class TestCreateTestToken:
    """Test the test-token helper used in local development."""

    def test_creates_decodable_token(self):
        token = create_test_token(user_id="test-user")
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.user_id == "test-user"

    def test_default_values(self):
        token = create_test_token()
        identity = extract_caller_identity(f"Bearer {token}")
        assert identity.user_id == "test-user"
        assert identity.agent_id == "test-agent"
        assert identity.namespaces == ["default"]
        assert identity.roles == ["viewer"]
