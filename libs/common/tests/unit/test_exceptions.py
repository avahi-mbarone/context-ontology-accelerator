# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for coa_common.exceptions."""

from __future__ import annotations

import pytest
from coa_common.exceptions import (
    ConfigurationError,
    DataSourceError,
    IngestionError,
    SCLError,
)

pytestmark = pytest.mark.unit


class TestSCLError:
    def test_default_code(self):
        err = SCLError("boom")
        assert err.code == "INTERNAL_ERROR"
        assert str(err) == "boom"

    def test_custom_code(self):
        err = SCLError("boom", code="CUSTOM")
        assert err.code == "CUSTOM"


class TestSubclassCodes:
    @pytest.mark.parametrize(
        "cls, expected_code",
        [
            (ConfigurationError, "CONFIGURATION_ERROR"),
            (DataSourceError, "DATA_SOURCE_ERROR"),
            (IngestionError, "INGESTION_ERROR"),
        ],
    )
    def test_subclass_sets_code(self, cls, expected_code):
        err = cls("msg")
        assert err.code == expected_code
        assert str(err) == "msg"
        assert isinstance(err, SCLError)
