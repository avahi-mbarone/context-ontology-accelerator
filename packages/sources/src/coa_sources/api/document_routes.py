# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Document-source route handlers.

Handles all DOCUMENTS source operations:
  POST   /namespaces/{namespaceId}/sources             — create document source
  POST   /namespaces/{namespaceId}/sources/upload-urls — pre-signed S3 upload URLs
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import unquote

import structlog
from botocore.exceptions import ClientError
from coa_common.constants import (
    SUPPORTED_UPLOAD_CONTENT_TYPES,
    to_graphrag_tenant_id,
    validate_s3_prefix,
)
from coa_common.dao.base import QueryParams
from coa_common.response import api_response, get_caller_identity
from coa_control_plane_server.models.extraction_config import ExtractionConfig
from coa_control_plane_server.models.source_status import SourceStatus
from coa_control_plane_server.models.source_sub_type import SourceSubType
from coa_control_plane_server.models.source_type import SourceType

from coa_sources.utils import merge_extraction_config

from .namespace_counters import adjust_namespace_source_count
from .sources_handler import (
    _BUCKET_NAME,
    _INGESTION_QUEUE_URL,
    _MAX_UPLOAD_FILES,
    _UPLOAD_URL_EXPIRY_SECONDS,
    _get_dao,
    _get_s3,
    _get_sqs,
    _item_to_detail,
    _now_iso,
    _source_id_from_item,
)

_BY_NAME_GSI = "ByName"

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# CREATE DOCUMENT SOURCE
# ---------------------------------------------------------------------------


