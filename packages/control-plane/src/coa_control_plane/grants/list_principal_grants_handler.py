# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""List Principal Grants handler.

GET /principals/{principalId}/grants

When principalId is the SELF_PRINCIPAL sentinel, resolves the caller's email
and groups from the authorizer context and returns all grants for the user
and their groups.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
from coa_common import sanitize_principal_key
from coa_common.dao import DynamoDBDAO, QueryParams
from coa_common.logging import setup_logging
from coa_common.response import api_response

from .grant_id import encode_grant_id

setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SELF_PRINCIPAL = "me"
"""Sentinel value for principalId that resolves to the authenticated caller."""

_CLAIM_EMAIL = "email"
_CLAIM_GROUPS = "groups"
_CLAIM_COGNITO_GROUPS = "cognito:groups"

_MAX_GROUPS = 250
"""Hard circuit-breaker on group fan-out, not an expected ceiling.

Enterprise SSO users routinely carry 100+ group
memberships (a real observed token had ~140) — a low cap here silently
truncates the group list wherever a caller's granted group happens to fall
past the cutoff, causing a principal's own grant to vanish from THIS listing
(while `coa_control_plane.authorization.handler`'s uncapped `_resolve_roles`
still enforces it correctly) with no error, no indication of an incomplete
result, and no correlation to anything the caller did. That silent split
between "what you're allowed to do" and "what you're shown you're allowed to
do" is what the old `_MAX_GROUPS = 10` produced.

250 is sized to comfortably exceed real-world group counts while still
bounding the fan-out below (see `_MAX_GROUP_QUERY_WORKERS`). If a caller ever
exceeds it, log loudly (``logger.error``, not ``warning``) rather than
truncating silently — see the log call below.
"""

_MAX_GROUP_QUERY_WORKERS = 20
"""Bound on concurrent DynamoDB queries for the group fan-out.

Each principal key (self + each group) is one PrincipalIndex GSI query;
executed sequentially, that scales request latency linearly with the
caller's group count (100+ groups would add seconds to a single page load).
Parallelizing over a small thread pool keeps latency roughly constant
(bounded by the slowest single query, not their sum) while still bounding
concurrent read load against the table — the DAO's boto3 client is safe for
concurrent use across threads.
"""

_GROUP_NAME_RE = re.compile(r"^[\w.@\-]+$")
"""Valid group name pattern — alphanumeric, dots, @, hyphens."""


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    """List all grants held by the calling principal and their groups.

    Only self-lookup is permitted: the principal id must be the ``me``
    sentinel. The caller's email and group memberships are resolved from the
    authorizer context and every matching grant is returned.

    Args:
        event: API Gateway proxy event with a ``principalId`` path parameter
            and authorizer-populated caller context.
        context: Lambda context object (unused).

    Returns:
        An API Gateway proxy response: 200 with the caller's grants, or a
        4xx/5xx error response.
    """
    path_params = event.get("pathParameters") or {}
    principal_id = path_params.get("principalId", "")

    if not principal_id:
        return api_response(400, {"message": "principalId is required"})

    # Only allow self-lookup — other users' grants require admin endpoints
    if principal_id != SELF_PRINCIPAL:
        return api_response(403, {"message": "Access denied. Use 'me' to query your own grants."})

    region = os.environ.get("AWS_REGION")
    mappings_table = os.environ.get("RESOURCE_ROLE_MAPPINGS_TABLE")

    if not region or not mappings_table:
        logger.error("missing_env_vars")
        return api_response(500, {"message": "Internal server error"})

    auth_context = event.get("requestContext", {}).get("authorizer", {})
    claims = auth_context.get("claims", {})

    email = auth_context.get(_CLAIM_EMAIL) or claims.get(_CLAIM_EMAIL, "")
    groups_str = auth_context.get(_CLAIM_GROUPS) or claims.get(_CLAIM_COGNITO_GROUPS, "")

    if not email:
        return api_response(400, {"message": "Unable to resolve caller identity"})

    # Normalize email to lowercase for consistent lookups
    email = email.strip().lower()

    principal_keys: list[str] = [f"User::{sanitize_principal_key(email)}"]

    if groups_str:
        groups_added = 0
        for group in groups_str.split(","):
            group = group.strip()
            if not group:
                continue
            if not _GROUP_NAME_RE.match(group):
                logger.warning("invalid_group_name_skipped", group=group)
                continue
            if groups_added >= _MAX_GROUPS:
                # Loud, not silent: this caller's own grant listing WILL be
                # incomplete past this point (unlike the old cap, which hit
                # real users' normal group counts and dropped their grants
                # with no signal at all). error, not warning, so this is
                # visible without needing debug-level log access.
                logger.error(
                    "group_fanout_cap_hit_grants_may_be_incomplete",
                    total_groups=groups_str.count(",") + 1,
                    max=_MAX_GROUPS,
                    email=email,
                )
                break
            principal_keys.append(f"Group::{sanitize_principal_key(group)}")
            groups_added += 1

    try:
        mappings_dao = DynamoDBDAO(mappings_table, region=region)
        seen_grant_ids: set[str] = set()
        grants: list[dict[str, Any]] = []

        def _query_principal_key(pk: str) -> list[dict[str, Any]]:
            # query_all, not query: a single query returns one 1 MB page, so a
            # principal with many grants would see an arbitrary subset of their
            # own permissions here — with no indication the list is incomplete.
            return mappings_dao.query_all(
                QueryParams(
                    key_condition="#pk = :pk",
                    expression_values={":pk": pk},
                    expression_names={"#pk": "principalKey"},
                    index_name="PrincipalIndex",
                )
            )

        # Parallelize the per-principal-key fan-out (self + every group) over a
        # small thread pool. Sequential queries scale request latency linearly
        # with the caller's group count — an enterprise SSO
        # user with 100+ group memberships would otherwise add seconds to a
        # single page load. boto3 clients are safe for concurrent use across
        # threads, so this is a plain I/O-bound fan-out, not a new concurrency
        # model for the codebase.
        worker_count = min(_MAX_GROUP_QUERY_WORKERS, len(principal_keys))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            for items in pool.map(_query_principal_key, principal_keys):
                for item in items:
                    summary = _to_grant_summary(item)
                    if summary["grantId"] not in seen_grant_ids:
                        seen_grant_ids.add(summary["grantId"])
                        grants.append(summary)

        return api_response(200, {"grants": grants})

    except Exception:
        logger.exception("list_principal_grants_error", principal_id=email)
        return api_response(500, {"message": "Internal server error"})


def _to_grant_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "grantId": encode_grant_id(item["PK"], item["SK"]),
        "namespaceId": item.get("resourceId", ""),
        "principalType": item.get("principalType", ""),
        "principalId": item.get("principalId", ""),
        "role": item.get("role", ""),
        "grantedBy": item.get("grantedBy", ""),
        "grantedAt": item.get("grantedAt", ""),
    }
    # ``is not None``, not truthiness: a declared-empty override (e.g.
    # tableAllowlist: []) is a deny-all restriction and must stay visible to
    # the principal — omitting it makes a deny-all grant indistinguishable
    # from an unrestricted one.
    for opt in ("tableAllowlist", "columnDenylist", "allowedMetrics"):
        if item.get(opt) is not None:
            summary[opt] = item[opt]
    return summary
