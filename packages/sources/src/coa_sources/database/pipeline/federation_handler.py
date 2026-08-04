# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Federation provisioner Lambda — runs AFTER discovery in the pipeline.

Separated from the discovery handler so the Lake Formation data-lake-admin
privilege required to create federated catalogs and grant LF data permissions is
isolated to this single-purpose function's role (not the broad discovery connector).

Discovery runs first; this step then:
- **JDBC sources**: provisions the managed Glue federated catalog and grants the
  consumer query principal LF SELECT/DESCRIBE on it. ``queryable`` is set to the
  grant result.
- **GLUE_DATABASE sources**: skips catalog provisioning (they query natively via
  AwsDataCatalog) but still grants the consumer LF SELECT/DESCRIBE on the native
  Glue database. This is a no-op in IAM-mode accounts and idempotent on re-scans.
  Accounts with strict Lake Formation mode (IAM_ALLOWED_PRINCIPALS removed) require
  this grant for Athena to access LF-governed Glue tables.

Fails loudly: a provisioning or persistence error raises, so the Lambda fails and
the scan-pipeline Catch marks the scan FAILED and the source SCAN_FAILED. Sources
with incomplete config are skipped, not failed.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from coa_common import async_boto_config
from coa_common.dao import DynamoDBDAO
from coa_control_plane_server.models.source_sub_type import SourceSubType

from coa_sources.database.connectors.glue_connection_provisioner import (
    cleanup_federated_resources,
    grant_consumer_select,
    grant_consumer_select_native,
    provision_federated_catalog,
)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

