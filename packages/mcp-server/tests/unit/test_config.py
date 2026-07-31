# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for MCPConfig environment-variable loading.

MCPConfig is a pydantic BaseSettings that reads SCL_-prefixed env vars.
These tests verify defaults and that env vars override them.
"""

from __future__ import annotations

import pytest
from coa_mcp.config import MCPConfig


@pytest.mark.unit
class TestMCPConfig:
    def test_defaults_when_no_env(self, monkeypatch):
        for var in (
            "SCL_ENVIRONMENT",
            "SCL_LOG_LEVEL",
            "SCL_AWS_REGION",
            "SCL_MCP_HOST",
            "SCL_MCP_PORT",
            "SCL_AUTH_ENABLED",
            "SCL_USE_FUSEKI",
        ):
            monkeypatch.delenv(var, raising=False)
        config = MCPConfig()
        assert config.environment == "dev"
        assert config.log_level == "INFO"
        assert config.aws_region == "us-east-1"
        assert config.mcp_host == "0.0.0.0"
        assert config.mcp_port == 8000
        assert config.auth_enabled is True
        assert config.use_fuseki is False

    def test_aws_region_env_override(self, monkeypatch):
        monkeypatch.setenv("SCL_AWS_REGION", "eu-central-1")
        assert MCPConfig().aws_region == "eu-central-1"

    def test_auth_enabled_env_override(self, monkeypatch):
        monkeypatch.setenv("SCL_AUTH_ENABLED", "false")
        assert MCPConfig().auth_enabled is False

    def test_mcp_port_env_override_coerced_to_int(self, monkeypatch):
        monkeypatch.setenv("SCL_MCP_PORT", "9001")
        config = MCPConfig()
        assert config.mcp_port == 9001
        assert isinstance(config.mcp_port, int)
