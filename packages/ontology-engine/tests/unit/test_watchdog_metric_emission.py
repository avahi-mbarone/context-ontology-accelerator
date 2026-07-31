# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the watchdog's out-of-process OOM observability heartbeat.

A 50k induction SIGKILL/exit-137 (OOM) runs neither ``except`` nor ``finally``,
so ``emit_induction_job_metrics`` (in the finally block) never fires and the
induction dashboard is left blank for the crashed run. The fix: the 45s liveness
watchdog ALSO emits a lightweight ``InductionHeartbeat`` + ``InductionWorkerMemoryBytes``
each tick, so a crashed run leaves a partial trail (last heartbeat dates the
crash; the RSS high-water captures the pre-OOM ramp between the 1-min ECS
samples).

These tests assert (a) the loop emits the heartbeat EVERY tick (not just once,
not just importable), (b) the emit publishes both metric names dimensioned by
NamespaceId, and (c) a PutMetricData failure in a tick is best-effort — it must
NOT stop subsequent ticks.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _NTickEvent:
    """Counting stop-event: False for the first ``ticks`` waits (one heartbeat
    each), then True to break the ``while not stop_event.wait(...)`` loop.

    Deterministic — drives the real ``_watchdog_loop`` with no wall clock.
    """

    def __init__(self, ticks: int) -> None:
        self.ticks = ticks
        self.calls = 0

    def wait(self, _timeout) -> bool:
        self.calls += 1
        return self.calls > self.ticks


class _FakeCloudWatch:
    """Captures put_metric_data calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_metric_data(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _RaisingCloudWatch:
    """Every put_metric_data raises — models a broken CloudWatch seam."""

    def __init__(self) -> None:
        self.calls = 0

    def put_metric_data(self, **kwargs) -> None:
        self.calls += 1
        raise RuntimeError("synthetic PutMetricData failure")


class TestWatchdogEmitsHeartbeatPerTick:
    """The loop calls the heartbeat emit once per tick — the OOM-visibility trail."""

    def test_loop_emits_heartbeat_every_tick(self, monkeypatch):
        import coa_ontology.induce_catalog as ic
        from coa_ontology import dynamo_store as ds

        touch_calls: list[tuple[str, str]] = []
        emit_calls: list[tuple] = []
        monkeypatch.setattr(ds, "touch_job", lambda job_id, namespace: touch_calls.append((job_id, namespace)))
        # Spy on the emit as referenced from the induce_catalog module namespace
        # (the same seam ``emit_induction_job_metrics`` is patched at).
        monkeypatch.setattr(
            ic,
            "emit_induction_heartbeat_metrics",
            lambda namespace_id, region=None, cloudwatch_client=None: emit_calls.append((namespace_id, region)),
        )

        ic._watchdog_loop("j-hb", "ns-hb", _NTickEvent(3), interval=0, region="us-west-2")

        # One heartbeat emit per tick — absent-after-present is the crash signal.
        assert touch_calls == [("j-hb", "ns-hb")] * 3
        assert emit_calls == [("ns-hb", "us-west-2")] * 3


class TestHeartbeatEmitContent:
    """The emit publishes both metric names dimensioned by NamespaceId."""

    def test_emits_heartbeat_and_memory_bytes(self):
        from coa_common.bedrock_metrics import (
            METRICS_NAMESPACE,
            emit_induction_heartbeat_metrics,
        )

        fake = _FakeCloudWatch()
        emit_induction_heartbeat_metrics("ns-42", region="us-west-2", cloudwatch_client=fake)

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["Namespace"] == METRICS_NAMESPACE
        by_name = {d["MetricName"]: d for d in call["MetricData"]}

        assert "InductionHeartbeat" in by_name
        assert by_name["InductionHeartbeat"]["Value"] == 1.0
        assert by_name["InductionHeartbeat"]["Dimensions"] == [{"Name": "NamespaceId", "Value": "ns-42"}]

        assert "InductionWorkerMemoryBytes" in by_name
        # RSS high-water is a positive byte count on Linux (the induction task's
        # platform and the test host).
        assert by_name["InductionWorkerMemoryBytes"]["Value"] > 0
        assert by_name["InductionWorkerMemoryBytes"]["Dimensions"] == [{"Name": "NamespaceId", "Value": "ns-42"}]


class TestHeartbeatIsBestEffort:
    """A PutMetricData failure in a tick must not raise or stop later ticks."""

    def test_helper_swallows_put_metric_data_failure(self):
        from coa_common.bedrock_metrics import emit_induction_heartbeat_metrics

        # Must not raise even though the client blows up.
        emit_induction_heartbeat_metrics("ns-x", cloudwatch_client=_RaisingCloudWatch())

    def test_loop_continues_after_emit_failure(self, monkeypatch):
        import coa_ontology.induce_catalog as ic
        from coa_common import bedrock_metrics
        from coa_ontology import dynamo_store as ds

        touch_calls: list[tuple[str, str]] = []
        monkeypatch.setattr(ds, "touch_job", lambda job_id, namespace: touch_calls.append((job_id, namespace)))
        # Drive the REAL emit (not a spy) but force its CloudWatch client to
        # raise, so a genuine PutMetricData failure is exercised each tick.
        raising = _RaisingCloudWatch()
        monkeypatch.setattr(bedrock_metrics, "_cloudwatch_client", lambda region: raising)

        ic._watchdog_loop("j-hb", "ns-hb", _NTickEvent(3), interval=0)

        # All three ticks ran despite the emit failing on every one — best-effort
        # means the touch heartbeat AND subsequent emits keep going.
        assert touch_calls == [("j-hb", "ns-hb")] * 3
        assert raising.calls == 3
