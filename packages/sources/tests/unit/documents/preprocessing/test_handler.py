# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the preprocessing Lambda handler."""

import os
from unittest.mock import call, patch

import pytest

# Add preprocessing source to path for imports

# Set required env vars before importing handler (module-level validation runs at import)
os.environ.setdefault("BUCKET_NAME", "test-bucket")
os.environ.setdefault("DOC_SOURCES_TABLE", "test-table")

from coa_common.constants import validate_id  # noqa: E402

# Common env vars required by handler
_ENV = {"BUCKET_NAME": "test-bucket", "DOC_SOURCES_TABLE": "test-table"}


# ---------------------------------------------------------------------------
# Input validation — validate_id (now in coa_common.constants)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateId:
    def test_valid_simple(self):
        validate_id("valid-id_123", "test")  # should not raise

    def test_valid_alphanumeric(self):
        validate_id("abc123", "test")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid test"):
            validate_id("", "test")

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError):
            validate_id("../path/traversal", "test")

    def test_spaces_raise(self):
        with pytest.raises(ValueError):
            validate_id("has spaces", "test")

    def test_dots_raise(self):
        with pytest.raises(ValueError):
            validate_id("has.dots", "test")

    def test_slashes_raise(self):
        with pytest.raises(ValueError):
            validate_id("has/slash", "test")


# ---------------------------------------------------------------------------
# Validation error responses (400)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerValidation:
    @patch.dict(os.environ, _ENV)
    def test_invalid_namespace_returns_400(self):
        from coa_sources.documents.preprocessing.handler import handler

        result = handler({"namespace_id": "../bad", "doc_source_id": "ok"}, None)
        assert result["status"] == "SCAN_FAILED"
        assert len(result["issues"]) > 0

    @patch.dict(os.environ, _ENV)
    def test_empty_ids_returns_400(self):
        from coa_sources.documents.preprocessing.handler import handler

        result = handler({"namespace_id": "", "doc_source_id": ""}, None)
        assert result["status"] == "SCAN_FAILED"

    @patch.dict(os.environ, _ENV)
    def test_invalid_doc_source_returns_400(self):
        from coa_sources.documents.preprocessing.handler import handler

        result = handler({"namespace_id": "ok", "doc_source_id": "bad/id"}, None)
        assert result["status"] == "SCAN_FAILED"
        assert result["issues"][0]["reason"]


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerResponseShape:
    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_empty_listing_has_all_keys(self, mock_client, mock_list):
        from coa_sources.documents.preprocessing.handler import handler

        result = handler(
            {"namespace_id": "ns1", "doc_source_id": "ds1", "s3_prefixes": ["ns1/raw/ds1/"]},
            None,
        )
        assert result["status"] == "SCANNING"
        expected_keys = {
            "status",
            "staging_prefix",
            "files_total",
            "files_preprocessed",
            "files_skipped",
            "files_errored",
            "issues",
            "elapsed_seconds",
        }
        assert expected_keys.issubset(result.keys())
        assert isinstance(result["elapsed_seconds"], float)
        assert result["files_total"] == 0


