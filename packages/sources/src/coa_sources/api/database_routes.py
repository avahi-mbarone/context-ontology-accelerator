# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Database-source route handlers.

Handles all DATABASE source operations:
  POST   /namespaces/{namespaceId}/sources                                   — create database source
  GET    /namespaces/{namespaceId}/sources/{sourceId}/tables                 — list tables (DataZone)
  GET    /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}       — get table (DataZone)
  PUT    /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/review            — review one table
  PATCH  /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/metadata          — edit table metadata
  PUT    /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/columns/{columnName}/review    — review column
  PATCH  /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/columns/{columnName}/metadata — edit column meta
  GET    /namespaces/{namespaceId}/sources/{sourceId}/scan/{jobId}           — get scan job
  PUT    /namespaces/{namespaceId}/sources/{sourceId}/metadata               — update source-level metadata

Bulk approve/reject (ApproveSource, RejectSource) live in approve_reject_routes.py
because they are async via SQS.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any
from urllib.parse import unquote

import structlog
from botocore.exceptions import ClientError
from coa_common.metadata_store import SMUSClient
from coa_common.response import api_response, iso_to_epoch
from coa_control_plane_server.models.glue_execution_engine import GlueExecutionEngine
from coa_control_plane_server.models.query_engine import QueryEngine
from coa_control_plane_server.models.source_status import SourceStatus
from coa_control_plane_server.models.source_sub_type import SourceSubType
from coa_control_plane_server.models.source_type import SourceType

from coa_sources.database.connectors.jdbc import DIRECT_QUERY_ENGINES
from coa_sources.database.metrics import emit_metric

