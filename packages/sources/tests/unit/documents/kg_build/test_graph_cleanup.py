# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Deletion Pipeline Stage 2: graph_cleanup.py.

All external dependencies (GraphStoreFactory, VectorStoreFactory,
LexicalGraphIndex, DeleteSources) are mocked so tests run without
any AWS infrastructure.

graph_cleanup.py imports graphrag_toolkit inside main() (after applying the
graphrag monkey-patches), so we pre-stub the entire package in sys.modules before
importing the module under test. This is the same approach used for other heavy
deps that aren't installed in the dev venv.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# graphrag_toolkit stub — injected into sys.modules before graph_cleanup runs so
# the `from graphrag_toolkit...` lines inside main() resolve.
# ---------------------------------------------------------------------------


def _make_graphrag_stub() -> None:
    """Register minimal graphrag_toolkit stubs in sys.modules."""
    root = types.ModuleType("graphrag_toolkit")
    lexical = types.ModuleType("graphrag_toolkit.lexical_graph")
    storage = types.ModuleType("graphrag_toolkit.lexical_graph.storage")
    indexing = types.ModuleType("graphrag_toolkit.lexical_graph.indexing")
    build_mod = types.ModuleType("graphrag_toolkit.lexical_graph.indexing.build")
    delete_mod = types.ModuleType("graphrag_toolkit.lexical_graph.indexing.build.delete_sources")

    lexical.LexicalGraphIndex = MagicMock()
    storage.GraphStoreFactory = MagicMock()
    storage.VectorStoreFactory = MagicMock()
    delete_mod.DeleteSources = MagicMock()

    for name, mod in [
        ("graphrag_toolkit", root),
        ("graphrag_toolkit.lexical_graph", lexical),
        ("graphrag_toolkit.lexical_graph.storage", storage),
        ("graphrag_toolkit.lexical_graph.indexing", indexing),
        ("graphrag_toolkit.lexical_graph.indexing.build", build_mod),
        ("graphrag_toolkit.lexical_graph.indexing.build.delete_sources", delete_mod),
    ]:
        sys.modules.setdefault(name, mod)


