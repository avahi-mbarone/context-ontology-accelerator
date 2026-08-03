# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit test to validate the security pytest marker is registered.

This test ensures the security marker is properly configured in pyproject.toml
and can be used to select security-focused tests in CI and local runs.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestSecurityMarker:
    """Validate the security test marker is registered and functional."""

    def test_security_marker_is_registered(self, pytestconfig) -> None:
        """The 'security' marker should be registered in pytest configuration."""
        markers_raw = pytestconfig.getini("markers")
        # Markers come as strings like "security: description"
        markers = {line.split(":")[0].strip() for line in markers_raw}
        assert "security" in markers, "security marker not registered in pyproject.toml"

    def test_integ_marker_is_registered(self, pytestconfig) -> None:
        """The 'integ' marker should be registered (prerequisite for security tests)."""
        markers_raw = pytestconfig.getini("markers")
        markers = {line.split(":")[0].strip() for line in markers_raw}
        assert "integ" in markers, "integ marker not registered in pyproject.toml"
