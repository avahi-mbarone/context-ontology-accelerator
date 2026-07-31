# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Atomic maintenance of per-namespace source counters.

The Namespaces table stores a ``sourceCount`` attribute that the UI uses
to render quick summary numbers on the namespace list and detail pages.
The Sources service is the source of truth for this counter: every time
a source is created the counter is incremented, and every time a source
is removed the counter is decremented.

Kept in its own module to avoid a circular import between
``sources_handler.py`` (the Lambda entry point) and the per-source-type
route helpers (``database_routes.py``, ``document_routes.py``) — both
of which need to bump the counter on create.
"""

from __future__ import annotations

import os

import structlog
from botocore.exceptions import ClientError
from coa_common import resolve_region
from coa_common.dao import DynamoDBDAO

logger = structlog.get_logger(__name__)

_NAMESPACES_TABLE: str = os.environ.get("NAMESPACES_TABLE", "")
_AWS_REGION: str = resolve_region()

_ns_dao: DynamoDBDAO | None = None


def _get_ns_dao() -> DynamoDBDAO | None:
    """Lazy-construct the namespaces DDB DAO on first use.

    Returns ``None`` (rather than raising) when ``NAMESPACES_TABLE`` is
    not configured. The counter is best-effort and we never want a
    misconfigured deployment — or a test that doesn't bother setting
    the env var — to fail the create/delete workflow that calls us.
    """
    global _ns_dao
    if _ns_dao is None:
        table_name = os.environ.get("NAMESPACES_TABLE", _NAMESPACES_TABLE)
        if not table_name:
            return None
        _ns_dao = DynamoDBDAO(table_name, region=_AWS_REGION)
    return _ns_dao


def adjust_namespace_source_count(namespace_id: str, source_type: str, delta: int) -> None:
    """Atomically bump the namespace's source counter by ``delta``.

    Best-effort: counter drift is undesirable but must never block the
    source create/delete workflow. We therefore swallow ``ClientError``
    and log so a transient DynamoDB error does not orphan a successfully
    written source row.
    """
    if delta == 0:
        return
    dao = _get_ns_dao()
    if dao is None:
        logger.warning(
            "namespace_source_count_skipped_no_table",
            namespace_id=namespace_id,
            source_type=source_type,
            delta=delta,
        )
        return
    try:
        dao.atomic_increment(
            key={"PK": f"NS#{namespace_id}", "SK": "METADATA"},
            attribute="sourceCount",
            amount=delta,
        )
    except ClientError:
        logger.exception(
            "namespace_source_count_adjust_failed",
            namespace_id=namespace_id,
            source_type=source_type,
            delta=delta,
        )
