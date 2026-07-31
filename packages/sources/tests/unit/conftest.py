# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sources unit test configuration.

Required by coa_common.response (lazy check at api_response() call
time). Set before any handler imports so api_response() can return error
responses; otherwise every handler test raises RuntimeError("ALLOWED_ORIGIN
environment variable must be set"). Matches the pattern used by control-plane
and metric-service unit conftests.
"""

import os

os.environ.setdefault("ALLOWED_ORIGIN", "https://test.example.com")
