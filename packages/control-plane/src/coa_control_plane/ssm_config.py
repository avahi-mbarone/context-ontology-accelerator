# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""SSM Parameter Store helpers for SMUS configuration."""

from __future__ import annotations

import boto3


def get_smus_domain_id(ssm_prefix: str, region_name: str | None = None) -> str:
    """Read the SMUS domain ID from SSM Parameter Store.

    Args:
        ssm_prefix: SSM path prefix (e.g. ``/coa``).
        region_name: AWS region. Defaults to the SDK default chain.

    Returns:
        The SMUS domain ID string.

    Raises:
        ValueError: if the parameter is missing or empty.
    """
    param_name = f"{ssm_prefix}/smus/domain-id"
    ssm = boto3.client("ssm", region_name=region_name)
    resp = ssm.get_parameter(Name=param_name)
    value = resp.get("Parameter", {}).get("Value", "")
    if not value:
        raise ValueError(f"SMUS domain ID not found at SSM parameter: {param_name}")
    return value
