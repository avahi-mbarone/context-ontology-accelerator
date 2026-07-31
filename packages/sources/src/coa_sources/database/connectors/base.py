# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Connector protocol and shared types for the scan pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from coa_common.domain_models import DiscoveredMetadata


@dataclass
class ConnectionCheck:
    """Result of a single connection verification check."""

    check: str  # e.g. "catalog_access", "network", "auth"
    status: str  # "ok", "failed", "warning"
    message: str


@dataclass
class ConnectionTestResult:
    """Aggregate result of all connection checks."""

    success: bool
    message: str
    checks: list[ConnectionCheck] = field(default_factory=list)


@runtime_checkable
class MetadataConnector(Protocol):
    """Interface for pluggable data source connectors."""

    def test_connection(self, config: dict) -> ConnectionTestResult:
        """Verify connectivity to the data source."""
        ...

    def discover_metadata(self, config: dict) -> DiscoveredMetadata:
        """Discover tables and columns from the data source."""
        ...
