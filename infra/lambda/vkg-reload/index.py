# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""VKG Reload Lambda — provisions or redeploys per-namespace VKG service on ontology publish.

On every reload, registers a new task definition revision with the latest container
image (from SSM, written by CDK deploy) before forcing a new deployment. This ensures
ontology reloads always pick up the latest VKG image, not a stale one from provision time.
"""

import json
import os
import re

import boto3

ecs = boto3.client("ecs")
sd = boto3.client("servicediscovery")
ssm = boto3.client("ssm")
autoscaling = boto3.client("application-autoscaling")
cloudwatch = boto3.client("cloudwatch")

_NS_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")

# Reload-outcome metrics; the vkg stack alarms on ReloadFailed.
_METRIC_NAMESPACE = "COA/VKG"

# Circuit breaker + rollback: paired with the container's functional /health
# probe, a broken reload never goes healthy and rolls back to the last-good task.
_DEPLOY_CONFIG = {
    "minimumHealthyPercent": 100,
    "maximumPercent": 200,
    "deploymentCircuitBreaker": {"enable": True, "rollback": True},
}


def _emit_metric(name, namespace):
    """Emit a reload-outcome metric. Never raises.

    Each metric is published twice: once dimensioned by Namespace (for
    per-namespace dashboards / drill-down) and once with no dimensions (a
    cluster-wide roll-up). The undimensioned series is what the vkg stack's
    ReloadFailedAlarm evaluates: CloudWatch metric alarms cannot be backed by a
    SEARCH() expression, so the alarm needs a single concrete series that
    actually receives data across all namespaces.
    """
    try:
        cloudwatch.put_metric_data(
            Namespace=_METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": name,
                    "Value": 1,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Namespace", "Value": namespace}],
                },
                {
                    "MetricName": name,
                    "Value": 1,
                    "Unit": "Count",
                },
            ],
        )
    except Exception as e:  # pragma: no cover - defensive
        print(json.dumps({"action": "metric_emit_failed", "metric": name, "error": str(e)}))


def handler(event, context):
    """Provision or redeploy the per-namespace VKG service on ontology publish.

    Triggered by an ontology-publish event carrying ``detail.namespace`` and
    ``detail.version``. Resolves the latest VKG container image from SSM and,
    if the running service already uses it, forces a new deployment; otherwise
    registers a fresh task-definition revision with the new image first. If the
    service does not yet exist, provisions it. Reload outcomes are published as
    ``ReloadTriggered``/``ReloadFailed`` CloudWatch metrics.

    Args:
        event: EventBridge event; ``detail.namespace`` and ``detail.version``
            identify the ontology being reloaded.
        context: Lambda runtime context (unused).

    Returns:
        A status dict describing the outcome (``reload_triggered``, ``skipped``,
        or ``failed``) with the namespace and, on success, the deployment id.

    Raises:
        Exception: Re-raised after emitting ``ReloadFailed`` when an unexpected
            error occurs during reload of an existing service.
    """
    ns = event.get("detail", {}).get("namespace", "unknown")
    version = event.get("detail", {}).get("version", "unknown")
    cluster = os.environ["CLUSTER_ARN"]
    prefix = os.environ["RESOURCE_PREFIX"]

    if ns == "unknown" or not _NS_PATTERN.match(ns):
        print(json.dumps({"action": "reload_skipped", "reason": "missing or invalid namespace"}))
        return {"status": "skipped", "reason": "missing or invalid namespace"}

    service_name = f"{prefix}-vkg-{ns}"
    log = {"action": "reload_start", "namespace": ns, "version": version, "cluster": cluster, "service": service_name}
    print(json.dumps(log))

    try:
        container_image = _resolve_container_image()
        if not container_image:
            print(json.dumps({"action": "reload_failed", "namespace": ns, "reason": "cannot resolve container image"}))
            _emit_metric("ReloadFailed", ns)
            return {"status": "failed", "reason": "cannot resolve container image"}

        current_image = _get_current_service_image(cluster, service_name)

        if current_image == container_image:
            print(json.dumps({"action": "image_unchanged", "namespace": ns, "image": container_image}))
            resp = ecs.update_service(
                cluster=cluster,
                service=service_name,
                forceNewDeployment=True,
                deploymentConfiguration=_DEPLOY_CONFIG,
            )
        else:
            print(
                json.dumps(
                    {
                        "action": "image_updated",
                        "namespace": ns,
                        "old_image": current_image or "(unknown)",
                        "new_image": container_image,
                    }
                )
            )
            task_def_arn = _register_task_definition(ns, prefix, container_image)
            resp = ecs.update_service(
                cluster=cluster,
                service=service_name,
                taskDefinition=task_def_arn,
                forceNewDeployment=True,
                deploymentConfiguration=_DEPLOY_CONFIG,
            )

        deployment_id = resp["service"].get("deployments", [{}])[0].get("id", "unknown")
        print(
            json.dumps(
                {
                    "action": "reload_triggered",
                    "namespace": ns,
                    "version": version,
                    "service": service_name,
                    "deployment_id": deployment_id,
                    "image": container_image,
                    "image_changed": current_image != container_image,
                }
            )
        )
        _emit_metric("ReloadTriggered", ns)
        return {"status": "reload_triggered", "namespace": ns, "deployment_id": deployment_id}
    except (ecs.exceptions.ServiceNotFoundException, ecs.exceptions.ServiceNotActiveException):
        print(json.dumps({"action": "provision_start", "namespace": ns, "service": service_name}))
        return _provision_and_deploy(ns, service_name, cluster, prefix, version, container_image)
    except Exception as e:
        print(
            json.dumps(
                {
                    "action": "reload_failed",
                    "namespace": ns,
                    "service": service_name,
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
            )
        )
        _emit_metric("ReloadFailed", ns)
        raise


def _get_current_service_image(cluster, service_name):
    """Get the container image currently used by the service's task definition."""
    try:
        svc_resp = ecs.describe_services(cluster=cluster, services=[service_name])
        services = svc_resp.get("services", [])
        if not services:
            return ""
        task_def_arn = services[0]["taskDefinition"]
        td_resp = ecs.describe_task_definition(taskDefinition=task_def_arn)
        containers = td_resp["taskDefinition"].get("containerDefinitions", [])
        return containers[0].get("image", "") if containers else ""
    except (ecs.exceptions.ServiceNotFoundException, ecs.exceptions.ServiceNotActiveException):
        return ""
    except Exception as e:
        print(json.dumps({"action": "get_image_failed", "service": service_name, "error_type": type(e).__name__}))
        return ""


