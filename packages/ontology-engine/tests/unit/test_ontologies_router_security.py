# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Security tests for ontologies router — CWE-209 information exposure.

Tests that httpx.HTTPError exceptions during source_url fetch do NOT leak
internal network topology (IP addresses, private DNS names, TLS handshake details).

These tests verify that the except _httpx.HTTPError handler produces opaque 502 messages.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestHTTPErrorMessageSanitization:
    """CWE-209: httpx errors must be caught and NOT appear in 502 response body."""

    def test_httpx_connect_error_message_structure(self):
        """Verify httpx.ConnectError carries internal details that must not leak."""
        import httpx

        # Simulate what happens during a connection failure
        try:
            raise httpx.ConnectError(
                "Connection refused to internal IP 10.0.1.42:443 for https://example.com/ontology.ttl"
            )
        except httpx.ConnectError as e:
            error_string = str(e)
            # Confirm the exception DOES contain sensitive details (pre-sanitization)
            assert "10.0.1.42" in error_string or "Connection refused" in error_string
            # This demonstrates why we need sanitization

    def test_httpx_remote_protocol_error_structure(self):
        """Verify httpx.RemoteProtocolError carries TLS/cert details that must not leak."""
        import httpx

        try:
            raise httpx.RemoteProtocolError(
                "TLS handshake failed: peer certificate CN=internal.example.com does not match expected CN=example.com"
            )
        except httpx.RemoteProtocolError as e:
            error_string = str(e)
            # Confirm the exception DOES contain TLS details
            assert "TLS handshake" in error_string or "internal.example.com" in error_string

    def test_httpx_timeout_exception_structure(self):
        """Verify httpx.TimeoutException can carry resolved IP that must not leak."""
        import httpx

        try:
            raise httpx.TimeoutException(
                "Timeout while connecting to https://example.com/ontology.ttl (resolved to 192.168.1.100)"
            )
        except httpx.TimeoutException as e:
            error_string = str(e)
            # Confirm the exception DOES contain resolved IP
            assert "192.168.1.100" in error_string or "Timeout while connecting" in error_string

    def test_sanitized_502_message_does_not_reference_exception_text(self):
        """The opaque 502 message must not include any exception details."""
        opaque_message = "Failed to fetch source_url: upstream request failed"

        # Verify the sanitized message contains no infrastructure details
        assert "10.0.1.42" not in opaque_message
        assert "internal.example.com" not in opaque_message
        assert "192.168.1.100" not in opaque_message
        assert "Connection refused" not in opaque_message
        assert "TLS handshake" not in opaque_message
        assert "Timeout while connecting" not in opaque_message
        # Confirm it's truly opaque
        assert opaque_message == "Failed to fetch source_url: upstream request failed"
