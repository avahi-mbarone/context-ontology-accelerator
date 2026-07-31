# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for StoreOntologyCatalogAdapter.

The adapter presents the legacy ``OntologyCatalogClient`` surface on top of a
``(GraphStore, VectorStore)`` pair. We inject MagicMock stores and assert the
adapter threads namespace correctly, converts ``EmbeddingHit`` dataclasses to
dicts, and applies the create/get/upload semantics.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from coa_ontology.stores.adapters import StoreOntologyCatalogAdapter
from coa_ontology.stores.base import EmbeddingHit

pytestmark = pytest.mark.unit


def _adapter(namespace: str | None = "ns1") -> tuple[StoreOntologyCatalogAdapter, MagicMock, MagicMock]:
    graph = MagicMock()
    vec = MagicMock()
    return StoreOntologyCatalogAdapter(graph, vec, namespace=namespace), graph, vec


class TestSearchEmbeddings:
    def test_converts_hits_to_dicts_and_uses_bound_namespace(self):
        adapter, _graph, vec = _adapter("ns1")
        vec.search_nearest.return_value = [
            EmbeddingHit(entity_uri="http://x/A", embedding_type="lexical", model_id="titan", vector=[0.1], score=0.9)
        ]
        out = adapter.search_embeddings([0.1], "lexical", "titan", ontology_id="ont-1", top_k=7)
        assert out == [
            {
                "entity_uri": "http://x/A",
                "embedding_type": "lexical",
                "model_id": "titan",
                "vector": [0.1],
                "ontology_id": None,
                "entity_type": None,
                "score": 0.9,
                "text": None,
                "metadata": None,
            }
        ]
        # Bound namespace is passed through when no per-call namespace given.
        assert vec.search_nearest.call_args.kwargs["namespace"] == "ns1"
        assert vec.search_nearest.call_args.kwargs["top_k"] == 7

    def test_per_call_namespace_overrides_bound(self):
        adapter, _graph, vec = _adapter("ns1")
        vec.search_nearest.return_value = []
        adapter.search_embeddings([0.1], "lexical", "titan", namespace="other")
        assert vec.search_nearest.call_args.kwargs["namespace"] == "other"


class TestGetEmbeddingsForEntity:
    def test_delegates_with_bound_namespace(self):
        adapter, _graph, vec = _adapter("ns1")
        vec.get_embeddings_for_entity.return_value = [{"vector": [0.1]}]
        out = adapter.get_embeddings_for_entity("http://x/A", embedding_type="lexical")
        assert out == [{"vector": [0.1]}]
        assert vec.get_embeddings_for_entity.call_args.kwargs["namespace"] == "ns1"


class TestStoreEmbeddingsBatch:
    def test_injects_namespace_into_each_item(self):
        adapter, _graph, vec = _adapter("ns1")
        vec.store_embeddings_batch.return_value = [{"ok": True}]
        adapter.store_embeddings_batch([{"entity_uri": "http://x/A"}, {"entity_uri": "http://x/B"}])
        sent = vec.store_embeddings_batch.call_args[0][0]
        assert all(item["namespace"] == "ns1" for item in sent)

    def test_no_namespace_injection_when_unbound(self):
        adapter, _graph, vec = _adapter(namespace=None)
        vec.store_embeddings_batch.return_value = []
        adapter.store_embeddings_batch([{"entity_uri": "http://x/A"}])
        sent = vec.store_embeddings_batch.call_args[0][0]
        assert "namespace" not in sent[0]


class TestGetClassDefinition:
    def test_returns_first_comment_from_namespace_vertex(self):
        adapter, graph, _vec = _adapter("ns1")
        graph.get_vertex.return_value = {"comments": ["a definition", "second"]}
        assert adapter.get_class_definition("http://x/A") == "a definition"
        # First lookup uses the bound namespace.
        assert graph.get_vertex.call_args_list[0].kwargs["namespace"] == "ns1"

    def test_falls_back_to_global_lookup(self):
        adapter, graph, _vec = _adapter("ns1")
        # Namespace lookup returns no comments; global (namespace=None) has one.
        graph.get_vertex.side_effect = [
            {"comments": []},
            {"comments": ["global def"]},
        ]
        assert adapter.get_class_definition("http://x/A") == "global def"
        assert graph.get_vertex.call_args_list[1].kwargs["namespace"] is None

    def test_returns_empty_string_when_no_comments_anywhere(self):
        adapter, graph, _vec = _adapter("ns1")
        graph.get_vertex.side_effect = [None, None]
        assert adapter.get_class_definition("http://x/A") == ""


class TestOntologyOps:
    def test_create_ontology_returns_existing_when_present(self):
        adapter, graph, _vec = _adapter()
        graph.get_ontology_by_uri.return_value = {"id": "existing"}
        out = adapter.create_ontology({"uri": "http://o"})
        assert out == {"id": "existing"}
        graph.create_ontology.assert_not_called()

    def test_create_ontology_creates_when_absent(self):
        adapter, graph, _vec = _adapter()
        graph.get_ontology_by_uri.return_value = None
        graph.create_ontology.return_value = {"id": "new"}
        out = adapter.create_ontology({"uri": "http://o"})
        assert out == {"id": "new"}
        graph.create_ontology.assert_called_once()

    def test_get_ontology_by_uri_returns_when_found(self):
        adapter, graph, _vec = _adapter()
        graph.get_ontology_by_uri.return_value = {"id": "o1"}
        assert adapter.get_ontology_by_uri("http://o") == {"id": "o1"}

    def test_get_ontology_by_uri_raises_when_missing(self):
        adapter, graph, _vec = _adapter()
        graph.get_ontology_by_uri.return_value = None
        with pytest.raises(ValueError, match="not found"):
            adapter.get_ontology_by_uri("http://missing")


class TestUploadOntologyFile:
    def test_is_a_noop_returning_null_file_path(self):
        adapter, _graph, _vec = _adapter()
        out = adapter.upload_ontology_file("ont-1", b"@prefix x: <http://x> .")
        assert out == {"id": "ont-1", "file_path": None}
