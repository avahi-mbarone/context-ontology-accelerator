# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for coa_common.logging.setup_logging."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from coa_common.logging import setup_logging

pytestmark = pytest.mark.unit


class TestSetupLogging:
    @patch("coa_common.logging.structlog.configure")
    def test_configures_structlog_with_default_level(self, mock_configure):
        setup_logging()
        mock_configure.assert_called_once()
        kwargs = mock_configure.call_args.kwargs
        assert kwargs["cache_logger_on_first_use"] is True
        assert kwargs["context_class"] is dict

    @patch("coa_common.logging.structlog.configure")
    def test_unknown_level_falls_back_to_info(self, mock_configure):
        # Should not raise even with a bogus level (getattr fallback to INFO)
        setup_logging(log_level="NOPE")
        mock_configure.assert_called_once()
