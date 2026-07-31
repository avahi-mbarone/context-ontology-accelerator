# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared utilities for the unified sources package."""

from __future__ import annotations

from typing import Any

from coa_common.constants import EXTRACTION_DEFAULTS, ExtractionMode

_VALID_EXTRACTION_MODES: frozenset[str] = frozenset(ExtractionMode)


def merge_extraction_config(config: object) -> dict[str, Any]:
    """Merge user-supplied extraction config with defaults.

    Accepts a Pydantic model (with ``model_dump``), a plain dict, or ``None``.
    Returns a snake_case dict suitable for SQS message bodies and DDB storage.
    Raises ``ValueError`` for an unrecognised ``extraction_mode``.
    """
    result: dict[str, Any] = dict(EXTRACTION_DEFAULTS)
    if config is None:
        return result
    if hasattr(config, "model_dump"):
        overrides: dict[str, Any] = config.model_dump(exclude_none=True)  # type: ignore[union-attr]
    elif isinstance(config, dict):
        overrides = {k: v for k, v in config.items() if v is not None}
    else:
        return result
    if "extraction_mode" in overrides and overrides["extraction_mode"] not in _VALID_EXTRACTION_MODES:
        raise ValueError(
            f"Invalid extractionMode: {overrides['extraction_mode']!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_EXTRACTION_MODES))}."
        )
    result.update(overrides)
    return result
