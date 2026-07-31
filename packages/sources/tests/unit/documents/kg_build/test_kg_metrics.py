# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the kg_metrics ProgressMonitor.

The GraphRAG toolkit (>= 3.18.6) invokes ``ProgressMonitor.increment_*`` at
document boundaries, single-threaded from the main process. Our implementation
writes each increment straight to the shared per-source DynamoDB metrics record
via atomic ADD — plain Number counters, no cross-process distinct-set logic.

Key properties under test:
  - Each increment_* method issues one atomic_add of the mapped field.
  - Counts land under the dedicated PK=METRICS#{ns}, SK=KGBUILD#{ds} record.
  - A DDB error is swallowed (instrumentation never fails the build).
  - Metrics disabled / toolkit unavailable → a no-op monitor (never raises).

The toolkit is not a unit-test dependency, so a stub ``ProgressMonitor`` base is
injected into ``sys.modules`` for the tests that exercise the real DDB monitor.
"""

from __future__ import annotations

import importlib
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

_PM_MODULE = "graphrag_toolkit.lexical_graph.indexing.progress_monitor"


@contextmanager
def _stub_toolkit_progress_monitor():
    """Inject a minimal ``ProgressMonitor`` base at the toolkit's import path so
    ``make_progress_monitor`` can subclass it without the real toolkit installed.
    The parent packages are stubbed too so the dotted import resolves."""

    class ProgressMonitor:  # mirrors the toolkit's NoOp-able base
        def increment_llm_processed_documents(self, count: int = 1) -> None: ...
        def increment_llm_processed_chunks(self, count: int = 1) -> None: ...
        def increment_graph_processed_documents(self, count: int = 1) -> None: ...
        def increment_graph_processed_chunks(self, count: int = 1) -> None: ...
        def increment_vector_processed_documents(self, count: int = 1) -> None: ...
        def increment_vector_processed_chunks(self, count: int = 1) -> None: ...

    pm_mod = types.ModuleType(_PM_MODULE)
    pm_mod.ProgressMonitor = ProgressMonitor

    parents = [
        "graphrag_toolkit",
        "graphrag_toolkit.lexical_graph",
        "graphrag_toolkit.lexical_graph.indexing",
    ]
    added = {}
    for name in parents:
        if name not in sys.modules:
            added[name] = types.ModuleType(name)
    with patch.dict(sys.modules, {**added, _PM_MODULE: pm_mod}):
        yield


@pytest.fixture
def km():
    """Fresh kg_metrics module."""
    from coa_sources.documents.kg_build import kg_metrics

    importlib.reload(kg_metrics)
    return kg_metrics


def _monitor_with_mock_dao(km):
    """Build a real DDB ProgressMonitor with a stubbed toolkit base and a mocked
    DynamoDBDAO, so we can assert atomic_add calls without touching AWS.
    Returns (monitor, dao)."""
    mock_dao = MagicMock()
    with (
        _stub_toolkit_progress_monitor(),
        patch.object(km, "METRICS_ENABLED", True),
        patch("coa_common.dao.DynamoDBDAO", return_value=mock_dao),
    ):
        monitor = km.make_progress_monitor(table="tbl", region="us-west-2", namespace_id="ns1", doc_source_id="ds1")
    return monitor, mock_dao


class TestDdbProgressMonitor:
    def test_llm_chunks_increment_writes_chunks_llm(self, km):
        monitor, dao = _monitor_with_mock_dao(km)
        assert not isinstance(monitor, km.NoOpProgressMonitor)
        monitor.increment_llm_processed_chunks(5)
        dao.atomic_add.assert_called_once()
        key, incr = dao.atomic_add.call_args.args
        assert key == {"PK": "METRICS#ns1", "SK": "KGBUILD#ds1"}
        assert incr == {"chunks_llm": 5}

    def test_llm_documents_increment_writes_documents_processed(self, km):
        monitor, dao = _monitor_with_mock_dao(km)
        monitor.increment_llm_processed_documents(1)
        _, incr = dao.atomic_add.call_args.args
        assert incr == {"documents_processed": 1}

    def test_graph_and_vector_chunks_map_to_fields(self, km):
        monitor, dao = _monitor_with_mock_dao(km)
        monitor.increment_graph_processed_chunks(3)
        monitor.increment_vector_processed_chunks(4)
        fields = [c.args[1] for c in dao.atomic_add.call_args_list]
        assert {"chunks_graph": 3} in fields
        assert {"chunks_embed": 4} in fields

    def test_document_level_graph_vector_are_noops(self, km):
        """Only chunk-level graph/vector progress is surfaced today; the
        document-level graph/vector callbacks must not write."""
        monitor, dao = _monitor_with_mock_dao(km)
        monitor.increment_graph_processed_documents(1)
        monitor.increment_vector_processed_documents(1)
        dao.atomic_add.assert_not_called()

    def test_zero_or_negative_count_does_not_write(self, km):
        monitor, dao = _monitor_with_mock_dao(km)
        monitor.increment_llm_processed_chunks(0)
        monitor.increment_graph_processed_chunks(-1)
        dao.atomic_add.assert_not_called()

    def test_ddb_error_is_swallowed(self, km):
        monitor, dao = _monitor_with_mock_dao(km)
        dao.atomic_add.side_effect = RuntimeError("DDB down")
        # Must not raise — instrumentation is best-effort.
        monitor.increment_llm_processed_chunks(1)


class TestNoOpFallback:
    def test_disabled_returns_noop(self, km):
        with patch.object(km, "METRICS_ENABLED", False):
            monitor = km.make_progress_monitor(table="t", region="r", namespace_id="n", doc_source_id="d")
        assert isinstance(monitor, km.NoOpProgressMonitor)
        # No-op methods accept the calls and do nothing.
        monitor.increment_llm_processed_chunks(9)
        monitor.increment_graph_processed_chunks(9)

    def test_noop_when_toolkit_missing(self, km):
        """With the toolkit absent, make_progress_monitor falls back to no-op
        rather than raising."""
        # Ensure the toolkit import path is unavailable.
        with patch.dict(sys.modules, {_PM_MODULE: None}), patch.object(km, "METRICS_ENABLED", True):
            monitor = km.make_progress_monitor(table="t", region="r", namespace_id="n", doc_source_id="d")
        assert isinstance(monitor, km.NoOpProgressMonitor)


class TestResetMetrics:
    def test_deletes_prior_record(self, km):
        """A (re)build clears the leftover record so counts don't accumulate."""
        mock_dao = MagicMock()
        with (
            patch.object(km, "METRICS_ENABLED", True),
            patch("coa_common.dao.DynamoDBDAO", return_value=mock_dao),
        ):
            km.reset_metrics(table="tbl", region="us-west-2", namespace_id="ns1", doc_source_id="ds1")
        mock_dao.delete.assert_called_once_with({"PK": "METRICS#ns1", "SK": "KGBUILD#ds1"})

    def test_disabled_is_noop(self, km):
        mock_dao = MagicMock()
        with (
            patch.object(km, "METRICS_ENABLED", False),
            patch("coa_common.dao.DynamoDBDAO", return_value=mock_dao),
        ):
            km.reset_metrics(table="t", region="r", namespace_id="n", doc_source_id="d")
        mock_dao.delete.assert_not_called()

    def test_ddb_error_is_swallowed(self, km):
        """A delete failure must never fail the build."""
        mock_dao = MagicMock()
        mock_dao.delete.side_effect = RuntimeError("DDB down")
        with (
            patch.object(km, "METRICS_ENABLED", True),
            patch("coa_common.dao.DynamoDBDAO", return_value=mock_dao),
        ):
            # Must not raise.
            km.reset_metrics(table="t", region="r", namespace_id="n", doc_source_id="d")


class TestMetricsKey:
    def test_dedicated_partition(self, km):
        assert km._metrics_key("ns", "ds") == {"PK": "METRICS#ns", "SK": "KGBUILD#ds"}