from .namespace_counters import adjust_namespace_source_count
from .sources_handler import (
    _AWS_REGION,
    _PROJECT_ACCESS_ROLE_ARN,
    _REVIEW_QUEUE_URL,
    _SCAN_QUEUE_URL,
    _SMUS_DOMAIN_ID,
    _get_dao,
    _get_ns_dao,
    _get_scan_dao,
    _get_sqs,
    _now_iso,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# SMUS helpers
# ---------------------------------------------------------------------------


def _get_smus_client() -> SMUSClient:
    return SMUSClient(
        domain_id=_SMUS_DOMAIN_ID,
        region_name=_AWS_REGION,
        assume_role_arn=_PROJECT_ACCESS_ROLE_ARN or None,
        session_name="sources-api",
    )


def _resolve_project_id(namespace_id: str) -> str | None:
    try:
        item = _get_ns_dao().get({"PK": f"NS#{namespace_id}", "SK": "METADATA"})
    except ClientError:
        logger.exception("ddb_get_namespace_failed", namespace_id=namespace_id)
        return None
    if not item or "dataZoneProjectId" not in item:
        return None
    return item["dataZoneProjectId"]


# ---------------------------------------------------------------------------
# CREATE DATABASE SOURCE
# ---------------------------------------------------------------------------

# Athena's account-default Glue Data Catalog name.
_DEFAULT_ATHENA_CATALOG = "AwsDataCatalog"


def _resolve_glue_athena_catalog(glue_config: Any) -> str:
    """Resolve the Athena QueryExecutionContext.Catalog for a Glue source.

    - An explicit ``athenaDataCatalogName`` wins (caller knows their catalog).
    - A nested/cross-account ``catalogId`` of the form ``account:catalogName``
      maps to the nested catalog name.
    - A bare account-id ``catalogId`` (the account's root Data Catalog) maps to
      Athena's default ``AwsDataCatalog``.
    """
    if glue_config.athena_data_catalog_name:
        return glue_config.athena_data_catalog_name
    catalog_id = (glue_config.catalog_id or "").strip()
    if ":" in catalog_id:
        return catalog_id.split(":", 1)[1]
    return _DEFAULT_ATHENA_CATALOG


def _resolve_query_engine(glue_config: Any, jdbc_config: Any) -> QueryEngine:
    """Preferred single-source execution engine for the source.

    ``JDBC`` (direct, low-latency) only when a direct dialect is implemented for
    the engine (today PostgreSQL/Redshift). ``REDSHIFT`` when a Glue/Iceberg
    source opts in to Redshift Serverless (`awsdatacatalog` auto-mount) via
    ``GlueConfiguration.executionEngine`` — else Glue defaults to Athena. JDBC
    engines without a direct path also go through Athena — so serve never routes
    to a path that doesn't exist. Multi-source queries always use Athena.
    """
    if jdbc_config is not None:
        engine = getattr(jdbc_config.engine, "value", jdbc_config.engine) or ""
        if str(engine).upper() in DIRECT_QUERY_ENGINES:
            return QueryEngine.JDBC
        return QueryEngine.ATHENA
    if glue_config is not None:
        execution_engine = getattr(glue_config, "execution_engine", None)
        engine = getattr(execution_engine, "value", execution_engine) or ""
        if str(engine).upper() == GlueExecutionEngine.REDSHIFT.value:
            return QueryEngine.REDSHIFT
    return QueryEngine.ATHENA


def _create_database_source(db_req: Any, namespace_id: str) -> dict[str, Any]:
    """Create a DATABASE source. db_req is a CreateDatabaseSourceInput model instance."""
    name: str = db_req.name.strip()
    if not name:
        return api_response(400, {"error": "name is required"})

    glue_config = db_req.glue_configuration
    jdbc_config = db_req.jdbc_configuration
    if not glue_config and not jdbc_config:
        return api_response(400, {"error": "glueConfiguration or jdbcConfiguration is required"})

    # A Glue source opting into Redshift execution must name the workgroup that
    # runs its queries — the backend cannot infer which Serverless workgroup to
    # use. Athena (the default) needs no workgroup.
    if glue_config is not None:
        execution_engine = getattr(glue_config, "execution_engine", None)
        engine_value = getattr(execution_engine, "value", execution_engine) or ""
        if str(engine_value).upper() == GlueExecutionEngine.REDSHIFT.value and not getattr(
            glue_config, "redshift_workgroup", None
        ):
            return api_response(
                400,
                {"error": "redshiftWorkgroup is required when executionEngine is REDSHIFT"},
            )

    sub_type = SourceSubType.JDBC_DATABASE if jdbc_config else SourceSubType.GLUE_DATABASE
    source_id = str(uuid.uuid4())
    now = _now_iso()

    config_dict = jdbc_config.to_dict() if jdbc_config else glue_config.to_dict()

    item: dict[str, Any] = {
        "PK": f"NS#{namespace_id}",
        "SK": f"SRC#{source_id}",
        "sourceId": source_id,
        "namespaceId": namespace_id,
        "name": name,
        "sourceType": SourceType.DATABASE,
        "sourceSubType": sub_type,
        "status": SourceStatus.REGISTERED,
        "configuration": json.dumps(config_dict),
        # Query-layer metadata (read by serve to build the Athena request).
        # Catalog: native Glue resolves from catalogId (AwsDataCatalog for the
        # account-root catalog, else the nested catalog name); JDBC federated
        # catalogs are nested under AwsDataCatalog. region is where Athena/the
        # catalog live (Glue: source region; JDBC: deployment region).
        # queryable flips true once the source is actually queryable
        # (Glue: after first scan; JDBC: after federation provisioning).
        "athenaCatalog": (_resolve_glue_athena_catalog(glue_config) if glue_config else _DEFAULT_ATHENA_CATALOG),
        # Preferred single-source execution engine. Direct JDBC only when a
        # direct dialect exists for the engine (PostgreSQL/Redshift today),
        # otherwise Athena. Serve overrides to Athena for any multi-source
        # query (Athena federates as the staging engine).
        "queryEngine": _resolve_query_engine(glue_config, jdbc_config),
        "region": (glue_config.region if glue_config else _AWS_REGION),
        "queryable": False,
        "tablesDiscovered": 0,
        "tablesApproved": 0,
        "createdAt": now,
        "updatedAt": now,
        "sourceTypeCreatedAt": f"{SourceType.DATABASE.value}#{now}",
    }
    # For native Glue sources the Athena Database is the Glue database name.
    # JDBC federated sources resolve schema per-table, so no single database.
    if glue_config:
        item["athenaDatabase"] = glue_config.database_name
    # Persist the metadata enrichment toggle whenever the caller specifies it
    # (true or false). Records that omit the field — legacy records, or
    # programmatic callers that don't set it — fall back to "enabled" at read
    # time in the enrichment handler.
    if db_req.metadata_enrichment_enabled is not None:
        item["metadataEnrichmentEnabled"] = db_req.metadata_enrichment_enabled
    # Persist athenaDataCatalogName at top level for Glue sources (used by query layer)
    if glue_config and getattr(glue_config, "athena_data_catalog_name", None):
        item["athenaDataCatalogName"] = glue_config.athena_data_catalog_name
    # Persist redshiftWorkgroup at top level ONLY for Glue sources that actually
    # execute via Redshift (queryEngine=REDSHIFT). Read by serve's Redshift
    # executor the way athenaCatalog/athenaDatabase are read by the Athena
    # executor. A workgroup on an ATHENA source is meaningless, so it is
    # not persisted — keeps the record honest and avoids a dead column.
    if glue_config and item["queryEngine"] == QueryEngine.REDSHIFT and getattr(glue_config, "redshift_workgroup", None):
        item["redshiftWorkgroup"] = glue_config.redshift_workgroup

    try:
        _get_dao().put(item)
    except ClientError:
        logger.exception("ddb_put_failed", source_id=source_id)
        return api_response(500, {"error": "Internal server error"})

    # Increment the namespace sourceCount. Best-effort: counter drift
    # is undesirable but must never block source creation.
    adjust_namespace_source_count(namespace_id, SourceType.DATABASE, 1)

    # Write initial scan job record — SK is the ISO timestamp (used as scanJobSK in SFN)
    scan_job_sk = now
    try:
        _get_scan_dao().put(
            {
                "PK": f"SRC#{source_id}",
                "SK": scan_job_sk,
                "sourceId": source_id,
                "namespaceId": namespace_id,
                "status": "IN_PROGRESS",
                "scanType": "full",
                "startedAt": now,
                "createdAt": now,
            }
        )
    except ClientError:
        logger.exception("ddb_put_scan_job_failed", source_id=source_id)

    # Enqueue to database scan queue — include scanJobPK/scanJobSK so the state machine
    # can update the correct source-scan-jobs record (PK=SRC#{sourceId}, SK=scanJobSK).
    # scanJobId uses a fresh UUID (matching old logic) so each execution has a unique name.
    if _SCAN_QUEUE_URL:
        try:
            _get_sqs().send_message(
                QueueUrl=_SCAN_QUEUE_URL,
                MessageBody=json.dumps(
                    {
                        "datasourceId": f"DS#{source_id}",
                        "sourceId": source_id,
                        "scanJobId": f"SCAN#{str(uuid.uuid4())}",
                        "scanJobPK": f"SRC#{source_id}",
                        "scanJobSK": scan_job_sk,
                        "namespaceId": namespace_id,
                        "scanType": "full",
                    }
                ),
            )
        except ClientError:
            # The scan never started, so the source must not be left orphaned
            # (a REGISTERED source that never scans) or mislabeled SCAN_FAILED
            # (which implies a scan ran and failed). Roll back the partial create
            # so DDB state matches the 500 the client receives and a retry is clean.
            logger.exception("sqs_send_failed", source_id=source_id)
            with contextlib.suppress(ClientError):
                _get_scan_dao().delete({"PK": f"SRC#{source_id}", "SK": scan_job_sk})
            source_deleted = False
            try:
                _get_dao().delete({"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"})
                source_deleted = True
            except ClientError:
                logger.warning("rollback_source_delete_failed", source_id=source_id)
            # Only adjust the counter if the source row was actually removed, else
            # we'd drift the count. adjust_* is itself best-effort, so the 500 below
            # is always returned.
            if source_deleted:
                adjust_namespace_source_count(namespace_id, SourceType.DATABASE, -1)
            return api_response(
                500,
                {"error": "Failed to create source. Please retry."},
            )

    logger.info("database_source_created", source_id=source_id, namespace_id=namespace_id)
    return api_response(
        202,
        {
            "sourceId": source_id,
            "status": SourceStatus.REGISTERED,
            "scanJobId": scan_job_sk,
            "createdAt": iso_to_epoch(now),
        },
    )


# ---------------------------------------------------------------------------
# LIST TABLES
# ---------------------------------------------------------------------------


def _handle_list_tables(event: dict[str, Any], namespace_id: str, source_id: str) -> dict[str, Any]:
    """GET /namespaces/{namespaceId}/sources/{sourceId}/tables."""
    from coa_common.datazone_forms import FORM_TYPE_NAME
    from coa_control_plane_server.models.review_status import ReviewStatus
    from coa_control_plane_server.models.table_summary import TableSummary

    if not _SMUS_DOMAIN_ID:
        return api_response(500, {"error": "SMUS_DOMAIN_ID not configured"})

    qs = event.get("queryStringParameters") or {}
    review_status_filter = qs.get("reviewStatus")
    next_token = qs.get("nextToken")
    try:
        max_results = min(int(qs.get("maxResults", "50")), 50)  # DataZone Search API hard limit is 50
    except (ValueError, TypeError):
        return api_response(400, {"error": "maxResults must be a valid integer"})

    if review_status_filter:
        try:
            ReviewStatus(review_status_filter)
        except ValueError:
            return api_response(400, {"error": f"Invalid reviewStatus: {review_status_filter}"})

    project_id = _resolve_project_id(namespace_id)
    if not project_id:
        return api_response(404, {"error": f"Namespace {namespace_id} not found"})

    client = _get_smus_client()
    ds_key = f"DS#{source_id}"
    try:
        result = client.search_assets(
            project_id=project_id,
            search_text=ds_key,
            max_results=max_results,
            next_token=next_token,
        )
    except Exception:
        logger.exception("list_tables_search_failed", source_id=source_id, project_id=project_id)
        return api_response(500, {"error": "Failed to search tables"})

    items: list[dict[str, Any]] = []
    skipped_assets: int = 0
    for asset in result.items:
        if not asset.name.startswith(f"{ds_key}:"):
            continue
        try:
            detail = client.get_asset_forms(asset_id=asset.asset_id)
        except Exception:
            skipped_assets += 1
            logger.warning(
                "list_tables_asset_forms_failed",
                source_id=source_id,
                asset_id=asset.asset_id,
                asset_name=asset.name,
            )
            continue
        for form in detail.get("formsOutput", []):
            if form.get("formName") != FORM_TYPE_NAME:
                continue
            try:
                payload = json.loads(form["content"])
            except (json.JSONDecodeError, ValueError):
                skipped_assets += 1
                logger.warning(
                    "list_tables_form_parse_failed",
                    source_id=source_id,
                    asset_id=asset.asset_id,
                    asset_name=asset.name,
                    form_name=form.get("formName"),
                )
                continue
            table_id = f"{payload.get('databaseName', '')}.{payload.get('tableName', '')}"
            cols_field = payload.get("columns", "[]")
            try:
                columns_raw = json.loads(cols_field) if isinstance(cols_field, str) else (cols_field or [])
            except (json.JSONDecodeError, ValueError):
                skipped_assets += 1
                logger.warning(
                    "list_tables_columns_parse_failed",
                    source_id=source_id,
                    asset_id=asset.asset_id,
                    asset_name=asset.name,
                    table_id=table_id,
                )
                continue
            columns_approved = sum(
                1
                for c in columns_raw
                if isinstance(c, dict) and c.get("business_metadata", {}).get("review_status") == ReviewStatus.APPROVED
            )
            summary = TableSummary(
                tableId=table_id,
                name=payload.get("tableName", ""),
                database=payload.get("databaseName", ""),
                columnCount=payload.get("columnCount", 0),
                columnsApproved=columns_approved,
                reviewStatus=payload.get("reviewStatus", ReviewStatus.PENDING_REVIEW),
                enrichmentSource=payload.get("enrichmentSource"),
            )
            if review_status_filter and summary.review_status != review_status_filter:
                continue
            items.append(summary.to_dict())
            break

    response: dict[str, Any] = {"items": items}
    if skipped_assets > 0:
        response["skippedAssets"] = skipped_assets
    if result.next_token:
        response["nextToken"] = result.next_token
    return api_response(200, response)


# ---------------------------------------------------------------------------
# GET TABLE
# ---------------------------------------------------------------------------


def _handle_get_table(namespace_id: str, source_id: str, table_id: str) -> dict[str, Any]:
    """GET /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}."""
    from coa_common.datazone_forms import FORM_TYPE_NAME, deserialize_form
    from coa_control_plane_server.models.business_metadata_output import BusinessMetadataOutput
    from coa_control_plane_server.models.column_metadata import ColumnMetadata
    from coa_control_plane_server.models.foreign_key_output import ForeignKeyOutput
    from coa_control_plane_server.models.primary_key_output import PrimaryKeyOutput
    from coa_control_plane_server.models.review_status import ReviewStatus as RS
    from coa_control_plane_server.models.technical_metadata_output import TechnicalMetadataOutput

    if not _SMUS_DOMAIN_ID:
        return api_response(500, {"error": "SMUS_DOMAIN_ID not configured"})

    project_id = _resolve_project_id(namespace_id)
    if not project_id:
        return api_response(404, {"error": f"Namespace {namespace_id} not found"})

    client = _get_smus_client()
    ds_key = f"DS#{source_id}"
    asset_name = f"{ds_key}:{table_id}"
    try:
        result = client.search_assets(project_id=project_id, search_text=asset_name, max_results=1)
    except Exception:
        logger.exception("get_table_search_failed", source_id=source_id, table_id=table_id)
        return api_response(500, {"error": "Failed to search for table"})

    if not result.items or result.items[0].name != asset_name:
        return api_response(404, {"error": f"Table {table_id} not found"})

    try:
        detail = client.get_asset_forms(asset_id=result.items[0].asset_id)
    except Exception:
        logger.exception("get_table_forms_failed", source_id=source_id, table_id=table_id)
        return api_response(500, {"error": "Failed to retrieve table metadata"})

    for form in detail.get("formsOutput", []):
        if form.get("formName") != FORM_TYPE_NAME:
            continue
        try:
            payload = json.loads(form["content"])
            table = deserialize_form(payload, data_source_id=source_id)
        except Exception:
            logger.exception("get_table_deserialize_failed", source_id=source_id)
            return api_response(500, {"error": "Failed to parse table metadata"})

        biz = table.business_metadata
        pk = None
        if table.primary_key and table.primary_key.columns:
            pk = PrimaryKeyOutput(
                columns=table.primary_key.columns,
                source=table.primary_key.source or None,
                confidence=table.primary_key.confidence or None,
            ).to_dict()
        fks = [
            ForeignKeyOutput(
                column=fk.column,
                targetTable=fk.target_table,
                targetColumn=fk.target_column or None,
                source=fk.source or None,
                confidence=fk.confidence or None,
            ).to_dict()
            for fk in table.foreign_keys
        ] or None
        columns = []
        for col in table.columns:
            col_biz = None
            if col.business_metadata:
                col_biz = BusinessMetadataOutput(
                    description=col.business_metadata.description or None,
                    synonyms=col.business_metadata.synonyms or None,
                    glossaryTerms=col.business_metadata.glossary_terms or None,
                    tags=col.business_metadata.tags or None,
                    enrichmentSource=col.business_metadata.enrichment_source or None,
                    reviewStatus=col.business_metadata.review_status or None,
                    confidence=col.business_metadata.confidence or None,
                ).to_dict()
            columns.append(
                ColumnMetadata(
                    name=col.name,
                    dataType=col.data_type,
                    nullable=col.nullable,
                    isPartitionKey=col.is_partition_key or None,
                    # Source / curated description has a single home now
                    # (business_metadata.description). The Smithy
                    # ColumnMetadata type still exposes a top-level
                    # ``description`` for backward-compat with web UI; map
                    # it from business_metadata so callers that read either
                    # field see the same value.
                    description=col.business_metadata.description or None,
                    businessMetadata=col_biz,
                    distinctValues=col.distinct_values or None,
                ).to_dict()
            )
        tech = TechnicalMetadataOutput(
            columnCount=table.technical_metadata.column_count or None,
            partitionKeys=table.technical_metadata.partition_keys or None,
            format=table.technical_metadata.format or None,
            location=table.technical_metadata.location or None,
        ).to_dict()
        return api_response(
            200,
            {
                "tableId": table.table_id,
                "name": table.name,
                "database": table.database,
                "reviewStatus": biz.review_status or RS.PENDING_REVIEW,
                "businessMetadata": BusinessMetadataOutput(
                    description=biz.description or None,
                    synonyms=biz.synonyms or None,
                    glossaryTerms=biz.glossary_terms or None,
                    tags=biz.tags or None,
                    enrichmentSource=biz.enrichment_source or None,
                    reviewStatus=biz.review_status or None,
                ).to_dict(),
                "primaryKey": pk,
                "foreignKeys": fks,
                "columns": columns,
                "technicalMetadata": tech,
            },
        )

    return api_response(404, {"error": f"Table {table_id} not found"})


# ---------------------------------------------------------------------------
# REVIEW — Resource-oriented endpoints
# ---------------------------------------------------------------------------
#
# Replaces the former bulk POST /review god endpoint. Each handler operates on
# a single asset (one search + one get_asset_forms = ~400ms) and writes a
# DataZone revision only when the resulting state actually changes. This
# eliminates the N+1 pattern that caused the 29s API Gateway timeout for
# sources with 75+ tables.
#
# Cascade rules (match the legacy bulk semantics):
#   - APPROVE on a table cascades to PENDING columns; never overrides REJECTED.
#   - REJECT on a table sets all non-REJECTED columns to REJECTED.
#   - Edit endpoints (PATCH .../metadata) never change reviewStatus — they only
#     set business metadata fields and mark enrichmentSource = STEWARD_EDITED.
#
# Idempotency:
#   - Every review/edit is idempotent. If the resulting reviewStatus equals the
#     existing reviewStatus and no metadata changed, no DataZone revision is
#     written and the counter is not adjusted.
#
# Counter tracking:
#   - tablesApproved is bumped via DynamoDB ADD (atomic) only when a table
#     transitions in or out of APPROVED. Column-level review does not touch it.
#     Counter drift is logged but not raised — the DataZone asset is the canon.


def _smus_or_500() -> tuple[SMUSClient | None, dict[str, Any] | None]:
    """Build the SMUS client or return a 500 if domain not configured."""
    if not _SMUS_DOMAIN_ID:
        return None, api_response(500, {"error": "SMUS_DOMAIN_ID not configured"})
    return _get_smus_client(), None


def _project_or_404(namespace_id: str) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve namespace → DataZone project ID, or return 404."""
    project_id = _resolve_project_id(namespace_id)
    if not project_id:
        return None, api_response(404, {"error": f"Namespace {namespace_id} not found"})
    return project_id, None


def _load_single_asset(
    client: SMUSClient,
    project_id: str,
    source_id: str,
    table_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Search-and-load a single table asset by exact name match.

    Performs at most 2 DataZone API calls (search + get_asset_forms),
    independent of the total table count for the source. Returns
    (asset_dict, None) or (None, error_response).
    """
    from coa_common.datazone_forms import FORM_TYPE_NAME, deserialize_form

    ds_key = f"DS#{source_id}"
    asset_name = f"{ds_key}:{table_id}"
    try:
        # max_results=10 tolerates partial-prefix search hits; we filter to the exact name.
        result = client.search_assets(project_id=project_id, search_text=asset_name, max_results=10)
    except Exception:
        logger.exception("load_single_asset_search_failed", source_id=source_id, table_id=table_id)
        return None, api_response(500, {"error": "Failed to load table from catalog"})

    asset = next((a for a in result.items if a.name == asset_name), None)
    if asset is None:
        return None, api_response(404, {"error": f"Table '{table_id}' not found"})

    try:
        detail = client.get_asset_forms(asset_id=asset.asset_id)
    except Exception:
        logger.exception("load_single_asset_forms_failed", source_id=source_id, table_id=table_id)
        return None, api_response(500, {"error": "Failed to retrieve table metadata"})

    for form in detail.get("formsOutput", []):
        if form.get("formName") != FORM_TYPE_NAME:
            continue
        try:
            payload = json.loads(form["content"])
            table = deserialize_form(payload, data_source_id=source_id)
        except Exception:
            logger.exception("load_single_asset_deserialize_failed", source_id=source_id, table_id=table_id)
            return None, api_response(500, {"error": "Failed to parse table metadata"})
        return {"asset_id": asset.asset_id, "asset_name": asset.name, "table": table}, None

    return None, api_response(500, {"error": "Asset is missing CoaTableMetadata form"})


def _decision_to_status(decision: str) -> str:
    """Map a ReviewDecision value to its corresponding ReviewStatus value."""
    from coa_control_plane_server.models.review_decision import ReviewDecision
    from coa_control_plane_server.models.review_status import ReviewStatus

    return ReviewStatus.APPROVED if decision == ReviewDecision.APPROVED else ReviewStatus.REJECTED


def _approval_delta(old_status: str, new_status: str) -> int:
    """Compute the change to apply to tablesApproved when a table transitions.

    +1 when entering APPROVED, -1 when leaving APPROVED, 0 otherwise.
    """
    from coa_control_plane_server.models.review_status import ReviewStatus

    was_approved = old_status == ReviewStatus.APPROVED
    is_approved = new_status == ReviewStatus.APPROVED
    if was_approved == is_approved:
        return 0
    return 1 if is_approved else -1


def _adjust_approval_counter(namespace_id: str, source_id: str, delta: int) -> None:
    """Atomically adjust the tablesApproved counter on the source record.

    Failures are logged but not raised — the DataZone asset is the source of
    truth; counter drift can be reconciled by re-deriving the count from
    DataZone (re-aggregation). To make systematic drift observable, every
    failed increment emits an ``ApprovalCounterUpdateFailed`` metric so an
    alarm can fire when increments fail repeatedly (manual reconciliation:
    recompute tablesApproved from the APPROVED assets in DataZone and PUT it
    back on the source record).
    """
    if delta == 0:
        return
    try:
        _get_dao().atomic_increment(
            {"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"},
            "tablesApproved",
            amount=delta,
        )
    except ClientError:
        logger.exception(
            "tables_approved_counter_failed",
            namespace_id=namespace_id,
            source_id=source_id,
            delta=delta,
        )
        # Emit a metric so ops can alarm on systematic counter drift.
        emit_metric("ApprovalCounterUpdateFailed", 1, "Count")


def _apply_business_overrides(biz: Any, overrides: dict[str, Any]) -> bool:
    """Apply MetadataOverrides fields to a BusinessMetadata object.

    Returns True if any field was changed (forces enrichmentSource to
    STEWARD_EDITED on change). Only non-None values mutate state — passing
    null/missing leaves the existing field untouched.
    """
    from coa_common.domain_models import EnrichmentSource

    field_map = {
        "description": "description",
        "synonyms": "synonyms",
        "glossaryTerms": "glossary_terms",
        "tags": "tags",
    }
    changed = False
    for in_field, out_attr in field_map.items():
        if in_field in overrides and overrides[in_field] is not None:
            new_value = overrides[in_field]
            if getattr(biz, out_attr) != new_value:
                setattr(biz, out_attr, new_value)
                changed = True
    if changed:
        biz.enrichment_source = EnrichmentSource.STEWARD_EDITED
    return changed


def _parse_decision(body: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Validate and extract a ReviewDecision from a request body."""
    from coa_control_plane_server.models.review_decision import ReviewDecision

    decision = body.get("decision")
    if not decision:
        return None, api_response(400, {"error": "decision is required"})
    try:
        ReviewDecision(decision)
    except ValueError:
        return None, api_response(400, {"error": f"Invalid decision: {decision}"})
    return decision, None


# Source statuses where per-table/column review or edit is allowed.
# Excludes transient bulk states (APPROVING, REJECTING) where the worker
# owns the source, and pre-review states (REGISTERED, SCANNING, ENRICHING).
# After-review states (APPROVED, REJECTED) and failure states
# (APPROVAL_FAILED, REJECTION_FAILED) are reviewable so stewards can adjust
# decisions or recover from a failed bulk run.
_REVIEWABLE_STATES: frozenset[str] = frozenset(
    {
        # NOTE: REJECTED is intentionally absent. A successful bulk reject now
        # makes the source terminal-REJECTED (see worker _lifecycle); from
        # there no per-asset review/edit or bulk approve/reject is allowed —
        # the steward must re-onboard a new source. APPROVAL_FAILED /
        # REJECTION_FAILED remain reviewable so a failed bulk run can be retried.
        "PENDING_REVIEW",
        "APPROVED",
        "APPROVAL_FAILED",
        "REJECTION_FAILED",
    }
)


def _assert_source_reviewable(namespace_id: str, source_id: str) -> dict[str, Any] | None:
    """Return a 409 response if the source is in a non-reviewable state.

    Prevents per-table/column review/edit operations from racing with bulk
    approve/reject workers (or from running before discovery/enrichment is
    complete). One DDB read per call. Returns ``None`` when the operation
    may proceed.
    """
    try:
        item = _get_dao().get(
            {"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"},
            projection=["status", "sourceType"],
        )
    except ClientError:
        logger.exception("assert_reviewable_get_failed", source_id=source_id)
        return api_response(500, {"error": "Internal server error"})

    if not item:
        return api_response(404, {"error": f"Source '{source_id}' not found"})
    if item.get("sourceType") != SourceType.DATABASE:
        return api_response(400, {"error": "Review operations only apply to DATABASE sources"})

    status = item.get("status")
    if status not in _REVIEWABLE_STATES:
        return api_response(
            409,
            {
                "error": (
                    f"Source is in '{status}' state; review operations require one of: {sorted(_REVIEWABLE_STATES)}"
                )
            },
        )
    return None


def _terminal_edit_block(review_status: str, kind: str) -> dict[str, Any] | None:
    """Return a 409 if the asset is in a terminal review state.

    Metadata and key edits are disabled once a table or column is REJECTED —
    the steward must re-onboard. PENDING_REVIEW and APPROVED items can still
    be edited (editing does not change the reviewStatus).
    """
    from coa_control_plane_server.models.review_status import ReviewStatus

    if review_status == ReviewStatus.REJECTED:
        return api_response(
            409,
            {
                "error": (
                    f"Cannot edit {kind} metadata: review status is '{review_status}' (terminal). "
                    f"Editing is only allowed while the {kind} is PENDING_REVIEW or APPROVED."
                )
            },
        )
    return None


def _handle_review_table(event: dict[str, Any], namespace_id: str, source_id: str, table_id: str) -> dict[str, Any]:
    """PUT /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/review.

    Apply a review decision to a single table. Cascades to columns per the
    shared rules in ``coa_common.review_logic``. Idempotent —
    only writes a DataZone revision if the table's reviewStatus changes.
    """
    from coa_common.datazone_forms import build_forms_input
    from coa_common.review_logic import apply_decision_to_table

    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"error": "Invalid JSON body"})

    decision, err = _parse_decision(body)
    if err:
        return err
    assert decision is not None

    err = _assert_source_reviewable(namespace_id, source_id)
    if err:
        return err

    client, err = _smus_or_500()
    if err:
        return err
    assert client is not None
    project_id, err = _project_or_404(namespace_id)
    if err:
        return err
    assert project_id is not None
    asset, err = _load_single_asset(client, project_id, source_id, table_id)
    if err:
        return err
    assert asset is not None

    table = asset["table"]
    old_table_status = table.business_metadata.review_status

    # Cascade to columns first, then the table (see review_logic). Per-asset
    # APPROVE flips PENDING columns to APPROVED; REJECT flips every
    # non-REJECTED column to REJECTED. Persisted atomically below.
    changed = apply_decision_to_table(table, decision)
    new_table_status = table.business_metadata.review_status

    if changed:
        # Write whenever the table OR any column changed — an aggressive reject
        # can flip a still-APPROVED column even when the table was already
        # REJECTED, and that column change must be persisted.
        try:
            client.create_asset_revision(
                asset_id=asset["asset_id"],
                name=asset["asset_name"],
                description=table.business_metadata.description or "",
                forms_input=build_forms_input(table),
            )
        except Exception:
            logger.exception("review_table_revision_failed", source_id=source_id, table_id=table_id)
            return api_response(500, {"error": "Failed to write review"})
        if old_table_status != new_table_status:
            _adjust_approval_counter(namespace_id, source_id, _approval_delta(old_table_status, new_table_status))

    return api_response(200, {"tableId": table_id, "reviewStatus": new_table_status})


def _handle_update_table_metadata(
    event: dict[str, Any], namespace_id: str, source_id: str, table_id: str
) -> dict[str, Any]:
    """PATCH /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/metadata.

    Edit the table's business metadata fields. Sets enrichmentSource =
    STEWARD_EDITED. Does NOT change reviewStatus.
    """
    from coa_common.datazone_forms import build_forms_input

    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"error": "Invalid JSON body"})

    overrides = body.get("overrides")
    if not isinstance(overrides, dict) or not overrides:
        return api_response(400, {"error": "overrides is required"})

    err = _assert_source_reviewable(namespace_id, source_id)
    if err:
        return err

    client, err = _smus_or_500()
    if err:
        return err
    assert client is not None
    project_id, err = _project_or_404(namespace_id)
    if err:
        return err
    assert project_id is not None
    asset, err = _load_single_asset(client, project_id, source_id, table_id)
    if err:
        return err
    assert asset is not None

    table = asset["table"]
    if (blocked := _terminal_edit_block(table.business_metadata.review_status, "table")) is not None:
        return blocked
    if _apply_business_overrides(table.business_metadata, overrides):
        try:
            client.create_asset_revision(
                asset_id=asset["asset_id"],
                name=asset["asset_name"],
                description=table.business_metadata.description or "",
                forms_input=build_forms_input(table),
            )
        except Exception:
            logger.exception("update_table_metadata_revision_failed", source_id=source_id, table_id=table_id)
            return api_response(500, {"error": "Failed to write metadata update"})

    return api_response(
        200,
        {"tableId": table_id, "reviewStatus": table.business_metadata.review_status},
    )


def _handle_update_table_keys(
    event: dict[str, Any], namespace_id: str, source_id: str, table_id: str
) -> dict[str, Any]:
    """PATCH /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/keys.

    Replace the table's primary key and/or foreign keys. Steward edits are
    authoritative: keys that actually change are stored with
    source = STEWARD_SPECIFIED, overriding deterministic or AI-inferred keys.
    Keys that are unchanged keep their original provenance, so editing one key
    never re-stamps the others. An omitted field is left unchanged; an empty
    list clears it. Key columns are validated against the table's own columns.
    Does NOT change reviewStatus.
    """
    from coa_common.datazone_forms import build_forms_input
    from coa_common.domain_models import EnrichmentSource, ForeignKey, PrimaryKey

    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"error": "Invalid JSON body"})

    pk_in = body.get("primaryKey")
    fks_in = body.get("foreignKeys")
    if pk_in is None and fks_in is None:
        return api_response(400, {"error": "primaryKey or foreignKeys is required"})

    err = _assert_source_reviewable(namespace_id, source_id)
    if err:
        return err
    client, err = _smus_or_500()
    if err:
        return err
    assert client is not None
    project_id, err = _project_or_404(namespace_id)
    if err:
        return err
    assert project_id is not None
    asset, err = _load_single_asset(client, project_id, source_id, table_id)
    if err:
        return err
    assert asset is not None

    table = asset["table"]
    if (blocked := _terminal_edit_block(table.business_metadata.review_status, "table")) is not None:
        return blocked
    valid_cols = {c.name for c in table.columns}

    if pk_in is not None:
        cols = pk_in.get("columns")
        if not isinstance(cols, list):
            return api_response(400, {"error": "primaryKey.columns must be a list"})
        unknown = [c for c in cols if c not in valid_cols]
        if unknown:
            return api_response(400, {"error": f"Unknown primary key column(s): {unknown}"})
        # De-duplicate while preserving composite-key order.
        cols = list(dict.fromkeys(cols))
        existing_pk = table.primary_key
        # Only stamp STEWARD_SPECIFIED when the key actually changed; an
        # unchanged key keeps its original provenance (DETERMINISTIC / AI_INFERRED).
        if existing_pk and cols == existing_pk.columns:
            table.primary_key = PrimaryKey(columns=cols, source=existing_pk.source, confidence=existing_pk.confidence)
        else:
            table.primary_key = PrimaryKey(columns=cols, source=EnrichmentSource.STEWARD_SPECIFIED)

    if fks_in is not None:
        if not isinstance(fks_in, list):
            return api_response(400, {"error": "foreignKeys must be a list"})
        # Index existing FKs so unchanged rows retain their original provenance.
        existing_fk_by_key = {(fk.column, fk.target_table, fk.target_column or ""): fk for fk in table.foreign_keys}
        new_fks: list[ForeignKey] = []
        for fk in fks_in:
            col = fk.get("column") if isinstance(fk, dict) else None
            target = fk.get("targetTable") if isinstance(fk, dict) else None
            if not col or not target:
                return api_response(400, {"error": "Each foreign key requires column and targetTable"})
            if col not in valid_cols:
                return api_response(400, {"error": f"Unknown foreign key column: {col}"})
            tcol = fk.get("targetColumn") or ""
            existing = existing_fk_by_key.get((col, target, tcol))
            new_fks.append(
                existing
                if existing is not None
                else ForeignKey(
                    column=col, target_table=target, target_column=tcol, source=EnrichmentSource.STEWARD_SPECIFIED
                )
            )
        table.foreign_keys = new_fks

    try:
        client.create_asset_revision(
            asset_id=asset["asset_id"],
            name=asset["asset_name"],
            description=table.business_metadata.description or "",
            forms_input=build_forms_input(table),
        )
    except Exception:
        logger.exception("update_table_keys_revision_failed", source_id=source_id, table_id=table_id)
        return api_response(500, {"error": "Failed to write keys update"})

    return api_response(
        200,
        {"tableId": table_id, "reviewStatus": table.business_metadata.review_status},
    )


def _handle_review_column(
    event: dict[str, Any],
    namespace_id: str,
    source_id: str,
    table_id: str,
    column_name: str,
) -> dict[str, Any]:
    """PUT /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/columns/{columnName}/review.

    Apply a review decision to a single column. Idempotent — only writes a
    DataZone revision if the column's reviewStatus changes. Does NOT change
    table-level review status or the tablesApproved counter.
    """
    from coa_common.datazone_forms import build_forms_input

    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"error": "Invalid JSON body"})

    decision, err = _parse_decision(body)
    if err:
        return err
    assert decision is not None

    err = _assert_source_reviewable(namespace_id, source_id)
    if err:
        return err

    client, err = _smus_or_500()
    if err:
        return err
    assert client is not None
    project_id, err = _project_or_404(namespace_id)
    if err:
        return err
    assert project_id is not None
    asset, err = _load_single_asset(client, project_id, source_id, table_id)
    if err:
        return err
    assert asset is not None

    table = asset["table"]
    column = next((c for c in table.columns if c.name == column_name), None)
    if column is None:
        return api_response(404, {"error": f"Column '{column_name}' not found on table '{table_id}'"})

    old_col_status = column.business_metadata.review_status
    new_col_status = _decision_to_status(decision)

    if old_col_status != new_col_status:
        column.business_metadata.review_status = new_col_status
        try:
            client.create_asset_revision(
                asset_id=asset["asset_id"],
                name=asset["asset_name"],
                description=table.business_metadata.description or "",
                forms_input=build_forms_input(table),
            )
        except Exception:
            logger.exception(
                "review_column_revision_failed",
                source_id=source_id,
                table_id=table_id,
                column_name=column_name,
            )
            return api_response(500, {"error": "Failed to write column review"})

    return api_response(
        200,
        {
            "tableId": table_id,
            "columnName": column_name,
            "reviewStatus": new_col_status,
        },
    )


def _handle_update_column_metadata(
    event: dict[str, Any],
    namespace_id: str,
    source_id: str,
    table_id: str,
    column_name: str,
) -> dict[str, Any]:
    """PATCH /namespaces/{namespaceId}/sources/{sourceId}/tables/{tableId}/columns/{columnName}/metadata.

    Edit a single column's business metadata. Sets enrichmentSource =
    STEWARD_EDITED. Does NOT change reviewStatus.
    """
    from coa_common.datazone_forms import build_forms_input

    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"error": "Invalid JSON body"})

    overrides = body.get("overrides")
    if not isinstance(overrides, dict) or not overrides:
        return api_response(400, {"error": "overrides is required"})

    err = _assert_source_reviewable(namespace_id, source_id)
    if err:
        return err

    client, err = _smus_or_500()
    if err:
        return err
    assert client is not None
    project_id, err = _project_or_404(namespace_id)
    if err:
        return err
    assert project_id is not None
    asset, err = _load_single_asset(client, project_id, source_id, table_id)
    if err:
        return err
    assert asset is not None

    table = asset["table"]
    column = next((c for c in table.columns if c.name == column_name), None)
    if column is None:
        return api_response(404, {"error": f"Column '{column_name}' not found on table '{table_id}'"})

    if (blocked := _terminal_edit_block(column.business_metadata.review_status, "column")) is not None:
        return blocked

    if _apply_business_overrides(column.business_metadata, overrides):
        try:
            client.create_asset_revision(
                asset_id=asset["asset_id"],
                name=asset["asset_name"],
                description=table.business_metadata.description or "",
                forms_input=build_forms_input(table),
            )
        except Exception:
            logger.exception(
                "update_column_metadata_revision_failed",
                source_id=source_id,
                table_id=table_id,
                column_name=column_name,
            )
            return api_response(500, {"error": "Failed to write metadata update"})

    return api_response(
        200,
        {
            "tableId": table_id,
            "columnName": column_name,
            "reviewStatus": column.business_metadata.review_status,
        },
    )


# ---------------------------------------------------------------------------
# BULK APPROVE / REJECT — async via SQS worker
# ---------------------------------------------------------------------------
#
# Bulk operations cannot run inline within the 29s API Gateway timeout for
# sources with 75+ tables (each table requires search + get_asset_forms +
# create_asset_revision = 3 DataZone API calls). Instead the request is
# enqueued and a worker Lambda processes it asynchronously.
#
# The status transition (PENDING_REVIEW or *_FAILED) → APPROVING/REJECTING
# happens via a conditional DynamoDB update, which gives us idempotency: a
# duplicate API call (or replayed SQS message at the worker layer) finds the
# source already in the transient state and is rejected as a 409, preventing
# two workers from racing on the same source.
#
# Frontend polls GetSource for the source's `status` field. Terminal states:
#   - APPROVE flow:  APPROVED        (or APPROVAL_FAILED on worker error)
#   - REJECT flow:   PENDING_REVIEW  (rejection puts the source back into
#                                     review; tables marked REJECTED retain
#                                     that status — REJECTION_FAILED on error)


# Per-decision lifecycle: maps a ReviewDecision value to the
# (transient_status, failure_status, allowed_entry_states) triple.
def _bulk_lifecycle(decision: str) -> tuple[str, str, tuple[str, str]]:
    """Return (transient, failed, allowed_entry_states) for a decision."""
    from coa_control_plane_server.models.review_decision import ReviewDecision

    if decision == ReviewDecision.APPROVED:
        return (
            SourceStatus.APPROVING,
            SourceStatus.APPROVAL_FAILED,
            (SourceStatus.PENDING_REVIEW, SourceStatus.APPROVAL_FAILED),
        )
    if decision == ReviewDecision.REJECTED:
        return (
            SourceStatus.REJECTING,
            SourceStatus.REJECTION_FAILED,
            (SourceStatus.PENDING_REVIEW, SourceStatus.REJECTION_FAILED),
        )
    raise ValueError(f"Unsupported decision: {decision}")


def _enqueue_bulk_review(namespace_id: str, source_id: str, decision: str) -> dict[str, Any] | None:
    """Send a bulk-review SQS message. Returns an error response on failure."""
    if not _REVIEW_QUEUE_URL:
        return api_response(500, {"error": "REVIEW_QUEUE_URL not configured"})
    payload = {
        "namespaceId": namespace_id,
        "sourceId": source_id,
        "decision": decision,
    }
    try:
        _get_sqs().send_message(
            QueueUrl=_REVIEW_QUEUE_URL,
            MessageBody=json.dumps(payload),
            # Best-effort dedup: SQS Standard doesn't enforce it, but the conditional
            # status transition above is the real guard. The MessageGroupId is unused
            # for Standard queues; for FIFO we'd set it to source_id.
        )
    except ClientError:
        logger.exception("enqueue_bulk_review_failed", source_id=source_id)
        return api_response(500, {"error": "Failed to enqueue bulk review"})
    return None


def _transition_to_transient(
    namespace_id: str,
    source_id: str,
    transient_status: str,
    allowed_entry_states: tuple[str, ...],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Atomically transition source status to a bulk transient state.

    The conditional update only fires if the source is currently in one of
    ``allowed_entry_states`` (typically PENDING_REVIEW or the matching
    *_FAILED). On condition failure we return 409 with the actual current
    status. Returns (source_item, None) on success, (None, error_response)
    on failure.
    """
    try:
        item = _get_dao().get({"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"})
    except ClientError:
        logger.exception("ddb_get_for_transition_failed", source_id=source_id)
        return None, api_response(500, {"error": "Internal server error"})
    if not item:
        return None, api_response(404, {"error": f"Source '{source_id}' not found"})
    if item.get("sourceType") != SourceType.DATABASE:
        return None, api_response(400, {"error": "Bulk review only applies to DATABASE sources"})

    # Bulk approve / reject is meaningless when no tables have been discovered
    # yet (the worker would no-op against an empty asset set). Reject the
    # request rather than transition the source into a transient state and
    # leave the user staring at an APPROVING / REJECTING badge that never
    # resolves. The UI also disables the buttons in this case but we enforce
    # here to prevent direct API misuse.
    tables_discovered = int(item.get("tablesDiscovered") or 0)
    if tables_discovered <= 0:
        return None, api_response(
            400,
            {
                "error": (
                    "Bulk review requires at least one discovered table; "
                    "the source has 0 tables. Wait for the scan to complete or re-scan the source first."
                ),
                "sourceId": source_id,
                "tablesDiscovered": tables_discovered,
            },
        )

    # Build IN-clause placeholders dynamically so the helper supports any tuple
    # of allowed entry states.
    placeholders = [f":entry{i}" for i in range(len(allowed_entry_states))]
    condition = f"#status IN ({', '.join(placeholders)})"
    condition_values = dict(zip(placeholders, allowed_entry_states, strict=True))

    try:
        _get_dao().update(
            {"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"},
            {"status": transient_status},
            condition=condition,
            condition_names={"#status": "status"},
            condition_values=condition_values,
            raise_on_error=True,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None, api_response(
                409,
                {
                    "error": (
                        f"Source is in '{item.get('status')}' state; "
                        f"bulk review requires one of: {list(allowed_entry_states)}"
                    )
                },
            )
        logger.exception("transition_to_transient_failed", source_id=source_id)
        return None, api_response(500, {"error": "Internal server error"})

    return item, None


def _handle_bulk_review(
    event: dict[str, Any],  # noqa: ARG001 — body is unused; decision is path-derived
    namespace_id: str,
    source_id: str,
    decision: str,
) -> dict[str, Any]:
    """Shared implementation for ApproveSource / RejectSource.

    Action endpoints — no body is consumed. Returns 202 with the new
    transient status, leaving the actual DataZone writes to the worker.
    """
    transient, failed, allowed_entry = _bulk_lifecycle(decision)

    _, err = _transition_to_transient(namespace_id, source_id, transient, allowed_entry)
    if err:
        return err

    err = _enqueue_bulk_review(namespace_id, source_id, decision)
    if err:
        # Best-effort rollback: if SQS enqueue failed, restore status so the user
        # can retry. We don't fail-fast on rollback errors; the worker has its
        # own status check and the source can be manually un-stuck.
        try:
            _get_dao().update(
                {"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"},
                {"status": failed},
                raise_on_error=False,
            )
        except Exception:
            logger.exception("rollback_to_failed_state_failed", source_id=source_id)
        return err

    return api_response(202, {"sourceId": source_id, "status": transient})


def _handle_approve_source(event: dict[str, Any], namespace_id: str, source_id: str) -> dict[str, Any]:
    """POST /namespaces/{namespaceId}/sources/{sourceId}/approve (202)."""
    from coa_control_plane_server.models.review_decision import ReviewDecision

    return _handle_bulk_review(event, namespace_id, source_id, ReviewDecision.APPROVED)


def _handle_reject_source(event: dict[str, Any], namespace_id: str, source_id: str) -> dict[str, Any]:
    """POST /namespaces/{namespaceId}/sources/{sourceId}/reject (202)."""
    from coa_control_plane_server.models.review_decision import ReviewDecision

    return _handle_bulk_review(event, namespace_id, source_id, ReviewDecision.REJECTED)


# ---------------------------------------------------------------------------
# GET SCAN JOB
# ---------------------------------------------------------------------------


def _handle_get_scan_job(namespace_id: str, source_id: str, job_id: str) -> dict[str, Any]:
    """GET /namespaces/{namespaceId}/sources/{sourceId}/scan/{jobId}.

    Reads from source-scan-jobs table.
    PK = SRC#{sourceId}, SK = <ISO timestamp stored at job creation>
    The jobId path param is the ISO timestamp SK.
    """
    job_id = unquote(job_id)
    try:
        source_item = _get_dao().get({"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"})
    except ClientError:
        logger.exception("ddb_get_failed", source_id=source_id)
        return api_response(500, {"error": "Internal server error"})

    if not source_item:
        return api_response(404, {"error": f"Source '{source_id}' not found"})

    try:
        scan_item = _get_scan_dao().get({"PK": f"SRC#{source_id}", "SK": job_id})
    except ClientError:
        logger.exception("ddb_get_scan_job_failed", source_id=source_id, job_id=job_id)
        return api_response(500, {"error": "Internal server error"})

    if not scan_item:
        return api_response(404, {"error": f"Scan job '{job_id}' not found"})

    response: dict[str, Any] = {
        "scanJobId": job_id,
        "sourceId": source_id,
        "status": scan_item.get("status"),
        "scanType": scan_item.get("scanType"),
        "tablesDiscovered": scan_item.get("tablesDiscovered"),
        "columnsDiscovered": scan_item.get("columnsDiscovered"),
        "startedAt": iso_to_epoch(scan_item.get("startedAt")),
        "completedAt": iso_to_epoch(scan_item.get("completedAt")),
        "errorMessage": scan_item.get("errorMessage"),
    }
    return api_response(200, {k: v for k, v in response.items() if v is not None})


# ---------------------------------------------------------------------------
# UPDATE METADATA
# ---------------------------------------------------------------------------


def _handle_update_metadata(event: dict[str, Any], namespace_id: str, source_id: str) -> dict[str, Any]:
    """PUT /namespaces/{namespaceId}/sources/{sourceId}/metadata.

    Updates mutable fields on a DATABASE source: name, configuration,
    metadataEnrichmentEnabled.
    """
    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"error": "Invalid JSON body"})

    if not body:
        return api_response(400, {"error": "Request body must not be empty"})

    try:
        item = _get_dao().get({"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"})
    except ClientError:
        logger.exception("ddb_get_failed", source_id=source_id)
        return api_response(500, {"error": "Internal server error"})

    if not item:
        return api_response(404, {"error": f"Source '{source_id}' not found"})

    if item.get("sourceType") != SourceType.DATABASE:
        return api_response(400, {"error": "Metadata update is only supported for DATABASE sources"})

    update_fields: dict[str, Any] = {}

    if "name" in body and body["name"] is not None:
        name = str(body["name"]).strip()
        if not name:
            return api_response(400, {"error": "name must not be blank"})
        update_fields["name"] = name

    if "metadataEnrichmentEnabled" in body and body["metadataEnrichmentEnabled"] is not None:
        update_fields["metadataEnrichmentEnabled"] = bool(body["metadataEnrichmentEnabled"])

    glue_config = body.get("glueConfiguration")
    jdbc_config = body.get("jdbcConfiguration")
    if glue_config and jdbc_config:
        return api_response(400, {"error": "Cannot update both glueConfiguration and jdbcConfiguration"})
    if glue_config:
        from coa_control_plane_server.models.glue_configuration import GlueConfiguration
        from pydantic import ValidationError as PydanticValidationError

        try:
            GlueConfiguration.model_validate(glue_config)
        except PydanticValidationError as exc:
            return api_response(400, {"error": f"Invalid glueConfiguration: {exc.errors()[0]['msg']}"})
        update_fields["configuration"] = json.dumps(glue_config)
    if jdbc_config:
        from coa_control_plane_server.models.jdbc_configuration import JdbcConfiguration
        from pydantic import ValidationError as PydanticValidationError

        try:
            JdbcConfiguration.model_validate(jdbc_config)
        except PydanticValidationError as exc:
            return api_response(400, {"error": f"Invalid jdbcConfiguration: {exc.errors()[0]['msg']}"})
        update_fields["configuration"] = json.dumps(jdbc_config)

    if not update_fields:
        return api_response(400, {"error": "No updatable fields provided"})

    try:
        _get_dao().update(
            {"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"},
            update_fields,
        )
    except ClientError:
        logger.exception("ddb_update_failed", source_id=source_id)
        return api_response(500, {"error": "Internal server error"})

    updated = _get_dao().get({"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"})
    return api_response(
        200,
        {
            "sourceId": source_id,
            "status": (updated or item).get("status"),
            "updatedAt": iso_to_epoch((updated or item).get("updatedAt")),
        },
    )
