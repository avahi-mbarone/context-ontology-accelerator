# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Custom resource — non-destructively registers an IAM role as an LF data-lake admin.

Reads the target role ARN from SSM, then GetDataLakeSettings -> append the role
to DataLakeAdmins if absent -> PutDataLakeSettings (full settings object), so
existing admins and other settings are preserved. Removes the role on Delete
(best-effort, so it never blocks stack teardown). Returns the
Provider-framework OnEventResponse shape.
"""

from __future__ import annotations

import contextlib
import re

import boto3
from botocore.exceptions import ClientError

_ssm = boto3.client("ssm")
_lf = boto3.client("lakeformation")
_sts = boto3.client("sts")

# Same-account IAM role ARN. The target becomes a Lake Formation data-lake admin,
# so it must be a role we own — validating the format + account guards against a
# misconfigured/compromised SSM parameter escalating an arbitrary principal.
_ROLE_ARN_RE = re.compile(r"^arn:aws[a-z-]*:iam::(\d{12}):role/.+")


def _target(event: dict) -> str:
    """Resolve and validate the target role ARN from the SSM parameter."""
    name = event["ResourceProperties"]["RoleArnSsmParameterName"]
    try:
        arn = _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except ClientError as e:
        raise ValueError(f"Failed to read SSM parameter {name!r}: {e}") from e
    m = _ROLE_ARN_RE.match(arn or "")
    if not m:
        raise ValueError(f"SSM parameter {name!r} is not an IAM role ARN: {arn!r}")
    try:
        account = _sts.get_caller_identity()["Account"]
    except ClientError as e:
        raise ValueError(f"Failed to retrieve AWS account id: {e}") from e
    if m.group(1) != account:
        raise ValueError(f"Refusing to register cross-account principal as LF admin: {arn!r}")
    return arn


def _apply(request_type: str, target: str) -> None:
    # Read-modify-write: preserve existing admins and all other settings.
    try:
        settings = _lf.get_data_lake_settings().get("DataLakeSettings", {})
        admins = settings.get("DataLakeAdmins", []) or []
        ids = {a.get("DataLakePrincipalIdentifier") for a in admins}
        if request_type == "Delete":
            admins = [a for a in admins if a.get("DataLakePrincipalIdentifier") != target]
        elif target not in ids:
            admins.append({"DataLakePrincipalIdentifier": target})
        settings["DataLakeAdmins"] = admins
        _lf.put_data_lake_settings(DataLakeSettings=settings)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "AccessDeniedException":
            # Bootstrap chicken-and-egg: this Lambda's role must itself be an LF
            # admin in an account that already has admins (see infra/README.md).
            raise PermissionError(f"Lambda role must be a Lake Formation data-lake admin to manage admins: {e}") from e
        raise


def handler(event: dict, context: object = None) -> dict:
    """Register or deregister the target IAM role as a Lake Formation admin.

    CloudFormation custom-resource entry point. On Create/Update, resolves and
    validates the target role ARN from SSM and appends it to the data-lake
    admins (read-modify-write, preserving existing settings). On Delete, removes
    it best-effort so an LF error never blocks stack teardown.

    Args:
        event: Custom-resource event with ``RequestType`` and
            ``ResourceProperties.RoleArnSsmParameterName``.
        context: Lambda runtime context (unused).

    Returns:
        A Provider-framework ``OnEventResponse`` dict carrying
        ``PhysicalResourceId``.
    """
    if event["RequestType"] == "Delete":
        # Best-effort: never block stack deletion on an LF error.
        with contextlib.suppress(Exception):
            _apply("Delete", _target(event))
        return {"PhysicalResourceId": event.get("PhysicalResourceId", "lf-admin")}
    target = _target(event)
    _apply(event["RequestType"], target)
    return {"PhysicalResourceId": f"lf-admin-{target}"}
