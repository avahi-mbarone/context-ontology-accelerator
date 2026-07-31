# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the serve OpenSearch VectorClient (async wrapper over the
shared AossVectorClient).

The serve client owns the async surface, ``VectorHit`` shaping, hybrid search,
and the proxy transport; the shared client owns the actual query building /
filtering / retry (tested in ``coa_common``'s
``test_opensearch_client.py``). So here we inject a mock shared client via
``client._aoss`` and assert delegation + hit shaping.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _client(**aoss_attrs):
    """Build a serve client with a mocked shared AossVectorClient."""
    from coa_serve.clients.opensearch import OpenSearchVectorClient

    client = OpenSearchVectorClient(endpoint="test.aoss.amazonaws.com")
    aoss = MagicMock()
    for k, v in aoss_attrs.items():
        getattr(aoss, k).return_value = v
    client._aoss = aoss
    return client, aoss


@pytest.mark.unit
class TestParseHits:
    def test_parse_hits(self):
        client, _ = _client()
        raw = {
            "hits": {
                "hits": [
                    {
                        "_id": "c1",
                        "_score": 0.92,
                        "_source": {
                            "text": "Claims SLA is 10 days",
                            "source_doc": "policy.pdf",
                            "label": "Policy.pdf",
                            "chunk_index": 3,
                            "type": "document",
                        },
                    }
                ]
            }
        }
        hits = client._parse_hits(raw)
        assert len(hits) == 1
        assert hits[0].id == "c1"
        assert hits[0].score == 0.92
        assert hits[0].text == "Claims SLA is 10 days"
        assert hits[0].metadata["label"] == "Policy.pdf"

    def test_parse_hits_empty_results(self):
        client, _ = _client()
        assert client._parse_hits({"hits": {"hits": []}}) == []

    def test_parse_hits_missing_fields(self):
        client, _ = _client()
        raw = {"hits": {"hits": [{"_id": "c2", "_score": 0.5, "_source": {"text": "some text"}}]}}
        hits = client._parse_hits(raw)
        assert hits[0].metadata["source_doc"] == ""
        assert hits[0].metadata["type"] == ""

    def test_parse_hits_keeps_missing_source_as_empty(self):
        client, _ = _client()
        raw = {
            "hits": {"hits": [{"_id": "c3", "_score": 0.8}, {"_id": "c4", "_score": 0.7, "_source": {"text": "valid"}}]}
        }
        hits = client._parse_hits(raw)
        assert len(hits) == 2
        assert hits[0].id == "c3" and hits[0].text == ""
        assert hits[1].id == "c4" and hits[1].text == "valid"


@pytest.mark.unit
class TestConstruction:
    def test_missing_endpoint_raises(self):
        from coa_serve.clients.opensearch import OpenSearchVectorClient

        with pytest.raises(ValueError, match="OpenSearch endpoint must be provided"):
            OpenSearchVectorClient(endpoint="")


@pytest.mark.unit
class TestSearchDelegation:
    async def test_entity_type_becomes_server_side_filter_and_shapes_hits(self):
        client, aoss = _client(
            knn_search=[
                {"_id": "cls1", "_score": 0.9, "text": "Claim", "entity_type": "class"},
                {"_id": "cls2", "_score": 0.85, "text": "Policy", "entity_type": "class"},
            ]
        )
        hits = await client.search([0.1] * 8, top_k=2, index="ont-idx", entity_type="class")

        # Delegates to the shared client's knn_search with the term filter + top_k.
        kwargs = aoss.knn_search.call_args.kwargs
        assert kwargs["top_k"] == 2
        assert kwargs["filters"] == [{"term": {"entity_type": "class"}}]
        assert aoss.knn_search.call_args.args[0] == "ont-idx"
        assert [h.id for h in hits] == ["cls1", "cls2"]
        assert hits[0].metadata["entity_type"] == "class"

    async def test_require_mapped_adds_exists_filter(self):
        client, aoss = _client(knn_search=[])
        await client.search([0.1] * 8, top_k=5, entity_type="class", require_mapped=True)
        assert aoss.knn_search.call_args.kwargs["filters"] == [
            {"term": {"entity_type": "class"}},
            {"exists": {"field": "data_source_id"}},
        ]

    async def test_no_filters_passes_none(self):
        client, aoss = _client(knn_search=[])
        await client.search([0.1] * 8, top_k=7)
        assert aoss.knn_search.call_args.kwargs["filters"] is None
        assert aoss.knn_search.call_args.kwargs["top_k"] == 7

    async def test_count_documents_delegates_with_filters(self):
        client, aoss = _client(count=3)
        n = await client.count_documents(index="ont-idx", entity_type="class", require_mapped=True)
        assert n == 3
        assert aoss.count.call_args.args[0] == "ont-idx"
        assert aoss.count.call_args.kwargs["filters"] == [
            {"term": {"entity_type": "class"}},
            {"exists": {"field": "data_source_id"}},
        ]


@pytest.mark.unit
class TestHybridAndHealth:
    async def test_hybrid_search_uses_bool_should_via_search_raw(self):
        client, aoss = _client(search_raw={"hits": {"hits": [{"_id": "h1", "_score": 0.6, "_source": {"text": "t"}}]}})
        hits = await client.hybrid_search("query", [0.1] * 8, top_k=4, index="chunks")
        body = aoss.search_raw.call_args.args[1]
        should = body["query"]["bool"]["should"]
        assert any("match" in clause for clause in should)
        assert any("knn" in clause for clause in should)
        assert [h.id for h in hits] == ["h1"]

    async def test_health_check_ok_maps_to_healthy(self):
        client, aoss = _client(health_check={"status": "ok", "index": "document-chunks"})
        result = await client.health_check()
        assert result["status"] == "healthy"

    async def test_health_check_error_maps_to_unhealthy(self):
        client, aoss = _client(health_check={"status": "error", "error": "boom"})
        result = await client.health_check()
        assert result["status"] == "unhealthy"

    async def test_close_is_noop(self):
        client, _ = _client()
        await client.close()  # must not raise
