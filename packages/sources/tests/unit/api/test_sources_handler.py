# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Sources API Lambda handler.

Tests the API Gateway proxy integration handler that implements:
  GET /namespaces/{namespaceId}/sources — list all sources for a namespace

Uses moto to mock DynamoDB in-process — no real AWS calls.
"""

from __future__ import annotations

import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

# ---------------------------------------------------------------------------
# Path setup — add the api/ source directory so `sources_handler` can be
# imported like it would be in the Lambda runtime.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Environment variables — must be set before the handler module is imported
# because it reads them at cold-start (module level).
# ---------------------------------------------------------------------------
_TABLE_NAME = "test-sources"

os.environ.setdefault("SOURCES_TABLE", _TABLE_NAME)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NAMESPACE_ID = "550e8400-e29b-41d4-a716-446655440000"  # valid UUID v4
_OTHER_NAMESPACE_ID = "660e8400-e29b-41d4-a716-446655440001"

_LIST_RESOURCE = "/namespaces/{namespaceId}/sources"


def _make_event(
    method: str,
    resource: str,
    path_params: dict | None = None,
    query_params: dict | None = None,
) -> dict:
    """Build a minimal API Gateway proxy integration event."""
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params,
        "body": None,
    }


def _parse_response(result: dict) -> tuple[int, dict]:
    """Extract status code and parsed JSON body from a Lambda proxy response."""
    status = result["statusCode"]
    body = json.loads(result["body"]) if result.get("body") else {}
    return status, body


def _put_source(
    table,
    namespace_id: str,
    source_id: str,
    *,
    name: str = "test-source",
    source_type: str = "DATABASE",
    source_sub_type: str = "GLUE_DATABASE",
    status: str = "APPROVED",
    created_at: str = "2026-01-01T00:00:00Z",
) -> None:
    """Insert a source item into DDB matching the sources-table schema."""
    table.put_item(
        Item={
            "PK": f"NS#{namespace_id}",
            "SK": f"SRC#{source_id}",
            "namespaceId": namespace_id,
            "sourceId": source_id,
            "name": name,
            "sourceType": source_type,
            "sourceSubType": source_sub_type,
            "status": status,
            "createdAt": created_at,
            "sourceTypeCreatedAt": f"{source_type}#{created_at}",
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def aws_env():
    """Create mocked DynamoDB table, yield handler and table resources.

    The DDB table matches the CDK definition in sources-stack.ts:
      PK = NS#{namespaceId} (S), SK = SRC#{sourceId} (S)
      GSI ByNamespace: PK=namespaceId, SK=createdAt
      GSI BySourceType: PK=namespaceId, SK=sourceTypeCreatedAt
    """
    with mock_aws():
        region = "us-east-1"
        ddb = boto3.resource("dynamodb", region_name=region)
        table = ddb.create_table(
            TableName=_TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "namespaceId", "AttributeType": "S"},
                {"AttributeName": "createdAt", "AttributeType": "S"},
                {"AttributeName": "sourceTypeCreatedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "ByNamespace",
                    "KeySchema": [
                        {"AttributeName": "namespaceId", "KeyType": "HASH"},
                        {"AttributeName": "createdAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "BySourceType",
                    "KeySchema": [
                        {"AttributeName": "namespaceId", "KeyType": "HASH"},
                        {"AttributeName": "sourceTypeCreatedAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )
        table.meta.client.get_waiter("table_exists").wait(TableName=_TABLE_NAME)

        # Import handler inside the mock context so boto3 clients connect to moto
        for mod in list(sys.modules.keys()):
            if mod in ("coa_sources.api.sources_handler",) or mod.startswith("coa_common"):
                del sys.modules[mod]

        from coa_sources.api import sources_handler as handler_module  # noqa: E402

        yield {
            "handler": handler_module.handler,
            "table": table,
        }


# ===================================================================
# LIST — GET /namespaces/{namespaceId}/sources
# ===================================================================


@pytest.mark.unit
class TestListSourcesEmpty:
    def test_list_sources_empty(self, aws_env):
        """GET with no items → 200 with empty items array."""
        event = _make_event("GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID})
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        assert "items" in body
        assert body["items"] == []
        assert "nextToken" not in body


@pytest.mark.unit
class TestListSourcesReturnsItems:
    def test_returns_items_for_namespace(self, aws_env):
        """GET returns only items belonging to the requested namespace."""
        _put_source(aws_env["table"], _NAMESPACE_ID, "src-001", name="glue-db", created_at="2026-05-01T00:00:00Z")
        _put_source(
            aws_env["table"],
            _NAMESPACE_ID,
            "src-002",
            name="jdbc-db",
            source_sub_type="JDBC_DATABASE",
            created_at="2026-04-01T00:00:00Z",
        )
        # Item in a different namespace — must NOT be returned
        _put_source(aws_env["table"], _OTHER_NAMESPACE_ID, "src-003", name="other-db")

        event = _make_event("GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID})
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        assert len(body["items"]) == 2
        returned_ids = {item["sourceId"] for item in body["items"]}
        assert returned_ids == {"src-001", "src-002"}

    def test_items_have_expected_fields(self, aws_env):
        """Each returned item has the required SourceSummary fields."""
        _put_source(aws_env["table"], _NAMESPACE_ID, "src-001", name="my-source")

        event = _make_event("GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID})
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        item = body["items"][0]
        assert item["sourceId"] == "src-001"
        assert item["namespaceId"] == _NAMESPACE_ID
        assert item["name"] == "my-source"
        assert item["sourceType"] == "DATABASE"
        assert item["sourceSubType"] == "GLUE_DATABASE"
        assert item["status"] == "APPROVED"
        assert "createdAt" in item

    def test_returns_newest_first(self, aws_env):
        """Items are returned in descending createdAt order (newest first)."""
        _put_source(aws_env["table"], _NAMESPACE_ID, "src-oldest", created_at="2026-01-01T00:00:00Z")
        _put_source(aws_env["table"], _NAMESPACE_ID, "src-middle", created_at="2026-03-01T00:00:00Z")
        _put_source(aws_env["table"], _NAMESPACE_ID, "src-newest", created_at="2026-05-01T00:00:00Z")

        event = _make_event("GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID})
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        ids = [item["sourceId"] for item in body["items"]]
        assert ids == ["src-newest", "src-middle", "src-oldest"], f"Expected newest-first, got: {ids}"

    def test_documents_and_database_sources_returned_together(self, aws_env):
        """Both DATABASE and DOCUMENTS sources are returned in the unfiltered list."""
        _put_source(aws_env["table"], _NAMESPACE_ID, "db-src", source_type="DATABASE", source_sub_type="GLUE_DATABASE")
        _put_source(aws_env["table"], _NAMESPACE_ID, "doc-src", source_type="DOCUMENTS", source_sub_type="S3")

        event = _make_event("GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID})
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        types = {item["sourceType"] for item in body["items"]}
        assert types == {"DATABASE", "DOCUMENTS"}


@pytest.mark.unit
class TestListSourcesSourceTypeFilter:
    def test_filter_by_database(self, aws_env):
        """sourceType=DATABASE returns only DATABASE sources via BySourceType GSI."""
        _put_source(
            aws_env["table"],
            _NAMESPACE_ID,
            "db-src",
            source_type="DATABASE",
            source_sub_type="GLUE_DATABASE",
            created_at="2026-05-01T00:00:00Z",
        )
        _put_source(
            aws_env["table"],
            _NAMESPACE_ID,
            "doc-src",
            source_type="DOCUMENTS",
            source_sub_type="S3",
            created_at="2026-04-01T00:00:00Z",
        )

        event = _make_event(
            "GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID}, query_params={"sourceType": "DATABASE"}
        )
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        assert len(body["items"]) == 1
        assert body["items"][0]["sourceId"] == "db-src"

    def test_filter_by_documents(self, aws_env):
        """sourceType=DOCUMENTS returns only DOCUMENTS sources."""
        _put_source(
            aws_env["table"],
            _NAMESPACE_ID,
            "db-src",
            source_type="DATABASE",
            source_sub_type="JDBC_DATABASE",
            created_at="2026-05-01T00:00:00Z",
        )
        _put_source(
            aws_env["table"],
            _NAMESPACE_ID,
            "doc-src",
            source_type="DOCUMENTS",
            source_sub_type="LOCAL_UPLOAD",
            created_at="2026-04-01T00:00:00Z",
        )

        event = _make_event(
            "GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID}, query_params={"sourceType": "DOCUMENTS"}
        )
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        assert len(body["items"]) == 1
        assert body["items"][0]["sourceId"] == "doc-src"


@pytest.mark.unit
class TestListSourcesPagination:
    def test_pagination_next_token_present_when_more_items(self, aws_env):
        """When maxResults < total items, nextToken is returned."""
        for i in range(5):
            _put_source(
                aws_env["table"],
                _NAMESPACE_ID,
                f"src-{i:03d}",
                created_at=f"2026-0{i + 1}-01T00:00:00Z",
            )

        event = _make_event(
            "GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID}, query_params={"maxResults": "2"}
        )
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        assert len(body["items"]) == 2
        assert "nextToken" in body

    def test_pagination_next_token_absent_when_all_items_fit(self, aws_env):
        """When all items fit in one page, nextToken is not returned."""
        for i in range(3):
            _put_source(aws_env["table"], _NAMESPACE_ID, f"src-{i:03d}", created_at=f"2026-0{i + 1}-01T00:00:00Z")

        event = _make_event(
            "GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID}, query_params={"maxResults": "10"}
        )
        status, body = _parse_response(aws_env["handler"](event, None))

        assert status == 200
        assert len(body["items"]) == 3
        assert "nextToken" not in body

    def test_pagination_second_page_returns_remaining_items(self, aws_env):
        """Using nextToken from page 1 returns the remaining items on page 2."""
        for i in range(4):
            _put_source(
                aws_env["table"],
                _NAMESPACE_ID,
                f"src-{i:03d}",
                created_at=f"2026-0{i + 1}-01T00:00:00Z",
            )

        # Page 1
        event1 = _make_event(
            "GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID}, query_params={"maxResults": "2"}
        )
        status1, body1 = _parse_response(aws_env["handler"](event1, None))
        assert status1 == 200
        assert len(body1["items"]) == 2
        assert "nextToken" in body1

        # Page 2
        event2 = _make_event(
            "GET",
            _LIST_RESOURCE,
            path_params={"namespaceId": _NAMESPACE_ID},
            query_params={"maxResults": "2", "nextToken": body1["nextToken"]},
        )
        status2, body2 = _parse_response(aws_env["handler"](event2, None))
        assert status2 == 200
        assert len(body2["items"]) == 2

        # All 4 unique items across both pages
        all_ids = {i["sourceId"] for i in body1["items"]} | {i["sourceId"] for i in body2["items"]}
        assert len(all_ids) == 4


# ===================================================================
# Validation errors
# ===================================================================


@pytest.mark.unit
class TestValidation:
    def test_missing_namespace_id(self, aws_env):
        """Missing namespaceId path param → 400."""
        event = _make_event("GET", _LIST_RESOURCE, path_params={})
        status, body = _parse_response(aws_env["handler"](event, None))
        assert status == 400

    def test_invalid_namespace_id(self, aws_env):
        """Invalid namespaceId (special chars) → 400."""
        event = _make_event("GET", _LIST_RESOURCE, path_params={"namespaceId": "invalid@ns"})
        status, body = _parse_response(aws_env["handler"](event, None))
        assert status == 400
        assert "namespaceId" in body.get("error", "")

    def test_invalid_max_results_string(self, aws_env):
        """Non-integer maxResults → 400."""
        event = _make_event(
            "GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID}, query_params={"maxResults": "abc"}
        )
        status, body = _parse_response(aws_env["handler"](event, None))
        assert status == 400

    def test_max_results_out_of_range(self, aws_env):
        """maxResults > 100 → 400."""
        event = _make_event(
            "GET", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID}, query_params={"maxResults": "200"}
        )
        status, body = _parse_response(aws_env["handler"](event, None))
        assert status == 400

    def test_invalid_next_token(self, aws_env):
        """Malformed nextToken → 400."""
        event = _make_event(
            "GET",
            _LIST_RESOURCE,
            path_params={"namespaceId": _NAMESPACE_ID},
            query_params={"nextToken": "not-valid-base64!!!"},
        )
        status, body = _parse_response(aws_env["handler"](event, None))
        assert status == 400

    def test_unknown_route(self, aws_env):
        """Unknown HTTP method/resource combination → 404."""
        event = _make_event("PATCH", _LIST_RESOURCE, path_params={"namespaceId": _NAMESPACE_ID})
        status, _ = _parse_response(aws_env["handler"](event, None))
        assert status == 404


# ===================================================================
# Document detail — KG-build metrics enrichment
# ===================================================================
#
# _build_document_detail is a pure function, so these tests exercise the
# ProgressMonitor Number-counter reader directly without moto.


class TestDocumentDetailMetrics:
    def _detail(self, metrics):
        from coa_sources.api.sources_handler import _build_document_detail

        # filesTotal is a recognized field, so the detail dict is non-empty even
        # when no metrics record exists (the builder returns None for empty dicts).
        item = {"sourceType": "DOCUMENTS", "name": "docs", "status": "READY", "filesTotal": 5}
        return _build_document_detail(item, metrics)

    def test_maps_number_counters_to_api_fields(self):
        """ProgressMonitor writes plain Number counters; they surface 1:1."""
        detail = self._detail(
            {
                "documents_processed": 12,
                "chunks_llm": 340,
                "chunks_embed": 170,
                "chunks_graph": 168,
            }
        )
        assert detail["documentsProcessed"] == 12
        assert detail["chunksLLM"] == 340
        assert detail["chunksEmbed"] == 170
        assert detail["chunksGraph"] == 168

    def test_absent_counters_are_omitted(self):
        """No metrics record yet → none of the progress fields appear."""
        detail = self._detail(None)
        for field in ("documentsProcessed", "chunksLLM", "chunksEmbed", "chunksGraph"):
            assert field not in detail

    def test_partial_counters_only_emit_present_fields(self):
        detail = self._detail({"documents_processed": 3})
        assert detail["documentsProcessed"] == 3
        assert "chunksLLM" not in detail

    def test_legacy_string_set_values_are_ignored(self):
        """Records written by the old distinct-set design stored String Sets;
        the Number reader must skip them rather than crash or emit a set len."""
        detail = self._detail({"chunks_embed": {"c1", "c2", "c3"}, "chunks_llm": 42})
        assert "chunksEmbed" not in detail
        assert detail["chunksLLM"] == 42


@pytest.mark.unit
class TestGetSourceMetricsBestEffort:
    """The GET-source metrics read is best-effort: a failure enriching a document
    source with KG-build metrics must degrade to 200 (no metrics), never 500.

    Uses a fully-mocked DAO (no moto) so the test targets _handle_get's exception
    handling directly — the source item read succeeds, the follow-up metrics read
    on the METRICS# partition raises a transient BotoCoreError."""

    def test_botocore_error_on_metrics_read_still_returns_200(self, monkeypatch):
        from botocore.exceptions import EndpointConnectionError
        from coa_sources.api import sources_handler

        source_item = {
            "PK": f"NS#{_NAMESPACE_ID}",
            "SK": "SRC#doc-001",
            "namespaceId": _NAMESPACE_ID,
            "sourceId": "doc-001",
            "name": "docs",
            "sourceType": "DOCUMENTS",
            "sourceSubType": "S3",
            "status": "COMPLETED",
            "createdAt": "2026-01-01T00:00:00Z",
        }

        class _FlakyMetricsDao:
            def get(self, key, **kwargs):
                if key["PK"].startswith("METRICS#"):
                    raise EndpointConnectionError(endpoint_url="https://dynamodb")
                return source_item

        monkeypatch.setattr(sources_handler, "_get_dao", lambda: _FlakyMetricsDao())

        event = _make_event(
            "GET",
            "/namespaces/{namespaceId}/sources/{sourceId}",
            path_params={"namespaceId": _NAMESPACE_ID, "sourceId": "doc-001"},
        )
        status, body = _parse_response(sources_handler.handler(event, None))

        assert status == 200
        # Metrics fields are simply absent — the detail view is unaffected.
        doc_details = body.get("documentDetails", {})
        for field in ("documentsProcessed", "chunksLLM", "chunksEmbed", "chunksGraph"):
            assert field not in doc_details