def _resolve_container_image():
    """Read latest VKG image URI from SSM (written by CDK on every deploy)."""
    param_name = os.environ.get("VKG_IMAGE_PARAM_NAME", "")
    if not param_name:
        print(json.dumps({"action": "image_resolve_failed", "reason": "VKG_IMAGE_PARAM_NAME not set"}))
        return ""
    try:
        resp = ssm.get_parameter(Name=param_name)
        image = resp["Parameter"]["Value"]
        print(json.dumps({"action": "image_resolved", "image": image, "source": "ssm"}))
        return image
    except Exception as e:
        print(json.dumps({"action": "image_resolve_failed", "reason": str(e)}))
        return ""


def _register_task_definition(ns, prefix, container_image):
    """Register a new task def revision with the latest image for this namespace."""
    task_role_arn = os.environ.get("VKG_TASK_ROLE_ARN", "")
    execution_role_arn = os.environ.get("VKG_EXECUTION_ROLE_ARN", "")
    ontology_bucket = os.environ.get("ONTOLOGY_BUCKET", "")
    region = os.environ.get("AWS_REGION", "us-west-2")

    family = f"{prefix}-vkg-{ns}" if prefix else f"vkg-{ns}"
    td_resp = ecs.register_task_definition(
        family=family,
        taskRoleArn=task_role_arn,
        executionRoleArn=execution_role_arn,
        networkMode="awsvpc",
        requiresCompatibilities=["FARGATE"],
        cpu="512",
        memory="1024",
        runtimePlatform={"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
        containerDefinitions=[
            {
                "name": "ontop",
                "image": container_image,
                "essential": True,
                "environment": [
                    {"name": "ONTOLOGY_BUCKET", "value": ontology_bucket},
                    {"name": "ONTOLOGY_PREFIX", "value": "ontologies/"},
                    {"name": "NAMESPACE", "value": ns},
                    {"name": "NAMESPACE_ID", "value": ns},
                    {"name": "ENDPOINT_PORT", "value": "8080"},
                    {"name": "JAVA_OPTS", "value": "-Xmx768m -Xms256m"},
                ],
                "portMappings": [{"containerPort": 8080, "protocol": "tcp"}],
                "healthCheck": {
                    "command": ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"],
                    "interval": 30,
                    "timeout": 10,
                    "retries": 5,
                    "startPeriod": 180,
                },
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": f"/ecs/vkg-{ns}",
                        "awslogs-region": region,
                        "awslogs-stream-prefix": "vkg",
                        "awslogs-create-group": "true",
                    },
                },
            }
        ],
    )
    task_def_arn = td_resp["taskDefinition"]["taskDefinitionArn"]
    print(json.dumps({"action": "task_def_registered", "namespace": ns, "task_def_arn": task_def_arn}))
    return task_def_arn