_make_graphrag_stub()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE_ENV = {
    "NAMESPACE_ID": "890dd75f-649c-4e95-8981-f9dc33a518ea",
    "DOC_SOURCE_ID": "01KRPTQ3075C5C6NV825ZQ5WW4",
    "TENANT_ID": "890dd75f649c4e958981f9dc3",
    "NEPTUNE_ENDPOINT": "my-neptune.us-east-1.neptune.amazonaws.com",
    "OPENSEARCH_ENDPOINT": "abc123.us-east-1.aoss.amazonaws.com",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key, val in _BASE_ENV.items():
        monkeypatch.setenv(key, val)
    _evict_graph_cleanup()


def _evict_graph_cleanup():
    """Fully evict graph_cleanup so re-import re-executes module-level code."""
    sys.modules.pop("coa_sources.documents.kg_build.graph_cleanup", None)
    # Also remove the attribute from the parent package so re-import is fresh
    pkg = sys.modules.get("coa_sources.documents.kg_build")
    if pkg and hasattr(pkg, "graph_cleanup"):
        delattr(pkg, "graph_cleanup")


@pytest.fixture()
def mod():
    _evict_graph_cleanup()
    from coa_sources.documents.kg_build import graph_cleanup

    return graph_cleanup


def _make_store_mocks(mock_gsf, mock_vsf):
    """Wire up GraphStoreFactory / VectorStoreFactory context-manager mocks."""
    mock_gs = MagicMock()
    mock_vs = MagicMock()
    mock_gsf.for_graph_store.return_value.__enter__ = MagicMock(return_value=mock_gs)
    mock_gsf.for_graph_store.return_value.__exit__ = MagicMock(return_value=False)
    mock_vsf.for_vector_store.return_value.__enter__ = MagicMock(return_value=mock_vs)
    mock_vsf.for_vector_store.return_value.__exit__ = MagicMock(return_value=False)
    return mock_gs, mock_vs


def _make_graph_index(mock_idx_cls, sources):
    """Return a mock LexicalGraphIndex with pre-configured get_sources result."""
    mock_index = MagicMock()
    mock_index.get_sources.return_value = sources
    mock_idx_cls.return_value = mock_index
    return mock_index


# Patch targets — graph_cleanup imports these names INSIDE main(), after applying
# the graphrag monkey-patches (the AOSS NEXTGEN fix must land before
# LexicalGraphIndex/VectorStoreFactory bind their own references). Function-local
# imports resolve from the source module at call time, so patch them there rather
# than in the graph_cleanup namespace.
_P_GSF = "graphrag_toolkit.lexical_graph.storage.GraphStoreFactory"
_P_VSF = "graphrag_toolkit.lexical_graph.storage.VectorStoreFactory"
_P_IDX = "graphrag_toolkit.lexical_graph.LexicalGraphIndex"
_P_DS = "graphrag_toolkit.lexical_graph.indexing.build.delete_sources.DeleteSources"


# ---------------------------------------------------------------------------
# 1. Environment validation
# ---------------------------------------------------------------------------


class TestEnvValidation:
    @pytest.mark.parametrize(
        "missing_var",
        ["NAMESPACE_ID", "DOC_SOURCE_ID", "TENANT_ID", "NEPTUNE_ENDPOINT", "OPENSEARCH_ENDPOINT"],
    )
    def test_missing_env_var_raises(self, missing_var, monkeypatch, mod):
        monkeypatch.delenv(missing_var)
        _evict_graph_cleanup()
        from coa_sources.documents.kg_build import graph_cleanup

        with pytest.raises(RuntimeError, match="Missing required environment variables"):
            graph_cleanup.main()

    def test_all_env_vars_present_does_not_raise_on_validation(self, mod):
        """Validation itself should not raise when all vars are set."""
        missing = [
            name
            for name, val in [
                ("NAMESPACE_ID", mod.NAMESPACE_ID),
                ("DOC_SOURCE_ID", mod.DOC_SOURCE_ID),
                ("TENANT_ID", mod.TENANT_ID),
                ("NEPTUNE_ENDPOINT", mod.NEPTUNE_ENDPOINT),
                ("OPENSEARCH_ENDPOINT", mod.OPENSEARCH_ENDPOINT),
            ]
            if not val
        ]
        assert missing == []


# ---------------------------------------------------------------------------
# 2. Store URI construction
# ---------------------------------------------------------------------------


class TestStoreUris:
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_neptune_uri_uses_port_8182(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [])

        mod.main()

        mock_gsf.for_graph_store.assert_called_once_with(f"neptune-db://{_BASE_ENV['NEPTUNE_ENDPOINT']}:8182")

    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_opensearch_uri_uses_aoss_scheme(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [])

        mod.main()

        mock_vsf.for_vector_store.assert_called_once_with(f"aoss://{_BASE_ENV['OPENSEARCH_ENDPOINT']}:443")


# ---------------------------------------------------------------------------
# 3. LexicalGraphIndex construction
# ---------------------------------------------------------------------------


class TestGraphIndexConstruction:
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_index_created_with_tenant_id(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        mock_gs, mock_vs = _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [])

        mod.main()

        mock_idx_cls.assert_called_once_with(mock_gs, mock_vs, tenant_id=_BASE_ENV["TENANT_ID"])

    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_get_sources_filtered_by_doc_source_id(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        mock_index = _make_graph_index(mock_idx_cls, [])

        mod.main()

        mock_index.get_sources.assert_called_once_with(filter={"doc_source_id": _BASE_ENV["DOC_SOURCE_ID"]})


# ---------------------------------------------------------------------------
# 4. No-sources path
# ---------------------------------------------------------------------------


class TestNoSourcesFound:
    @patch(_P_DS)
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_no_sources_does_not_call_delete(self, mock_vsf, mock_gsf, mock_idx_cls, mock_ds_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [])

        mod.main()

        mock_ds_cls.assert_not_called()

    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_no_sources_completes_without_error(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [])

        mod.main()  # should not raise


# ---------------------------------------------------------------------------
# 5. Happy path — sources found and deleted
# ---------------------------------------------------------------------------


class TestDeleteSources:
    @patch(_P_DS)
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_delete_called_with_source_ids(self, mock_vsf, mock_gsf, mock_idx_cls, mock_ds_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        sources = [{"sourceId": "src-001"}, {"sourceId": "src-002"}]
        _make_graph_index(mock_idx_cls, sources)
        mock_ds = MagicMock()
        mock_ds.delete_source_documents.return_value = ["src-001", "src-002"]
        mock_ds_cls.return_value = mock_ds

        mod.main()

        mock_ds.delete_source_documents.assert_called_once_with(["src-001", "src-002"])

    @patch(_P_DS)
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_delete_sources_uses_tenant_scoped_stores(self, mock_vsf, mock_gsf, mock_idx_cls, mock_ds_cls, mod):
        """DeleteSources must receive graph_index.graph_store / .vector_store
        (the tenant-scoped wrappers), not the raw stores."""
        _make_store_mocks(mock_gsf, mock_vsf)
        mock_index = _make_graph_index(mock_idx_cls, [{"sourceId": "src-001"}])
        mock_ds = MagicMock()
        mock_ds.delete_source_documents.return_value = ["src-001"]
        mock_ds_cls.return_value = mock_ds

        mod.main()

        mock_ds_cls.assert_called_once_with(
            graph_store=mock_index.graph_store,
            vector_store=mock_index.vector_store,
            batch_size=200,
            num_workers=1,
        )

    @patch(_P_DS)
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_batch_size_is_200(self, mock_vsf, mock_gsf, mock_idx_cls, mock_ds_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [{"sourceId": "src-001"}])
        mock_ds = MagicMock()
        mock_ds.delete_source_documents.return_value = ["src-001"]
        mock_ds_cls.return_value = mock_ds

        mod.main()

        _, kwargs = mock_ds_cls.call_args
        assert kwargs["batch_size"] == 200
        assert kwargs["num_workers"] == 1

    @patch(_P_DS)
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_single_source_deleted(self, mock_vsf, mock_gsf, mock_idx_cls, mock_ds_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [{"sourceId": "src-only"}])
        mock_ds = MagicMock()
        mock_ds.delete_source_documents.return_value = ["src-only"]
        mock_ds_cls.return_value = mock_ds

        mod.main()

        mock_ds.delete_source_documents.assert_called_once_with(["src-only"])

    @patch(_P_DS)
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_multiple_sources_all_passed_to_delete(self, mock_vsf, mock_gsf, mock_idx_cls, mock_ds_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        sources = [{"sourceId": f"src-{i}"} for i in range(5)]
        _make_graph_index(mock_idx_cls, sources)
        mock_ds = MagicMock()
        mock_ds.delete_source_documents.return_value = [s["sourceId"] for s in sources]
        mock_ds_cls.return_value = mock_ds

        mod.main()

        ids_passed = mock_ds.delete_source_documents.call_args[0][0]
        assert ids_passed == [f"src-{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# 6. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @patch(_P_DS)
    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_delete_failure_propagates(self, mock_vsf, mock_gsf, mock_idx_cls, mock_ds_cls, mod):
        """If DeleteSources raises, the exception should propagate (ECS task fails → Step Functions catches it)."""
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [{"sourceId": "src-001"}])
        mock_ds = MagicMock()
        mock_ds.delete_source_documents.side_effect = RuntimeError("Neptune OOM")
        mock_ds_cls.return_value = mock_ds

        with pytest.raises(RuntimeError, match="Neptune OOM"):
            mod.main()

    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_get_sources_failure_propagates(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        mock_index = _make_graph_index(mock_idx_cls, [])
        mock_index.get_sources.side_effect = RuntimeError("Neptune connection refused")

        with pytest.raises(RuntimeError, match="Neptune connection refused"):
            mod.main()


# ---------------------------------------------------------------------------
# 7. graphrag monkey-patches applied on the deletion path
# ---------------------------------------------------------------------------


class TestGraphragPatchesApplied:
    """Regression: the deletion task must apply the same graphrag monkey-patches
    as the build task.

    Deletion reads the vector indexes (``delete_embeddings`` →
    ``_get_existing_doc_ids_for_ids`` → ``paginated_search``), so it hits the same
    AOSS failure modes. Unpatched, a ``429 circuit_breaking_exception`` from the
    NEXTGEN heap breaker was neither retried nor surfaced: the toolkit's handler is
    ``except Exception as ee: ... raise e`` with ``e`` unbound, so it raised
    ``UnboundLocalError``, masked the real 429, failed the ECS task, and left the
    namespace's embeddings orphaned half-deleted (observed 2026-07-27 on both
    SEC-10-Q namespaces; the defect is still present in the pinned 3.18.7).
    """

    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_main_applies_all_three_patches(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [])

        with (
            patch.object(mod, "_patch_graphrag_toolkit_for_aoss_nextgen") as p_aoss,
            patch.object(mod, "_patch_graphrag_paginated_search_retry") as p_page,
            patch.object(mod, "_patch_graphrag_bulk_ingest_retry") as p_bulk,
        ):
            mod.main()

        p_aoss.assert_called_once()
        p_page.assert_called_once()
        p_bulk.assert_called_once()

    @patch(_P_IDX)
    @patch(_P_GSF)
    @patch(_P_VSF)
    def test_patches_applied_before_stores_are_built(self, mock_vsf, mock_gsf, mock_idx_cls, mod):
        """Ordering is load-bearing: the AOSS NEXTGEN patch must replace
        ``index_exists`` before ``VectorStoreFactory`` binds its own reference."""
        calls: list[str] = []
        _make_store_mocks(mock_gsf, mock_vsf)
        _make_graph_index(mock_idx_cls, [])
        mock_vsf.for_vector_store.side_effect = lambda *a, **k: (
            calls.append("vector_store"),
            MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False)),
        )[1]

        with (
            patch.object(mod, "_patch_graphrag_toolkit_for_aoss_nextgen", side_effect=lambda: calls.append("patch")),
            patch.object(mod, "_patch_graphrag_paginated_search_retry"),
            patch.object(mod, "_patch_graphrag_bulk_ingest_retry"),
        ):
            mod.main()

        assert calls.index("patch") < calls.index("vector_store"), f"patch must precede store build, got {calls}"