SOURCES_TABLE = os.environ["SOURCES_TABLE"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
# SSM parameter holding the consumer query principal (AgentCore runtime role) ARN.
# Optional: when unset/absent the consumer grant is skipped (e.g. envs without serve).
CONSUMER_QUERY_ROLE_SSM_PARAM = os.environ.get("CONSUMER_QUERY_ROLE_SSM_PARAM", "")
# Role the AWS-managed federated connector uses to read the credential secret.
# We assume it to pre-check secret readability before provisioning.
FEDERATED_CATALOG_ROLE_ARN = os.environ.get("FEDERATED_CATALOG_ROLE_ARN", "")

_dao: DynamoDBDAO | None = None
_ssm = None


def _get_dao() -> DynamoDBDAO:
    global _dao
    if _dao is None:
        _dao = DynamoDBDAO(SOURCES_TABLE, region=AWS_REGION)
    return _dao


def _secret_readable_by_connector(secret_arn: str) -> bool:
    """Verify the managed connector can read the credential secret.

    The federated connector reads the secret AS ``FEDERATED_CATALOG_ROLE_ARN``,
    so we assume that role and attempt ``GetSecretValue``. Returns ``False`` when
    it can't be read — e.g. a cross-account secret whose resource/KMS policy
    doesn't yet grant the connector role — so the caller skips provisioning a
    connection that would otherwise fail silently at query time. Returns ``True``
    when no dedicated role is configured (nothing to validate against).
    """
    if not FEDERATED_CATALOG_ROLE_ARN or not secret_arn:
        return True
    # SecretId must be queried in the secret's own region (it may be cross-region).
    # ARN format: arn:partition:service:region:account:resource (>= 6 parts).
    parts = secret_arn.split(":")
    if len(parts) < 6:
        logger.warning("malformed_secret_arn", extra={"secret_arn": secret_arn})
        return False
    secret_region = parts[3] or AWS_REGION
    try:
        creds = boto3.client("sts", region_name=AWS_REGION).assume_role(
            RoleArn=FEDERATED_CATALOG_ROLE_ARN, RoleSessionName="coa-secret-precheck"
        )["Credentials"]
        boto3.client(
            "secretsmanager",
            region_name=secret_region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        ).get_secret_value(SecretId=secret_arn)
        return True
    except (ClientError, BotoCoreError):
        # Only AWS-side failures mean "not readable"; programming errors surface.
        logger.warning("federation_secret_precheck_failed", extra={"secret_arn": secret_arn}, exc_info=True)
        return False


def _consumer_role_arn() -> str:
    """Resolve the consumer query role ARN from SSM at runtime (empty if unavailable)."""
    if not CONSUMER_QUERY_ROLE_SSM_PARAM:
        return ""
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm", region_name=AWS_REGION)
    try:
        return _ssm.get_parameter(Name=CONSUMER_QUERY_ROLE_SSM_PARAM)["Parameter"]["Value"]
    except Exception:
        logger.warning("consumer_role_ssm_lookup_failed", extra={"param": CONSUMER_QUERY_ROLE_SSM_PARAM})
        return ""


def _grant_secret_read_to_consumer(secret_arn: str) -> None:
    """Attach a resource policy on the credential secret granting the consumer role GetSecretValue.

    Idempotent: merges the consumer principal into the existing policy if one exists.
    Best-effort: failures are logged but don't block provisioning (the source remains
    queryable via Athena federation; only the direct JDBC fast-path is affected).
    """
    consumer_arn = _consumer_role_arn()
    if not consumer_arn or not secret_arn:
        return

    parts = secret_arn.split(":")
    if len(parts) < 6 or not parts[3]:
        logger.warning("malformed_secret_arn_skipping_grant", extra={"secret_arn": secret_arn})
        return
    secret_region = parts[3]
    sm = boto3.client("secretsmanager", region_name=secret_region, config=async_boto_config())

    try:
        # Fetch existing policy (if any)
        try:
            existing = sm.get_resource_policy(SecretId=secret_arn)
            policy = json.loads(existing.get("ResourcePolicy") or "{}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                policy = {}
            else:
                logger.debug(
                    "get_resource_policy_error", extra={"secret_arn": secret_arn, "code": e.response["Error"]["Code"]}
                )
                policy = {}
        except (json.JSONDecodeError, TypeError):
            policy = {}

        # Build/merge the statement
        sid = "SCLRuntimeSecretRead"
        statements = policy.get("Statement", [])
        if not isinstance(statements, list):
            logger.warning("invalid_policy_statement_type", extra={"secret_arn": secret_arn})
            statements = []
        # Remove any existing SCL statement to avoid duplicates
        statements = [s for s in statements if s.get("Sid") != sid]
        statements.append(
            {
                "Sid": sid,
                "Effect": "Allow",
                "Principal": {"AWS": consumer_arn},
                "Action": "secretsmanager:GetSecretValue",
                "Resource": "*",
            }
        )
        policy = {
            "Version": "2012-10-17",
            "Statement": statements,
        }

        sm.put_resource_policy(SecretId=secret_arn, ResourcePolicy=json.dumps(policy))
        logger.info("secret_resource_policy_granted", extra={"secret_arn": secret_arn, "principal": consumer_arn})
    except (ClientError, BotoCoreError):
        logger.warning("secret_resource_policy_grant_failed", extra={"secret_arn": secret_arn}, exc_info=True)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Provision a managed Glue federated catalog for a JDBC source, then grant LF.

    Input (from Step Functions): {datasourceId, sourceId, namespaceId, ...}.
    Glue (S3/Iceberg) sources are skipped — they query natively via
    AwsDataCatalog and need no provisioning.
    """
    datasource_id = event["datasourceId"]
    source_id = event.get("sourceId") or datasource_id.removeprefix("DS#")
    namespace_id = event["namespaceId"]
    source_key = {"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"}

    item = _get_dao().get(source_key) or {}
    sub_type = item.get("sourceSubType")

    # GLUE_DATABASE sources need no catalog provisioning but still need an LF
    # SELECT grant so the serve runtime role can query LF-governed Glue tables in
    # accounts with strict Lake Formation mode (IAM_ALLOWED_PRINCIPALS removed).
    if sub_type == SourceSubType.GLUE_DATABASE:
        database_name = item.get("athenaDatabase") or ""
        if not database_name:
            logger.warning(
                "glue_native_lf_grant_skipped_no_database",
                extra={"datasource_id": datasource_id},
            )
            return {"provisioned": False, "reason": "no-athena-database"}
        granted = grant_consumer_select_native(
            database_name=database_name,
            principal_arn=_consumer_role_arn(),
        )
        try:
            _get_dao().update(
                key=source_key,
                update_fields={"queryable": granted},
                condition="attribute_exists(PK)",
            )
        except Exception:
            # The LF grant is idempotent — even if the DDB write races with a
            # concurrent delete, the permission persists and a re-scan will retry.
            logger.warning(
                "glue_native_queryable_update_failed",
                extra={"datasource_id": datasource_id},
                exc_info=True,
            )
        logger.info(
            "glue_native_lf_grant",
            extra={"datasource_id": datasource_id, "granted": granted},
        )
        return {"provisioned": False, "reason": "glue-native", "queryable": granted}

    if sub_type != SourceSubType.JDBC_DATABASE:
        logger.info("Skipping federation for non-JDBC source: %s (type=%s)", datasource_id, sub_type)
        return {"provisioned": False, "reason": "not-jdbc"}

    raw_config = item.get("configuration", "{}")
    config = json.loads(raw_config) if isinstance(raw_config, str) else raw_config
    host = config.get("host")
    port = config.get("port")
    engine = config.get("engine")
    credential_secret_arn = config.get("credentialSecretArn")
    database_name = config.get("databaseName")
    if not all([host, port, engine, credential_secret_arn, database_name]):
        logger.info("Skipping federation — incomplete JDBC config for %s", datasource_id)
        return {"provisioned": False, "reason": "incomplete-config"}

    # Fail fast: don't provision a connection the managed connector can't
    # authenticate (e.g. a cross-account secret not yet shared with the catalog
    # role). The source stays not-queryable; a re-scan retries once fixed.
    if not _secret_readable_by_connector(credential_secret_arn):
        logger.warning("Skipping federation — connector role cannot read secret for %s", datasource_id)
        return {"provisioned": False, "reason": "secret-unreadable"}

    result = provision_federated_catalog(
        datasource_id=datasource_id,
        engine=engine,
        host=host,
        port=int(port),
        database_name=database_name,
        credential_secret_arn=credential_secret_arn,
        public_schema_name=config.get("schemaName", "public"),
        subnet_id=os.environ.get("CONNECTOR_SUBNET_ID"),
        security_group_id=os.environ.get("CONNECTOR_SECURITY_GROUP_ID"),
    )
    catalog_name = result["athenaDataCatalogName"]

    # Schemas come from discovery (which ran first). Federated DB names are
    # lowercase — via CATALOG_CASING_FILTER=LOWERCASE_ONLY for most connectors,
    # or natively for Redshift (which folds identifiers to lowercase and rejects
    # that property) — so we lowercase the discovered schemas to match. We grant
    # by name — no need to list the catalog's databases (which the connector
    # materializes lazily, so GetDatabases can return empty right after create).
    schemas = sorted({s.lower() for s in (item.get("discoveredSchemas") or []) if s})

    # Grant LF SELECT/DESCRIBE on the federated catalog to the consumer query
    # principal, scoped to the catalog's actual (casing-correct) database names.
    # The consumer grant gates queryable. Best-effort/idempotent: a failure (or no
    # principal) leaves queryable False without failing the scan — a re-scan retries.
    granted = grant_consumer_select(catalog_name=catalog_name, schemas=schemas, principal_arn=_consumer_role_arn())

    # Grant the consumer query principal (AgentCore runtime role) read access to
    # the credential secret so the direct JDBC executor can authenticate at query time.
    # Uses a resource-based policy on the secret (least-privilege, no broad IAM grant).
    _grant_secret_read_to_consumer(credential_secret_arn)

    # Persist the references; roll back the cloud resources if the write fails
    # so we never leave orphaned Glue/LF resources unrecorded, then re-raise to
    # fail the scan.
    try:
        _get_dao().update(
            key=source_key,
            update_fields={
                "glueConnectionName": result["glueConnectionName"],
                "athenaDataCatalogName": catalog_name,
                # Queryable only once the consumer holds the LF grant.
                "queryable": granted,
            },
            condition="attribute_exists(PK)",
        )
    except Exception:
        logger.exception("Failed to persist federation refs for %s; rolling back", datasource_id)
        cleanup_federated_resources(
            glue_connection_name=result.get("glueConnectionName"),
            athena_catalog_name=catalog_name,
        )
        raise

    return {"provisioned": True, "queryable": granted, **result}