def _provision_and_deploy(ns, service_name, cluster, prefix, version, container_image=None):
    """Create Cloud Map entry and launch ECS service for a new namespace."""
    cloud_map_ns_id = os.environ.get("CLOUD_MAP_NAMESPACE_ID", "")
    ontology_bucket = os.environ.get("ONTOLOGY_BUCKET", "")
    subnet_ids = [s for s in os.environ.get("PRIVATE_SUBNET_IDS", "").split(",") if s]
    sg_id = os.environ.get("ECS_SECURITY_GROUP_ID", "")

    if not all([cloud_map_ns_id, ontology_bucket, subnet_ids]):
        print(json.dumps({"action": "provision_skipped", "namespace": ns, "reason": "missing env vars"}))
        return {"status": "skipped", "reason": "provision env vars not configured"}

    if not container_image:
        container_image = _resolve_container_image()
    if not container_image:
        print(json.dumps({"action": "provision_failed", "namespace": ns, "reason": "cannot resolve container image"}))
        _emit_metric("ReloadFailed", ns)
        return {"status": "failed", "reason": "cannot resolve container image"}

    registry_arn = _ensure_cloud_map(ns, cloud_map_ns_id)
    task_def_arn = _register_task_definition(ns, prefix, container_image)

    try:
        ecs.create_service(
            cluster=cluster,
            serviceName=service_name,
            taskDefinition=task_def_arn,
            desiredCount=1,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnet_ids,
                    "securityGroups": [sg_id] if sg_id else [],
                    "assignPublicIp": "DISABLED",
                }
            },
            serviceRegistries=[{"registryArn": registry_arn}],
            deploymentConfiguration={
                "minimumHealthyPercent": 100,
                "maximumPercent": 200,
                "deploymentCircuitBreaker": {"enable": True, "rollback": True},
            },
        )
        print(json.dumps({"action": "service_created", "namespace": ns, "service": service_name}))
        _configure_auto_scaling(cluster, service_name)
        _emit_metric("ReloadTriggered", ns)
        return {"status": "provisioned", "namespace": ns, "service": service_name}
    except ecs.exceptions.InvalidParameterException as e:
        if "already exists" in str(e).lower() or "not idempotent" in str(e).lower():
            ecs.update_service(
                cluster=cluster,
                service=service_name,
                taskDefinition=task_def_arn,
                forceNewDeployment=True,
                deploymentConfiguration=_DEPLOY_CONFIG,
            )
            _configure_auto_scaling(cluster, service_name)
            print(json.dumps({"action": "reload_triggered", "namespace": ns, "service": service_name}))
            _emit_metric("ReloadTriggered", ns)
            return {"status": "reload_triggered", "namespace": ns}
        raise


def _configure_auto_scaling(cluster, service_name):
    """Register auto-scaling for a per-namespace VKG service (min=1, max=3, CPU 70%)."""
    cluster_name = cluster.split("/")[-1]
    resource_id = f"service/{cluster_name}/{service_name}"
    try:
        autoscaling.register_scalable_target(
            ServiceNamespace="ecs",
            ResourceId=resource_id,
            ScalableDimension="ecs:service:DesiredCount",
            MinCapacity=1,
            MaxCapacity=3,
        )
        autoscaling.put_scaling_policy(
            PolicyName=f"{service_name}-cpu-scaling",
            ServiceNamespace="ecs",
            ResourceId=resource_id,
            ScalableDimension="ecs:service:DesiredCount",
            PolicyType="TargetTrackingScaling",
            TargetTrackingScalingPolicyConfiguration={
                "TargetValue": 70.0,
                "PredefinedMetricSpecification": {"PredefinedMetricType": "ECSServiceAverageCPUUtilization"},
                "ScaleInCooldown": 300,
                "ScaleOutCooldown": 60,
            },
        )
        print(json.dumps({"action": "autoscaling_configured", "service": service_name}))
    except Exception as e:
        print(json.dumps({"action": "autoscaling_failed", "service": service_name, "error": str(e)}))


def _ensure_cloud_map(ns, cloud_map_ns_id):
    """Create or look up Cloud Map service entry. Returns registry ARN."""
    try:
        resp = sd.create_service(
            Name=f"vkg-{ns}",
            NamespaceId=cloud_map_ns_id,
            DnsConfig={"DnsRecords": [{"Type": "A", "TTL": 10}], "RoutingPolicy": "MULTIVALUE"},
            HealthCheckCustomConfig={"FailureThreshold": 1},
        )
        return resp["Service"]["Arn"]
    except sd.exceptions.ServiceAlreadyExists:
        pass
    paginator = sd.get_paginator("list_services")
    for page in paginator.paginate(Filters=[{"Name": "NAMESPACE_ID", "Values": [cloud_map_ns_id], "Condition": "EQ"}]):
        for svc in page.get("Services", []):
            if svc["Name"] == f"vkg-{ns}":
                return svc["Arn"]
    raise RuntimeError(f"Cloud Map service vkg-{ns} not found after create reported it exists")
