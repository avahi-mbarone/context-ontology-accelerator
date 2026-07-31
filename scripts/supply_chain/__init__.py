# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Supply-chain tooling: third-party license inventory + NOTICE generation.

Self-contained (stdlib only, via ``importlib.metadata``) so it runs in any build
without pulling unpinned third-party scanners. Backs ORR PAK-A-3: the root NOTICE
attributes every redistributed third-party component with its version and license.
"""

from __future__ import annotations
