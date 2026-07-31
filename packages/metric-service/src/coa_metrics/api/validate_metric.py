# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate Metric Lambda handler.

POST /namespaces/{namespaceId}/metrics/validate → 200 OK

Runs all validation checks (1-6) against a metric definition supplied in the
request body, without persisting it ("validate before create"). Returns
advisory warnings. This mirrors the validation that runs implicitly on
create (POST /metrics) and update (PUT /metrics/{name}).
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog
from coa_common.logging import setup_logging
from coa_common.response import api_response, get_caller_identity
from coa_control_plane_server.models.validate_metric_request_content import (
    ValidateMetricRequestContent,
)
from pydantic import ValidationError

from coa_metrics.api.validation_errors import format_validation_error
from coa_metrics.data_source_lookup_factory import build_data_source_lookup
from coa_metrics.lookups import DataSourceLookup, NeptuneOntologyLookup
from coa_metrics.validator import validate_metric

setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
logger = structlog.get_logger(__name__)


# ── Singleton clients ───────────────────────────────────────────────────

# Per-namespace cache: the SMUS-backed lookup is namespace-scoped.
_data_source_lookups: dict[str, DataSourceLookup | None] = {}
_ontology_lookup: NeptuneOntologyLookup | None = None


def _get_data_source_lookup(namespace: str) -> DataSourceLookup | None:
    """Get or build the data source lookup for a namespace.

    Returns None when SMUS catalog access is not configured or the namespace
    has no DataZone project — metadata checks (2-5) are then skipped.
    """
    if namespace not in _data_source_lookups:
        try:
            _data_source_lookups[namespace] = build_data_source_lookup(namespace)
        except Exception as exc:
            logger.warning("data_source_lookup_init_failed", namespace=namespace, error=str(exc))
            _data_source_lookups[namespace] = None
    return _data_source_lookups[namespace]


def _get_ontology_lookup() -> NeptuneOntologyLookup | None:
    """Get or create the ontology lookup. Returns None if Neptune is unavailable."""
    global _ontology_lookup  # noqa: PLW0603
    if _ontology_lookup is None:
        try:
            _ontology_lookup = NeptuneOntologyLookup()
        except Exception as exc:
            logger.warning("ontology_lookup_init_failed", error=str(exc))
            return None
    return _ontology_lookup


# ── Handler ─────────────────────────────────────────────────────────────


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Gateway proxy-integration Lambda handler for POST /namespaces/{ns}/metrics/validate."""
    namespace = (event.get("pathParameters") or {}).get("namespaceId", "")
    caller = get_caller_identity(event)
    logger.info("validate_metric", namespace=namespace, caller=caller)

    if not namespace:
        return api_response(400, {"message": "namespace is required"})

    # Parse request body
    try:
        body = json.loads(event.get("body") or "null")
    except (json.JSONDecodeError, TypeError):
        return api_response(400, {"message": "Invalid JSON in request body"})

    if body is None:
        return api_response(400, {"message": "Request body is required"})

    # Validate request structure via Smithy-generated Pydantic model
    try:
        request = ValidateMetricRequestContent.model_validate(body)
    except ValidationError as exc:
        return api_response(400, {"message": format_validation_error(exc)})

    metric_body = {
        "name": request.name,
        "description": request.description,
        "expression": {
            "dialects": [{"dialect": d.dialect, "expression": d.expression} for d in request.expression.dialects],
        },
        "dataSourceId": request.data_source_id,
        "sourceTable": request.source_table,
        "ontologyConcepts": request.ontology_concepts or [],
    }

    # Run validation
    try:
        result = validate_metric(
            metric_body=metric_body,
            data_sources_lookup=_get_data_source_lookup(namespace),
            ontology_lookup=_get_ontology_lookup(),
            namespace=namespace,
        )
    except Exception as exc:
        logger.exception("validation_failed", error=str(exc))
        return api_response(500, {"message": "Internal error during validation"})

    # The contract exposes a single advisory `warnings` list (WarningSeverity:
    # WARNING | INFO). Blocking syntax errors map to WARNING, soft findings to INFO.
    warnings = [
        {"field": err.get("check", "sql_syntax"), "message": err["message"], "severity": "WARNING"}
        for err in result.errors
    ] + [
        {"field": warn.get("check", "validation"), "message": warn["message"], "severity": "INFO"}
        for warn in result.warnings
    ]

    return api_response(200, {"warnings": warnings})
