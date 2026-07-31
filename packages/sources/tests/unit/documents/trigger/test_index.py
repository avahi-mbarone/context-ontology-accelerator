# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the ingestion trigger Lambda."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test")
os.environ.setdefault(
    "BEDROCK_MODEL_ARN",
    "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from coa_sources.documents.trigger import index


def _make_record(body: dict | str, message_id: str = "msg-001") -> dict:
    return {
        "messageId": message_id,
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


def _make_event(*records: dict) -> dict:
    return {"Records": list(records)}


_VALID_BODY = {
    "namespace_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "doc_source_id": "ds-1",
    "s3_prefixes": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/raw/ds-1/"],
}


@pytest.mark.unit
class TestHandlerValidMessage:
    @patch.object(index, "sfn_client")
    def test_starts_execution_for_valid_message(self, mock_sfn):
        index.handler(_make_event(_make_record(_VALID_BODY)), None)
        mock_sfn.start_execution.assert_called_once()
        call_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
        assert call_input["namespace_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert "extraction_config" in call_input
        assert call_input["extraction_config"]["extraction_mode"] == "continuous"
        assert call_input["extraction_config"]["use_batch_inference"] == "false"

    @patch.object(index, "sfn_client")
    def test_processes_multiple_records(self, mock_sfn):
        body2 = {**_VALID_BODY, "doc_source_id": "ds-2"}
        index.handler(_make_event(_make_record(_VALID_BODY), _make_record(body2)), None)
        assert mock_sfn.start_execution.call_count == 2


@pytest.mark.unit
class TestHandlerMalformedMessage:
    @patch.object(index, "sfn_client")
    def test_drops_message_missing_namespace_id(self, mock_sfn):
        body = {"doc_source_id": "ds-1"}
        index.handler(_make_event(_make_record(body)), None)
        mock_sfn.start_execution.assert_not_called()

    @patch.object(index, "sfn_client")
    def test_drops_message_missing_doc_source_id(self, mock_sfn):
        body = {"namespace_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
        index.handler(_make_event(_make_record(body)), None)
        mock_sfn.start_execution.assert_not_called()

    @patch.object(index, "sfn_client")
    def test_drops_invalid_json(self, mock_sfn):
        record = _make_record("not-json")
        record["body"] = "not-json"
        index.handler(_make_event(record), None)
        mock_sfn.start_execution.assert_not_called()

    @patch.object(index, "sfn_client")
    def test_continues_after_malformed_message(self, mock_sfn):
        """A malformed message should not prevent processing of subsequent valid ones."""
        bad = _make_record({"namespace_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}, "bad-msg")
        good = _make_record(_VALID_BODY, "good-msg")
        index.handler(_make_event(bad, good), None)
        mock_sfn.start_execution.assert_called_once()

    @patch.object(index, "sfn_client")
    def test_whole_bucket_no_prefixes(self, mock_sfn):
        """s3_prefixes absent means whole-bucket ingestion — still valid."""
        body = {"namespace_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "doc_source_id": "ds-1"}
        index.handler(_make_event(_make_record(body)), None)
        mock_sfn.start_execution.assert_called_once()
        call_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
        assert "s3_prefixes" not in call_input or call_input.get("s3_prefixes") in (None, [])

    @patch.object(index, "sfn_client")
    def test_multiple_prefixes_passed_through(self, mock_sfn):
        """Multiple prefixes should be forwarded to Step Functions as-is."""
        body = {
            **_VALID_BODY,
            "s3_prefixes": ["reports/2024/", "reports/2025/"],
        }
        index.handler(_make_event(_make_record(body)), None)
        call_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
        assert call_input["s3_prefixes"] == ["reports/2024/", "reports/2025/"]


@pytest.mark.unit
class TestHandlerTransientErrors:
    @patch.object(index, "sfn_client")
    def test_reraises_client_error(self, mock_sfn):
        from botocore.exceptions import ClientError

        mock_sfn.start_execution.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "StartExecution",
        )
        with pytest.raises(ClientError):
            index.handler(_make_event(_make_record(_VALID_BODY)), None)

    @patch.object(index, "sfn_client")
    def test_reraises_unexpected_error(self, mock_sfn):
        mock_sfn.start_execution.side_effect = RuntimeError("unexpected")
        with pytest.raises(RuntimeError):
            index.handler(_make_event(_make_record(_VALID_BODY)), None)


@pytest.mark.unit
class TestExtractionConfigNormalization:
    @patch.object(index, "sfn_client")
    def test_defaults_applied_when_no_config(self, mock_sfn):
        index.handler(_make_event(_make_record(_VALID_BODY)), None)
        call_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
        ec = call_input["extraction_config"]
        assert ec["extraction_mode"] == "continuous"
        assert ec["use_batch_inference"] == "false"
        assert ec["enable_versioning"] == "true"
        assert ec["enable_proposition_extraction"] == "true"
        assert ec["delete_prev_versions"] == "false"
        assert ec["bedrock_model_arn"].startswith("arn:aws:bedrock:")

    @patch.object(index, "sfn_client")
    def test_partial_override_merges_with_defaults(self, mock_sfn):
        body = {**_VALID_BODY, "extraction_config": {"extraction_mode": "separated"}}
        index.handler(_make_event(_make_record(body)), None)
        call_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
        ec = call_input["extraction_config"]
        assert ec["extraction_mode"] == "separated"
        assert ec["use_batch_inference"] == "false"
        assert ec["enable_versioning"] == "true"

    @patch.object(index, "sfn_client")
    def test_full_override(self, mock_sfn):
        body = {
            **_VALID_BODY,
            "extraction_config": {
                "extraction_mode": "separated",
                "use_batch_inference": False,
                "enable_versioning": False,
                "enable_proposition_extraction": False,
                "delete_prev_versions": True,
            },
        }
        index.handler(_make_event(_make_record(body)), None)
        call_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
        ec = call_input["extraction_config"]
        assert ec["extraction_mode"] == "separated"
        assert ec["enable_versioning"] == "false"
        assert ec["enable_proposition_extraction"] == "false"
        assert ec["delete_prev_versions"] == "true"

    @patch.object(index, "sfn_client")
    def test_none_values_ignored(self, mock_sfn):
        body = {**_VALID_BODY, "extraction_config": {"extraction_mode": None}}
        index.handler(_make_event(_make_record(body)), None)
        call_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
        assert call_input["extraction_config"]["extraction_mode"] == "continuous"
