# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for coa_sources.utils — merge_extraction_config."""

from __future__ import annotations

import pytest
from coa_common.constants import EXTRACTION_DEFAULTS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeConfig:
    """Minimal Pydantic-like model stub with model_dump."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self, exclude_none: bool = False):
        if exclude_none:
            return {k: v for k, v in self._data.items() if v is not None}
        return dict(self._data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeExtractionConfigNone:
    def test_none_returns_defaults(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config(None)
        assert result == dict(EXTRACTION_DEFAULTS)

    def test_returns_copy_not_original(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config(None)
        result["extraction_mode"] = "mutated"
        # Calling again should still return the original defaults
        result2 = merge_extraction_config(None)
        assert result2["extraction_mode"] == EXTRACTION_DEFAULTS["extraction_mode"]


@pytest.mark.unit
class TestMergeExtractionConfigDict:
    def test_empty_dict_returns_defaults(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config({})
        assert result == dict(EXTRACTION_DEFAULTS)

    def test_dict_with_none_values_ignored(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config({"extraction_mode": None})
        assert result["extraction_mode"] == EXTRACTION_DEFAULTS["extraction_mode"]

    def test_dict_overrides_extraction_mode_continuous(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config({"extraction_mode": "continuous"})
        assert result["extraction_mode"] == "continuous"

    def test_dict_overrides_extraction_mode_separated(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config({"extraction_mode": "separated"})
        assert result["extraction_mode"] == "separated"

    def test_dict_overrides_use_batch_inference(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config({"use_batch_inference": True})
        assert result["use_batch_inference"] is True

    def test_dict_overrides_enable_versioning(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config({"enable_versioning": False})
        assert result["enable_versioning"] is False

    def test_dict_overrides_multiple_fields(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config(
            {
                "extraction_mode": "separated",
                "use_batch_inference": True,
                "enable_versioning": False,
            }
        )
        assert result["extraction_mode"] == "separated"
        assert result["use_batch_inference"] is True
        assert result["enable_versioning"] is False

    def test_dict_invalid_extraction_mode_raises(self):
        from coa_sources.utils import merge_extraction_config

        with pytest.raises(ValueError, match="Invalid extractionMode"):
            merge_extraction_config({"extraction_mode": "invalid-mode"})

    def test_dict_preserves_unrelated_defaults(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config({"extraction_mode": "separated"})
        # All other defaults should still be present
        for key in EXTRACTION_DEFAULTS:
            assert key in result


@pytest.mark.unit
class TestMergeExtractionConfigPydanticModel:
    def test_model_with_no_overrides_returns_defaults(self):
        from coa_sources.utils import merge_extraction_config

        model = _FakeConfig({})
        result = merge_extraction_config(model)
        assert result == dict(EXTRACTION_DEFAULTS)

    def test_model_overrides_extraction_mode(self):
        from coa_sources.utils import merge_extraction_config

        model = _FakeConfig({"extraction_mode": "separated"})
        result = merge_extraction_config(model)
        assert result["extraction_mode"] == "separated"

    def test_model_none_values_excluded(self):
        from coa_sources.utils import merge_extraction_config

        model = _FakeConfig({"extraction_mode": None, "use_batch_inference": True})
        result = merge_extraction_config(model)
        # None value should be excluded, so extraction_mode stays as default
        assert result["extraction_mode"] == EXTRACTION_DEFAULTS["extraction_mode"]
        assert result["use_batch_inference"] is True

    def test_model_invalid_extraction_mode_raises(self):
        from coa_sources.utils import merge_extraction_config

        model = _FakeConfig({"extraction_mode": "bad-mode"})
        with pytest.raises(ValueError, match="Invalid extractionMode"):
            merge_extraction_config(model)


@pytest.mark.unit
class TestMergeExtractionConfigUnknownType:
    def test_unknown_type_returns_defaults(self):
        from coa_sources.utils import merge_extraction_config

        # An object that is neither None, dict, nor has model_dump
        result = merge_extraction_config(42)
        assert result == dict(EXTRACTION_DEFAULTS)

    def test_string_returns_defaults(self):
        from coa_sources.utils import merge_extraction_config

        result = merge_extraction_config("some-string")
        assert result == dict(EXTRACTION_DEFAULTS)
