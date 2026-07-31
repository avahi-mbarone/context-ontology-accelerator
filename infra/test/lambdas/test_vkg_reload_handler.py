# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for VKG reload Lambda handler."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda" / "vkg-reload"))

ENV = {
    "CLUSTER_ARN": "arn:aws:ecs:us-west-2:111:cluster/vkg",
    "RESOURCE_PREFIX": "coa-dev",
    "CLOUD_MAP_NAMESPACE_ID": "ns-abc123",
    "VKG_TASK_ROLE_ARN": "arn:aws:iam::111:role/task",
    "VKG_EXECUTION_ROLE_ARN": "arn:aws:iam::111:role/exec",
    "ONTOLOGY_BUCKET": "ontology-bucket",
    "PRIVATE_SUBNET_IDS": "subnet-a,subnet-b",
    "ECS_SECURITY_GROUP_ID": "sg-123",
    "AWS_REGION": "us-west-2",
    "VKG_IMAGE_PARAM_NAME": "/coa/vkg/container-image",
}


def _make_event(namespace="test-ns", version="v1"):
    return {"detail": {"namespace": namespace, "version": version}}


class TestHandler:
    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_reload_with_new_image_registers_task_def(self, mock_ssm, mock_sd, mock_ecs):
        """When SSM image differs from current, register new task def before deploying."""
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "111.dkr.ecr.us-west-2.amazonaws.com/scl:vkg-NEW"}
        }
        mock_ecs.describe_services.return_value = {"services": [{"taskDefinition": "arn:td:old"}]}
        mock_ecs.describe_task_definition.return_value = {
            "taskDefinition": {"containerDefinitions": [{"image": "111.dkr.ecr.us-west-2.amazonaws.com/scl:vkg-OLD"}]}
        }
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:ns-rev2"}}
        mock_ecs.update_service.return_value = {"service": {"deployments": [{"id": "deploy-1"}]}}

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "reload_triggered"
        mock_ecs.register_task_definition.assert_called_once()
        mock_ecs.update_service.assert_called_once_with(
            cluster=ENV["CLUSTER_ARN"],
            service="coa-dev-vkg-test-ns",
            taskDefinition="arn:td:ns-rev2",
            forceNewDeployment=True,
            deploymentConfiguration=index._DEPLOY_CONFIG,
        )

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_reload_same_image_skips_task_def_registration(self, mock_ssm, mock_sd, mock_ecs):
        """When SSM image matches current, just forceNewDeployment without new task def."""
        same_image = "111.dkr.ecr.us-west-2.amazonaws.com/scl:vkg-same"
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": same_image}}
        mock_ecs.describe_services.return_value = {"services": [{"taskDefinition": "arn:td:current"}]}
        mock_ecs.describe_task_definition.return_value = {
            "taskDefinition": {"containerDefinitions": [{"image": same_image}]}
        }
        mock_ecs.update_service.return_value = {"service": {"deployments": [{"id": "deploy-1"}]}}

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "reload_triggered"
        mock_ecs.register_task_definition.assert_not_called()
        mock_ecs.update_service.assert_called_once_with(
            cluster=ENV["CLUSTER_ARN"],
            service="coa-dev-vkg-test-ns",
            forceNewDeployment=True,
            deploymentConfiguration=index._DEPLOY_CONFIG,
        )

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_reload_uses_latest_image_from_ssm(self, mock_ssm, mock_sd, mock_ecs):
        """The reload path must read image from SSM, not from a running service."""
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "111.dkr.ecr.us-west-2.amazonaws.com/scl:vkg-new123"}
        }
        mock_ecs.describe_services.return_value = {"services": [{"taskDefinition": "arn:td:old"}]}
        mock_ecs.describe_task_definition.return_value = {
            "taskDefinition": {"containerDefinitions": [{"image": "111.dkr.ecr.us-west-2.amazonaws.com/scl:vkg-old"}]}
        }
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:rev3"}}
        mock_ecs.update_service.return_value = {"service": {"deployments": [{"id": "deploy-2"}]}}

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        index.handler(_make_event(), None)

        mock_ssm.get_parameter.assert_called_with(Name="/coa/vkg/container-image")
        td_call = mock_ecs.register_task_definition.call_args
        container_defs = td_call[1]["containerDefinitions"]
        assert container_defs[0]["image"] == "111.dkr.ecr.us-west-2.amazonaws.com/scl:vkg-new123"

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_provision_when_service_not_found(self, mock_ssm, mock_sd, mock_ecs):
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ecs.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "111.dkr.ecr.us-west-2.amazonaws.com/scl:vkg-abc"}
        }
        mock_ecs.describe_services.return_value = {"services": []}
        mock_ecs.update_service.side_effect = mock_ecs.exceptions.ServiceNotFoundException("not found")
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:new"}}
        mock_sd.create_service.return_value = {"Service": {"Arn": "arn:sd:svc"}}
        mock_sd.exceptions.ServiceAlreadyExists = type("ServiceAlreadyExists", (Exception,), {})

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "provisioned"
        mock_ecs.create_service.assert_called_once()
        assert mock_ecs.create_service.call_args[1]["serviceName"] == "coa-dev-vkg-test-ns"

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_invalid_namespace_rejected(self, mock_ssm, mock_sd, mock_ecs):
        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(namespace="../evil"), None)
        assert result["status"] == "skipped"
        assert "invalid" in result["reason"]
        mock_ecs.update_service.assert_not_called()

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_missing_namespace_rejected(self, mock_ssm, mock_sd, mock_ecs):
        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler({"detail": {"version": "v1"}}, None)
        assert result["status"] == "skipped"

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_race_condition_handles_not_idempotent(self, mock_ssm, mock_sd, mock_ecs):
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ecs.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:latest"}}
        mock_ecs.describe_services.return_value = {"services": []}
        mock_ecs.update_service.side_effect = [
            mock_ecs.exceptions.ServiceNotFoundException("not found"),
            {"service": {"deployments": [{"id": "deploy-2"}]}},
        ]
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:new"}}
        mock_ecs.create_service.side_effect = mock_ecs.exceptions.InvalidParameterException(
            "Creation of service was not idempotent."
        )
        mock_sd.create_service.return_value = {"Service": {"Arn": "arn:sd:svc"}}
        mock_sd.exceptions.ServiceAlreadyExists = type("ServiceAlreadyExists", (Exception,), {})

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "reload_triggered"

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_service_not_active_triggers_provision(self, mock_ssm, mock_sd, mock_ecs):
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ecs.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:latest"}}
        mock_ecs.describe_services.return_value = {"services": []}
        mock_ecs.update_service.side_effect = mock_ecs.exceptions.ServiceNotActiveException("not active")
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:new"}}
        mock_sd.create_service.return_value = {"Service": {"Arn": "arn:sd:svc"}}
        mock_sd.exceptions.ServiceAlreadyExists = type("ServiceAlreadyExists", (Exception,), {})

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "provisioned"

    @patch.dict(os.environ, {**ENV, "CLOUD_MAP_NAMESPACE_ID": "", "PRIVATE_SUBNET_IDS": ""})
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_provision_skipped_when_env_vars_missing(self, mock_ssm, mock_sd, mock_ecs):
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:latest"}}
        mock_ecs.describe_services.return_value = {"services": []}
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:new"}}
        mock_ecs.update_service.side_effect = mock_ecs.exceptions.ServiceNotFoundException("not found")

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "skipped"
        assert "env vars" in result["reason"]

    @patch.dict(os.environ, {**ENV, "VKG_IMAGE_PARAM_NAME": ""})
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_reload_fails_when_ssm_param_not_configured(self, mock_ssm, mock_sd, mock_ecs):
        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "failed"
        assert "container image" in result["reason"]

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    @patch("index.autoscaling")
    def test_provision_configures_auto_scaling(self, mock_autoscaling, mock_ssm, mock_sd, mock_ecs):
        """New namespace provision must configure auto-scaling (min=1, max=3, CPU 70%)."""
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ecs.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:latest"}}
        mock_ecs.describe_services.return_value = {"services": []}
        mock_ecs.update_service.side_effect = mock_ecs.exceptions.ServiceNotFoundException("not found")
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:new"}}
        mock_sd.create_service.return_value = {"Service": {"Arn": "arn:sd:svc"}}
        mock_sd.exceptions.ServiceAlreadyExists = type("ServiceAlreadyExists", (Exception,), {})

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm
        index.autoscaling = mock_autoscaling

        result = index.handler(_make_event(), None)
        assert result["status"] == "provisioned"
        mock_autoscaling.register_scalable_target.assert_called_once()
        target_call = mock_autoscaling.register_scalable_target.call_args[1]
        assert target_call["MinCapacity"] == 1
        assert target_call["MaxCapacity"] == 3
        mock_autoscaling.put_scaling_policy.assert_called_once()
        policy_call = mock_autoscaling.put_scaling_policy.call_args[1]
        assert policy_call["TargetTrackingScalingPolicyConfiguration"]["TargetValue"] == 70.0

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    @patch("index.autoscaling")
    def test_provision_succeeds_even_if_autoscaling_fails(self, mock_autoscaling, mock_ssm, mock_sd, mock_ecs):
        """Auto-scaling failure must not prevent service provisioning."""
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ecs.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:latest"}}
        mock_ecs.describe_services.return_value = {"services": []}
        mock_ecs.update_service.side_effect = mock_ecs.exceptions.ServiceNotFoundException("not found")
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:new"}}
        mock_sd.create_service.return_value = {"Service": {"Arn": "arn:sd:svc"}}
        mock_sd.exceptions.ServiceAlreadyExists = type("ServiceAlreadyExists", (Exception,), {})
        mock_autoscaling.register_scalable_target.side_effect = Exception("autoscaling API error")

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm
        index.autoscaling = mock_autoscaling

        result = index.handler(_make_event(), None)
        assert result["status"] == "provisioned"

    # ── circuit breaker + reload-outcome metrics ────────────────

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_reload_enables_deployment_circuit_breaker(self, mock_ssm, mock_sd, mock_ecs):
        """A reload deploys with the ECS circuit breaker + rollback so a load that
        never goes healthy rolls back instead of leaving the namespace broken."""
        same_image = "img:same"
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": same_image}}
        mock_ecs.describe_services.return_value = {"services": [{"taskDefinition": "arn:td:current"}]}
        mock_ecs.describe_task_definition.return_value = {
            "taskDefinition": {"containerDefinitions": [{"image": same_image}]}
        }
        mock_ecs.update_service.return_value = {"service": {"deployments": [{"id": "d1"}]}}

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        index.handler(_make_event(), None)

        cfg = mock_ecs.update_service.call_args.kwargs["deploymentConfiguration"]
        assert cfg["deploymentCircuitBreaker"] == {"enable": True, "rollback": True}

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_successful_reload_emits_reload_triggered_metric(self, mock_ssm, mock_sd, mock_ecs):
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:same"}}
        mock_ecs.describe_services.return_value = {"services": [{"taskDefinition": "arn:td:current"}]}
        mock_ecs.describe_task_definition.return_value = {
            "taskDefinition": {"containerDefinitions": [{"image": "img:same"}]}
        }
        mock_ecs.update_service.return_value = {"service": {"deployments": [{"id": "d1"}]}}

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        index.handler(_make_event(), None)

        metrics = [c.kwargs["MetricData"][0]["MetricName"] for c in index.cloudwatch.put_metric_data.call_args_list]
        assert "ReloadTriggered" in metrics

    @patch.dict(os.environ, {**ENV, "VKG_IMAGE_PARAM_NAME": ""})
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_unresolvable_image_emits_reload_failed_metric(self, mock_ssm, mock_sd, mock_ecs):
        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "failed"
        metrics = [c.kwargs["MetricData"][0]["MetricName"] for c in index.cloudwatch.put_metric_data.call_args_list]
        assert "ReloadFailed" in metrics

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_reload_exception_emits_reload_failed_and_reraises(self, mock_ssm, mock_sd, mock_ecs):
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:same"}}
        mock_ecs.describe_services.return_value = {"services": [{"taskDefinition": "arn:td:current"}]}
        mock_ecs.describe_task_definition.return_value = {
            "taskDefinition": {"containerDefinitions": [{"image": "img:same"}]}
        }
        mock_ecs.update_service.side_effect = RuntimeError("ecs boom")

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        import pytest

        with pytest.raises(RuntimeError, match="ecs boom"):
            index.handler(_make_event(), None)

        metrics = [c.kwargs["MetricData"][0]["MetricName"] for c in index.cloudwatch.put_metric_data.call_args_list]
        assert "ReloadFailed" in metrics

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_provision_success_emits_reload_triggered_metric(self, mock_ssm, mock_sd, mock_ecs):
        """A first-time provision (create_service) must emit ReloadTriggered, like the update path."""
        mock_ecs.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
        mock_ecs.exceptions.ServiceNotActiveException = type("ServiceNotActiveException", (Exception,), {})
        mock_ecs.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "img:latest"}}
        mock_ecs.describe_services.return_value = {"services": []}
        mock_ecs.update_service.side_effect = mock_ecs.exceptions.ServiceNotFoundException("not found")
        mock_ecs.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "arn:td:new"}}
        mock_sd.create_service.return_value = {"Service": {"Arn": "arn:sd:svc"}}
        mock_sd.exceptions.ServiceAlreadyExists = type("ServiceAlreadyExists", (Exception,), {})

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index.handler(_make_event(), None)
        assert result["status"] == "provisioned"
        metrics = [c.kwargs["MetricData"][0]["MetricName"] for c in index.cloudwatch.put_metric_data.call_args_list]
        assert "ReloadTriggered" in metrics

    @patch.dict(os.environ, ENV)
    @patch("index.ecs")
    @patch("index.sd")
    @patch("index.ssm")
    def test_provision_unresolvable_image_emits_reload_failed_metric(self, mock_ssm, mock_sd, mock_ecs):
        """The provision path's unresolvable-image failure must emit ReloadFailed, like its reload-path twin."""
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": ""}}

        import importlib

        import index

        importlib.reload(index)
        index.ecs = mock_ecs
        index.sd = mock_sd
        index.ssm = mock_ssm

        result = index._provision_and_deploy("test-ns", "coa-dev-vkg-test-ns", ENV["CLUSTER_ARN"], "coa-dev", "v1")
        assert result["status"] == "failed"
        assert "cannot resolve container image" in result["reason"]
        metrics = [c.kwargs["MetricData"][0]["MetricName"] for c in index.cloudwatch.put_metric_data.call_args_list]
        assert "ReloadFailed" in metrics

    def test_emit_metric_publishes_dimensioned_and_undimensioned_series(self):
        """Each metric is published twice in one call: once dimensioned by
        Namespace (drill-down) and once undimensioned (the cluster-wide roll-up
        the ReloadFailedAlarm evaluates — a metric alarm can't use SEARCH())."""
        import importlib

        import index

        importlib.reload(index)
        index.cloudwatch = MagicMock()

        index._emit_metric("ReloadFailed", "some-ns")

        index.cloudwatch.put_metric_data.assert_called_once()
        call = index.cloudwatch.put_metric_data.call_args
        assert call.kwargs["Namespace"] == "COA/VKG"
        entries = call.kwargs["MetricData"]
        assert len(entries) == 2
        assert all(e["MetricName"] == "ReloadFailed" for e in entries)
        dimensioned = [e for e in entries if e.get("Dimensions")]
        undimensioned = [e for e in entries if not e.get("Dimensions")]
        assert len(dimensioned) == 1
        assert dimensioned[0]["Dimensions"] == [{"Name": "Namespace", "Value": "some-ns"}]
        # The alarm reads this undimensioned roll-up; it must exist.
        assert len(undimensioned) == 1
