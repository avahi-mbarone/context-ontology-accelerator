# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Upstream service clients for the Context Manager.

All clients are accessed through abstract protocols defined in `base.py`.
The resolution pipeline depends only on these protocols — never on concrete
implementations. This allows backend swaps (e.g., Neptune DB → Neptune
Analytics) without changing the resolution logic.

Use `factory.build_clients()` to construct the configured client set.
Unit tests should mock the protocols directly via unittest.mock.AsyncMock.
"""