def _create_document_source(doc_req: Any, namespace_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """Create a DOCUMENTS source. doc_req is a CreateDocumentSourceInput model instance."""
    name: str = doc_req.name.strip()
    if not name:
        return api_response(400, {"error": "name is required"})

    source_bucket_arn: str | None = doc_req.source_bucket_arn or None
    s3_prefixes: list[str] = [p.strip() for p in (doc_req.s3_prefixes or [])]
    role_arn: str | None = doc_req.role_arn or None

    # Infer sub-type: sourceBucketArn → S3, else → LOCAL_UPLOAD
    if source_bucket_arn:
        sub_type = SourceSubType.S3
        doc_source_type = "s3"
    else:
        sub_type = SourceSubType.LOCAL_UPLOAD
        doc_source_type = "upload"

    if doc_source_type == "s3" and not source_bucket_arn:
        return api_response(400, {"error": "sourceBucketArn is required for S3 sources"})
    if doc_source_type == "upload" and not s3_prefixes:
        return api_response(400, {"error": "s3Prefixes is required for upload sources"})

    for prefix in s3_prefixes:
        try:
            validate_s3_prefix(prefix, "s3Prefixes")
        except ValueError as exc:
            return api_response(400, {"error": str(exc)})

    try:
        extraction_config = merge_extraction_config(doc_req.extraction_config)
    except ValueError as exc:
        return api_response(400, {"error": str(exc)})

    # Name uniqueness check via ByName GSI — O(1) lookup matching existing unstructured pattern
    try:
        gsi_result = _get_dao().query(
            QueryParams(
                key_condition="namespaceId = :ns AND #n = :name",
                expression_values={":ns": namespace_id, ":name": name},
                expression_names={"#n": "name"},
                index_name=_BY_NAME_GSI,
                limit=1,
            )
        )
        if gsi_result.items:
            existing = gsi_result.items[0]
            current_status = existing.get("status", "")
            existing_id = _source_id_from_item(existing)
            return api_response(
                409,
                {
                    "error": (f"A document source named '{name}' already exists (status: '{current_status}')."),
                    "sourceId": existing_id,
                    "status": current_status,
                },
            )
    except ClientError:
        logger.exception("ddb_gsi_query_failed")
        return api_response(500, {"error": "Internal server error"})

    source_id = str(uuid.uuid4())
    tenant_id = to_graphrag_tenant_id(namespace_id, source_id)
    now = _now_iso()

    extraction_config_stored = ExtractionConfig.model_validate(extraction_config).model_dump(
        by_alias=True, exclude_none=True
    )

    item: dict[str, Any] = {
        "PK": f"NS#{namespace_id}",
        "SK": f"SRC#{source_id}",
        "sourceId": source_id,
        "namespaceId": namespace_id,
        "name": name,
        "sourceType": SourceType.DOCUMENTS,
        "sourceSubType": sub_type,
        "docSourceType": doc_source_type,
        "status": SourceStatus.REGISTERED,
        "tenantId": tenant_id,
        "s3Prefixes": s3_prefixes,
        "extractionConfig": extraction_config_stored,
        "createdBy": get_caller_identity(event),
        "createdAt": now,
        "updatedAt": now,
        "sourceTypeCreatedAt": f"{SourceType.DOCUMENTS.value}#{now}",
    }
    if source_bucket_arn:
        item["sourceBucketArn"] = source_bucket_arn
    if role_arn:
        item["roleArn"] = role_arn

    try:
        _get_dao().put(item)
    except ClientError:
        logger.exception("ddb_put_failed")
        return api_response(500, {"error": "Internal server error"})

    # Increment the namespace sourceCount. Best-effort: counter drift
    # is undesirable but must never block source creation.
    adjust_namespace_source_count(namespace_id, SourceType.DOCUMENTS, 1)

    if _INGESTION_QUEUE_URL:
        sqs_body: dict[str, Any] = {
            "namespace_id": namespace_id,
            "doc_source_id": source_id,
            "tenant_id": tenant_id,
            "source_type": doc_source_type,
            "s3_prefixes": s3_prefixes,
            "extraction_config": extraction_config,
        }
        if source_bucket_arn:
            sqs_body["source_bucket_arn"] = source_bucket_arn
        if role_arn:
            sqs_body["role_arn"] = role_arn
        try:
            _get_sqs().send_message(
                QueueUrl=_INGESTION_QUEUE_URL,
                MessageBody=json.dumps(sqs_body, default=str),
            )
        except ClientError:
            logger.exception("sqs_send_failed", source_id=source_id)
            try:
                _get_dao().update(
                    {"PK": f"NS#{namespace_id}", "SK": f"SRC#{source_id}"},
                    {"status": SourceStatus.SCAN_FAILED, "errorMessage": "Failed to enqueue ingestion job"},
                )
            except ClientError:
                logger.exception("ddb_update_scan_failed_status_failed", source_id=source_id)
            return api_response(500, {"error": "Internal server error"})

    logger.info("document_source_created", source_id=source_id, namespace_id=namespace_id)
    return api_response(201, _item_to_detail(item))


# ---------------------------------------------------------------------------
# UPLOAD URLS
# ---------------------------------------------------------------------------


def _handle_upload_urls(event: dict[str, Any], namespace_id: str) -> dict[str, Any]:
    """POST /namespaces/{namespaceId}/sources/upload-urls — generate pre-signed S3 PUT URLs."""
    if not _BUCKET_NAME:
        return api_response(500, {"error": "Internal server error"})

    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"error": "Invalid JSON in request body"})

    files: list[Any] = body.get("files") or []
    if not files:
        return api_response(400, {"error": "files must not be empty"})
    if len(files) > _MAX_UPLOAD_FILES:
        return api_response(400, {"error": f"Too many files: maximum {_MAX_UPLOAD_FILES} per request"})

    validated: list[dict[str, str]] = []
    for i, f in enumerate(files):
        if not isinstance(f, dict):
            return api_response(400, {"error": f"files[{i}] must be an object with filename and contentType"})
        filename = (f.get("filename") or "").strip()
        content_type = (f.get("contentType") or "").strip()
        if not filename:
            return api_response(400, {"error": f"files[{i}].filename must not be blank"})
        # Decode percent-encoding before checking for path traversal
        decoded = unquote(filename)
        if any(c in decoded for c in ["/", "\\", "\0"]) or ".." in decoded or decoded.startswith("."):
            return api_response(400, {"error": f"files[{i}].filename contains invalid characters"})
        if not content_type:
            return api_response(400, {"error": f"files[{i}].contentType must not be blank"})
        if content_type not in SUPPORTED_UPLOAD_CONTENT_TYPES:
            return api_response(400, {"error": f"files[{i}].contentType '{content_type}' is not supported"})
        validated.append({"filename": filename, "contentType": content_type})

    upload_id = str(uuid.uuid4())
    s3_prefix = f"{namespace_id}/raw/{upload_id}/"
    upload_urls: list[dict[str, str]] = []
    try:
        for entry in validated:
            s3_key = f"{s3_prefix}{entry['filename']}"
            url = _get_s3().generate_presigned_url(
                "put_object",
                Params={"Bucket": _BUCKET_NAME, "Key": s3_key, "ContentType": entry["contentType"]},
                ExpiresIn=_UPLOAD_URL_EXPIRY_SECONDS,
            )
            upload_urls.append({"filename": entry["filename"], "uploadUrl": url})
    except ClientError:
        logger.exception("presigned_url_generation_failed", namespace_id=namespace_id)
        return api_response(500, {"error": "Internal server error"})

    return api_response(
        200,
        {
            "uploadId": upload_id,
            "s3Prefix": s3_prefix,
            "uploadUrls": upload_urls,
            "expiresIn": _UPLOAD_URL_EXPIRY_SECONDS,
        },
    )
