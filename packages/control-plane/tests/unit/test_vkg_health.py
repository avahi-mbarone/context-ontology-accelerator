# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for VKG health resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from coa_common.constants import RESOURCE_PREFIX

MODULE = "coa_control_plane.namespace.vkg_health"


@pytest.fixture(autouse=True)
def reset_client():
    import coa_control_plane.namespace.vkg_health as mod

    mod._ecs = None
    yield
    mod._ecs = None


def _running(running, desired=1, status="ACTIVE", deployments=None):
    svc = {"status": status, "runningCount": running, "desiredCount": desired}
    if deployments is not None:
        svc["deployments"] = deployments
    return {"services": [svc]}


@pytest.mark.unit
class TestResolveVkgHealth:
    def test_unknown_when_cluster_not_configured(self, monkeypatch):
        monkeypatch.delenv("VKG_CLUSTER_ARN", raising=False)
        from coa_control_plane.namespace.vkg_health import resolve_vkg_health

        assert resolve_vkg_health("ns-1") == "UNKNOWN"

    def test_unknown_when_namespace_empty(self, monkeypatch):
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        from coa_control_plane.namespace.vkg_health import resolve_vkg_health

        assert resolve_vkg_health("") == "UNKNOWN"

    def test_healthy_when_service_running(self, monkeypatch):
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", "coa-dev")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            client.describe_services.return_value = _running(1, 1)

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            assert resolve_vkg_health("ns-1") == "HEALTHY"
            client.describe_services.assert_called_once_with(
                cluster="arn:cluster", services=[f"{RESOURCE_PREFIX}-dev-vkg-ns-1"]
            )

    def test_unavailable_when_no_running_tasks(self, monkeypatch):
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", "coa-dev")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            client.describe_services.return_value = _running(0, 1)

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            assert resolve_vkg_health("ns-1") == "UNAVAILABLE"

    def test_provisioning_when_starting_up(self, monkeypatch):
        """A service that is not yet serving but whose primary deployment is rolling
        out is starting up, not broken."""
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", "coa-dev")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            client.describe_services.return_value = _running(
                0, 1, deployments=[{"status": "PRIMARY", "rolloutState": "IN_PROGRESS"}]
            )

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            assert resolve_vkg_health("ns-1") == "PROVISIONING"

    def test_unavailable_when_not_running_and_rollout_completed(self, monkeypatch):
        """A service that finished rolling out but still has no running tasks is down,
        not merely starting — so it must be UNAVAILABLE, not PROVISIONING."""
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", "coa-dev")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            client.describe_services.return_value = _running(
                0, 1, deployments=[{"status": "PRIMARY", "rolloutState": "COMPLETED"}]
            )

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            assert resolve_vkg_health("ns-1") == "UNAVAILABLE"

    def test_unknown_when_service_missing(self, monkeypatch):
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", "coa-dev")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            # A non-existent service comes back under `failures`, not `services`.
            client.describe_services.return_value = {"services": [], "failures": [{"reason": "MISSING"}]}

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            assert resolve_vkg_health("ns-1") == "UNKNOWN"

    def test_inactive_service_is_unknown(self, monkeypatch):
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", "coa-dev")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            client.describe_services.return_value = _running(1, 1, status="INACTIVE")

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            assert resolve_vkg_health("ns-1") == "UNKNOWN"

    def test_unknown_on_ecs_error(self, monkeypatch):
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", "coa-dev")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            client.describe_services.side_effect = RuntimeError("ecs boom")

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            assert resolve_vkg_health("ns-1") == "UNKNOWN"

    def test_prefix_trailing_dash_normalized(self, monkeypatch):
        monkeypatch.setenv("VKG_CLUSTER_ARN", "arn:cluster")
        monkeypatch.setenv("RESOURCE_PREFIX", f"{RESOURCE_PREFIX}-dev-")
        with patch(f"{MODULE}._ecs_client") as mock:
            client = MagicMock()
            mock.return_value = client
            client.describe_services.return_value = _running(1, 1)

            from coa_control_plane.namespace.vkg_health import resolve_vkg_health

            resolve_vkg_health("ns-1")
            client.describe_services.assert_called_once_with(
                cluster="arn:cluster", services=[f"{RESOURCE_PREFIX}-dev-vkg-ns-1"]
            )
