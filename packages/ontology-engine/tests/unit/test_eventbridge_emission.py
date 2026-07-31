# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for EventBridge event emission on ontology publish."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from coa_common.constants import EVENT_SOURCE_PREFIX


@pytest.mark.unit
class TestEmitOntologyPublished:
    """Tests for _emit_ontology_published helper."""

    def _call(self, mock_events_client, namespace="test-ns", version="v1"):
        """Call _emit_ontology_published with a mocked boto3.client."""
        with (
            patch.dict("os.environ", {"AWS_REGION": "us-west-2"}),
            patch("coa_ontology.proposals._S3_BUCKET", "test-bucket"),
            patch("coa_ontology.proposals._S3_PREFIX", "ontologies"),
        ):
            import boto3 as real_boto3

            with patch.object(real_boto3, "client", return_value=mock_events_client):
                from coa_ontology.proposals import _emit_ontology_published

                _emit_ontology_published(namespace, version)

    def test_emits_correct_event_structure(self):
        mock_events = MagicMock()
        mock_events.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "abc"}]}

        self._call(mock_events)

        mock_events.put_events.assert_called_once()
        entries = mock_events.put_events.call_args[1]["Entries"]
        entry = entries[0]
        assert entry["Source"] == f"{EVENT_SOURCE_PREFIX}.ontology"
        assert entry["DetailType"] == "ontology.published"
        detail = json.loads(entry["Detail"])
        assert detail["namespace"] == "test-ns"
        assert detail["version"] == "v1"
        assert detail["s3Bucket"] == "test-bucket"
        assert detail["s3Prefix"] == "ontologies/test-ns/latest/"

    def test_raises_on_failed_entry(self):
        """FailedEntryCount > 0 raises so ``_run_accept_step`` retries it. The
        accept still survives an exhausted retry — that is the CALLER's
        ``fatal=False``, not this function swallowing."""
        mock_events = MagicMock()
        mock_events.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "InternalError", "ErrorMessage": "Service unavailable"}],
        }
        with pytest.raises(RuntimeError, match="FailedEntryCount=1"):
            self._call(mock_events)

    def test_raises_so_the_retry_wrapper_sees_the_failure(self):
        mock_events = MagicMock()
        mock_events.put_events.side_effect = RuntimeError("Connection timeout")
        with pytest.raises(RuntimeError, match="Connection timeout"):
            self._call(mock_events)
