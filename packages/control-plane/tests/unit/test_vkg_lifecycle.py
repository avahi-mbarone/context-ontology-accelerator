# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for VKG teardown on namespace delete.

Tests the actual production functions (cleanup.teardown_vkg_service, invoked
by the deletion pipeline's delete_platform step) with boto3 mocked at the
module level. Provisioning tests live in
infra/test/lambdas/test_vkg_reload_handler.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from coa_common.constants import RESOURCE_PREFIX


@pytest.mark.unit
class TestTeardownVkgService:
    """Tests for teardown_vkg_service in cleanup.py."""

    ENV = {
        "AWS_REGION": "us-east-1",
        "RESOURCE_PREFIX": "coa-dev",
        "VKG_CLUSTER_ARN": "arn:aws:ecs:us-east-1:111:cluster/vkg",
        "CLOUD_MAP_NAMESPACE_ID": "ns-abc123",
        "NAMESPACES_TABLE": "test-ns-table",
    }

    @patch.dict("os.environ", ENV)
    @patch("coa_control_plane.namespace.cleanup.boto3")
    def test_deletes_service_and_cloud_map(self, mock_boto3):
        mock_ecs = MagicMock()
        mock_sd = MagicMock()
        mock_sd.exceptions.ResourceInUse = type("ResourceInUse", (Exception,), {})
        svc_paginator = MagicMock()
        svc_paginator.paginate.return_value = [{"Services": [{"Name": "vkg-test-ns", "Id": "svc-id-1"}]}]
        inst_paginator = MagicMock()
        inst_paginator.paginate.return_value = [{"Instances": [{"Id": "inst-1"}]}]
        mock_sd.get_paginator.side_effect = lambda name: svc_paginator if name == "list_services" else inst_paginator

        def client_fn(service, **kw):
            return mock_ecs if service == "ecs" else mock_sd

        mock_boto3.client.side_effect = client_fn

        from coa_control_plane.namespace.cleanup import (
            teardown_vkg_service,
        )

        teardown_vkg_service("test-ns")

        mock_ecs.delete_service.assert_called_once_with(
            cluster="arn:aws:ecs:us-east-1:111:cluster/vkg",
            service=f"{RESOURCE_PREFIX}-dev-vkg-test-ns",
            force=True,
        )
        mock_sd.deregister_instance.assert_called_once_with(ServiceId="svc-id-1", InstanceId="inst-1")
        mock_sd.delete_service.assert_called_once_with(Id="svc-id-1")

    @patch.dict("os.environ", ENV)
    @patch("coa_control_plane.namespace.cleanup.time")
    @patch("coa_control_plane.namespace.cleanup.boto3")
    def test_retries_cloud_map_delete_on_resource_in_use(self, mock_boto3, mock_time):
        mock_ecs = MagicMock()
        mock_sd = MagicMock()
        mock_sd.exceptions.ResourceInUse = type("ResourceInUse", (Exception,), {})
        svc_paginator = MagicMock()
        svc_paginator.paginate.return_value = [{"Services": [{"Name": "vkg-test-ns", "Id": "svc-id-1"}]}]
        inst_paginator = MagicMock()
        inst_paginator.paginate.return_value = [{"Instances": []}]
        mock_sd.get_paginator.side_effect = lambda name: svc_paginator if name == "list_services" else inst_paginator
        mock_sd.delete_service.side_effect = [
            mock_sd.exceptions.ResourceInUse("in use"),
            mock_sd.exceptions.ResourceInUse("in use"),
            None,
        ]

        def client_fn(service, **kw):
            return mock_ecs if service == "ecs" else mock_sd

        mock_boto3.client.side_effect = client_fn

        from coa_control_plane.namespace.cleanup import (
            teardown_vkg_service,
        )

        teardown_vkg_service("test-ns")

        assert mock_sd.delete_service.call_count == 3
        assert mock_time.sleep.call_count == 2

    @patch.dict("os.environ", ENV)
    @patch("coa_control_plane.namespace.cleanup.boto3")
    def test_handles_service_not_found(self, mock_boto3):
        mock_ecs = MagicMock()
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.delete_service.side_effect = mock_ecs.exceptions.ServiceNotFoundException("not found")

        mock_sd = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Services": []}]
        mock_sd.get_paginator.return_value = paginator

        def client_fn(service, **kw):
            return mock_ecs if service == "ecs" else mock_sd

        mock_boto3.client.side_effect = client_fn

        from coa_control_plane.namespace.cleanup import (
            teardown_vkg_service,
        )

        # Should not raise
        teardown_vkg_service("nonexistent-ns")

    @patch.dict("os.environ", {"AWS_REGION": "us-east-1", "VKG_CLUSTER_ARN": "", "RESOURCE_PREFIX": ""})
    @patch("coa_control_plane.namespace.cleanup.boto3")
    def test_skips_when_cluster_not_configured(self, mock_boto3):
        from coa_control_plane.namespace.cleanup import (
            teardown_vkg_service,
        )

        teardown_vkg_service("skip-ns")
        mock_boto3.client.assert_not_called()
