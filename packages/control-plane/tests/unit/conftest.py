# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Control-plane unit test configuration."""

import os

# Required by coa_common.response (lazy check at api_response() call time).
# Set before any handler imports to ensure api_response() can return error responses.
os.environ.setdefault("ALLOWED_ORIGIN", "https://test.example.com")
