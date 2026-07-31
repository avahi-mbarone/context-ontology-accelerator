# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""MCP Server configuration — extends shared SCLConfig."""

from pydantic_settings import BaseSettings


class MCPConfig(BaseSettings):
    """Configuration for the MCP Server.

    Values loaded from environment variables with ``SCL_`` prefix.
    Pydantic BaseSettings reads env vars automatically — for example,
    ``aws_region`` defaults to "us-east-1" only when the ``SCL_AWS_REGION``
    environment variable is not set. When the env var is present, its value
    takes precedence over the default specified here.
    """

    model_config = {"env_prefix": "SCL_"}

    # General
    environment: str = "dev"
    log_level: str = "INFO"

    # AWS — defaults to us-east-1 only when SCL_AWS_REGION env var is not set
    aws_region: str = "us-east-1"

    # Neptune (for discovery tools)
    neptune_endpoint: str = ""
    neptune_port: int = 8182

    # Fuseki local dev mode (bypasses SigV4, uses plain HTTP)
    use_fuseki: bool = False
    fuseki_url: str = "http://localhost:3030/coa/query"

    # MCP Server
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # Auth
    auth_enabled: bool = True