# ---------------------------------------------------------------------------
# s3_prefixes — whole bucket and multi-prefix behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestS3PrefixBehaviour:
    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_empty_prefixes_lists_whole_bucket(self, mock_client, mock_list):
        """No s3_prefixes → list_objects called with empty prefix (whole bucket)."""
        from coa_sources.documents.preprocessing.handler import handler

        handler({"namespace_id": "ns1", "doc_source_id": "ds1"}, None)
        mock_list.assert_called_once()
        args = mock_list.call_args[0]
        assert args[2] == ""  # empty prefix = whole bucket

    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_single_prefix_used(self, mock_client, mock_list):
        from coa_sources.documents.preprocessing.handler import handler

        handler({"namespace_id": "ns1", "doc_source_id": "ds1", "s3_prefixes": ["custom/path/"]}, None)
        args = mock_list.call_args[0]
        assert args[2] == "custom/path/"

    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_multiple_prefixes_calls_list_objects_per_prefix(self, mock_client, mock_list):
        from coa_sources.documents.preprocessing.handler import handler

        handler(
            {"namespace_id": "ns1", "doc_source_id": "ds1", "s3_prefixes": ["reports/2024/", "reports/2025/"]},
            None,
        )
        assert mock_list.call_count == 2
        prefixes_called = [c[0][2] for c in mock_list.call_args_list]
        assert "reports/2024/" in prefixes_called
        assert "reports/2025/" in prefixes_called

    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_staging_prefix_always_derived(self, mock_client, mock_list):
        from coa_sources.documents.preprocessing.handler import handler

        result = handler({"namespace_id": "myns", "doc_source_id": "myds"}, None)
        assert result["staging_prefix"] == "myns/staging/myds/"

    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.upload_metadata")
    @patch("coa_sources.documents.preprocessing.handler.upload_file")
    @patch("coa_sources.documents.preprocessing.handler.read_file_bytes", return_value=b"ok")
    @patch("coa_sources.documents.preprocessing.handler.list_objects")
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_deduplicates_overlapping_prefixes(self, mock_client, mock_list, mock_read, mock_upload, mock_meta):
        """If two prefixes return the same key, it should only be processed once."""
        mock_list.return_value = [{"Key": "reports/doc.txt", "Size": 2}]
        from coa_sources.documents.preprocessing.handler import handler

        result = handler(
            {"namespace_id": "ns1", "doc_source_id": "ds1", "s3_prefixes": ["reports/", "reports/"]},
            None,
        )
        assert result["files_preprocessed"] == 1
        assert mock_upload.call_count == 1


# ---------------------------------------------------------------------------
# Cross-account S3 access
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCrossAccountAccess:
    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch(
        "coa_sources.documents.preprocessing.handler.parse_bucket_from_arn",
        return_value="external-bucket",
    )
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_source_bucket_arn_uses_external_bucket(self, mock_client, mock_parse, mock_list):
        from coa_sources.documents.preprocessing.handler import handler

        handler(
            {
                "namespace_id": "ns1",
                "doc_source_id": "ds1",
                "source_bucket_arn": "arn:aws:s3:::external-bucket",
                "role_arn": "arn:aws:iam::123456789012:role/coa-cross-account-reader",
            },
            None,
        )
        mock_parse.assert_called_once_with("arn:aws:s3:::external-bucket")
        assert mock_client.call_count == 2
        first_call = mock_client.call_args_list[0]
        assert first_call == call(role_arn="arn:aws:iam::123456789012:role/coa-cross-account-reader")
        list_call_args = mock_list.call_args[0]
        assert list_call_args[1] == "external-bucket"

    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch("coa_sources.documents.preprocessing.handler.parse_bucket_from_arn", return_value="ext-bucket")
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_cross_account_without_role_arn(self, mock_client, mock_parse, mock_list):
        from coa_sources.documents.preprocessing.handler import handler

        handler(
            {
                "namespace_id": "ns1",
                "doc_source_id": "ds1",
                "source_bucket_arn": "arn:aws:s3:::ext-bucket",
            },
            None,
        )
        first_call = mock_client.call_args_list[0]
        assert first_call == call(role_arn=None)

    @patch.dict(os.environ, _ENV)
    @patch("coa_sources.documents.preprocessing.handler.list_objects", return_value=[])
    @patch("coa_sources.documents.preprocessing.handler.get_s3_client")
    def test_no_source_bucket_uses_our_bucket(self, mock_client, mock_list):
        from coa_sources.documents.preprocessing.handler import handler

        handler({"namespace_id": "ns1", "doc_source_id": "ds1"}, None)
        assert mock_client.call_count == 2
        assert mock_client.call_args_list[0] == call()
        list_call_args = mock_list.call_args[0]
        assert list_call_args[1] == "test-bucket"
