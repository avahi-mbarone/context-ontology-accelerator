# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""few-shot S3 example loader."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

import pytest
from coa_serve.tier2.ontop.sparql_example_loader import FewShotExampleLoader


def _s3_stub_returning(payload: dict):
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(payload).encode())}
    return s3


@pytest.mark.unit
class TestFewShotLoader:
    async def test_inert_without_bucket(self):
        loader = FewShotExampleLoader(bucket="")
        assert loader.available is False
        assert await loader.load("insurance") == []

    async def test_loads_and_parses_examples(self):
        payload = {
            "examples": [
                {"question": "How many open claims?", "sparql": "SELECT (COUNT(?c) AS ?n) WHERE { ?c a ind:Claim }"},
                {"question": "List policies", "sparql": "SELECT ?p WHERE { ?p a ind:Policy }"},
            ]
        }
        loader = FewShotExampleLoader(bucket="b", s3_client=_s3_stub_returning(payload))
        examples = await loader.load("insurance")
        assert len(examples) == 2
        assert examples[0].question == "How many open claims?"
        assert "Claim" in examples[0].sparql

    async def test_missing_file_falls_back_to_empty(self):
        s3 = MagicMock()
        s3.get_object.side_effect = Exception("NoSuchKey")
        loader = FewShotExampleLoader(bucket="b", s3_client=s3)
        assert await loader.load("insurance") == []

    async def test_bad_shape_falls_back(self):
        loader = FewShotExampleLoader(bucket="b", s3_client=_s3_stub_returning({"not_examples": 1}))
        assert await loader.load("insurance") == []

    async def test_skips_incomplete_entries(self):
        payload = {"examples": [{"question": "q only"}, {"sparql": "s only"}, {"question": "q", "sparql": "s"}]}
        loader = FewShotExampleLoader(bucket="b", s3_client=_s3_stub_returning(payload))
        examples = await loader.load("insurance")
        assert len(examples) == 1

    async def test_result_is_cached(self):
        s3 = _s3_stub_returning({"examples": [{"question": "q", "sparql": "s"}]})
        loader = FewShotExampleLoader(bucket="b", s3_client=s3)
        await loader.load("insurance")
        await loader.load("insurance")
        assert s3.get_object.call_count == 1  # second call served from cache

    async def test_invalidate_clears_cache(self):
        s3 = _s3_stub_returning({"examples": [{"question": "q", "sparql": "s"}]})
        loader = FewShotExampleLoader(bucket="b", s3_client=s3)
        await loader.load("insurance")
        loader.invalidate("insurance")
        await loader.load("insurance")
        assert s3.get_object.call_count == 2

    def test_format_for_prompt(self):
        from coa_serve.tier2.ontop.sparql_example_loader import FewShotExample

        block = FewShotExampleLoader.format_for_prompt(
            [FewShotExample(question="How many claims?", sparql="SELECT ?c WHERE { ?c a ind:Claim }")]
        )
        assert "How many claims?" in block
        assert "```sparql" in block

    def test_format_empty_is_empty(self):
        assert FewShotExampleLoader.format_for_prompt([]) == ""
