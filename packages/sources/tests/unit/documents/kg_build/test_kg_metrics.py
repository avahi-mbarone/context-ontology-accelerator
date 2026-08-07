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
import threading
import time
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


class TestCounterSnapshot:
    """Increments mirror into an in-process snapshot for the heartbeat to read.

    The heartbeat reports progress deltas without a DynamoDB read per beat, so
    every DDB-bound increment must also land in the local mirror.
    """

    def test_increment_mirrors_into_snapshot(self, km):
        monitor, _ = _monitor_with_mock_dao(km)
        monitor.increment_llm_processed_chunks(7)
        monitor.increment_graph_processed_chunks(3)
        assert km.counter_snapshot() == {"chunks_llm": 7, "chunks_graph": 3}

    def test_increments_accumulate(self, km):
        monitor, _ = _monitor_with_mock_dao(km)
        monitor.increment_llm_processed_chunks(2)
        monitor.increment_llm_processed_chunks(5)
        assert km.counter_snapshot()["chunks_llm"] == 7

    def test_snapshot_is_a_copy(self, km):
        monitor, _ = _monitor_with_mock_dao(km)
        monitor.increment_llm_processed_chunks(1)
        km.counter_snapshot()["chunks_llm"] = 999
        assert km.counter_snapshot()["chunks_llm"] == 1

    def test_ddb_failure_still_mirrors_locally(self, km):
        # The heartbeat must keep reporting progress even when DDB writes fail,
        # since that is exactly when operators are watching the logs.
        monitor, dao = _monitor_with_mock_dao(km)
        dao.atomic_add.side_effect = RuntimeError("ddb down")
        monitor.increment_llm_processed_chunks(4)
        assert km.counter_snapshot()["chunks_llm"] == 4


class TestHeartbeat:
    def test_disabled_interval_starts_no_thread(self, km):
        with patch.object(km, "HEARTBEAT_INTERVAL_SECONDS", 0):
            before = threading.active_count()
            stop = km.start_heartbeat(namespace_id="ns", doc_source_id="ds")
        assert threading.active_count() == before
        assert not stop.is_set()

    def test_emits_liveness_line_with_elapsed_and_counters(self, km):
        events: list[tuple[str, dict]] = []

        def capture(event, **kwargs):
            events.append((event, kwargs))

        monitor, _ = _monitor_with_mock_dao(km)
        monitor.increment_llm_processed_chunks(11)

        with (
            patch.object(km, "HEARTBEAT_INTERVAL_SECONDS", 0.01),
            patch.object(km.logger, "info", side_effect=capture),
        ):
            stop = km.start_heartbeat(namespace_id="ns", doc_source_id="ds")
            deadline = time.time() + 5
            while time.time() < deadline and not any(e == "kg_build heartbeat" for e, _ in events):
                time.sleep(0.01)
            stop.set()

        beats = [kwargs for event, kwargs in events if event == "kg_build heartbeat"]
        assert beats, "heartbeat never emitted a liveness line"
        first = beats[0]
        assert first["namespace_id"] == "ns"
        assert first["doc_source_id"] == "ds"
        assert first["chunks_llm"] == 11
        assert first["chunks_llm_delta"] == 11
        assert first["elapsed_seconds"] >= 0

    def test_stop_event_halts_beating(self, km):
        events: list[str] = []
        # A long interval would leave the thread parked inside stop.wait() for the
        # full period regardless of the event, so keep it short and assert that no
        # further beats are emitted rather than racing on thread liveness.
        with (
            patch.object(km, "HEARTBEAT_INTERVAL_SECONDS", 0.01),
            patch.object(km.logger, "info", side_effect=lambda e, **kw: events.append(e)),
        ):
            stop = km.start_heartbeat(namespace_id="ns", doc_source_id="ds")
            deadline = time.time() + 5
            while time.time() < deadline and events.count("kg_build heartbeat") < 1:
                time.sleep(0.01)
            stop.set()
            # Give the thread more than one interval to wake up and exit.
            time.sleep(0.2)
            after_stop = events.count("kg_build heartbeat")
            time.sleep(0.2)
            assert events.count("kg_build heartbeat") == after_stop, "heartbeat kept beating after stop was set"

    def test_zero_delta_beat_still_emitted_when_stalled(self, km):
        # A beat with all-zero deltas is the signal that distinguishes a stalled
        # task from a dead one, so it must not be suppressed.
        events: list[tuple[str, dict]] = []
        monitor, _ = _monitor_with_mock_dao(km)
        monitor.increment_llm_processed_chunks(5)

        with (
            patch.object(km, "HEARTBEAT_INTERVAL_SECONDS", 0.01),
            patch.object(km.logger, "info", side_effect=lambda e, **kw: events.append((e, kw))),
        ):
            stop = km.start_heartbeat(namespace_id="ns", doc_source_id="ds")
            deadline = time.time() + 5
            while time.time() < deadline and len([1 for e, _ in events if e == "kg_build heartbeat"]) < 2:
                time.sleep(0.01)
            stop.set()

        beats = [kw for e, kw in events if e == "kg_build heartbeat"]
        assert len(beats) >= 2
        assert beats[1]["chunks_llm_delta"] == 0
        assert beats[1]["chunks_llm"] == 5


class TestRssMb:
    def test_returns_float_or_none(self, km):
        rss = km._rss_mb()
        assert rss is None or (isinstance(rss, float) and rss > 0)

    def test_missing_procfs_returns_none(self, km):
        with patch("builtins.open", side_effect=OSError("no procfs")):
            assert km._rss_mb() is None
