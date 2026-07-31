# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Metric-service unit test configuration."""

from __future__ import annotations

import os

# Required by coa_common.response (lazy check at api_response() call time).
# Set before any handler imports so api_response() can build CORS headers for responses.
os.environ.setdefault("ALLOWED_ORIGIN", "https://test.example.com")
