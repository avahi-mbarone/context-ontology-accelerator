# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reads discovered assets from DataZone for enrichment using SMUSClient."""

from __future__ import annotations

import json
import logging
import os

from coa_common.datazone_forms import (
    FORM_TYPE_NAME,
    deserialize_form,
)
from coa_common.domain_models import Table
from coa_common.metadata_store.smus import SMUSClient

logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def read_assets_for_datasource(domain_id: str, project_id: str, data_source_id: str) -> list[Table]:
    """Search DataZone for assets belonging to a data source and parse into Table objects."""
    if not data_source_id:
        raise ValueError("data_source_id is required for asset filtering")

    # Assets are stored with DS# prefix in their name
    ds_key = f"DS#{data_source_id}" if not data_source_id.startswith("DS#") else data_source_id

    client = SMUSClient(
        domain_id=domain_id,
        region_name=AWS_REGION,
        assume_role_arn=os.getenv("PROJECT_ACCESS_ROLE_ARN") or None,
        session_name="enrichment-reader",
    )
    tables: list[Table] = []

    logger.info(
        "Searching DataZone for assets: domain=%s project=%s datasource=%s",
        domain_id,
        project_id,
        ds_key,
    )

    next_token: str | None = None
    while True:
        try:
            result = client.search_assets(
                project_id=project_id,
                search_text=ds_key,
                max_results=50,
                next_token=next_token,
            )
        except Exception:
            logger.exception("Failed to search assets for datasource %s", data_source_id)
            raise

        logger.info("Search returned %d assets (page)", len(result.items))

        for asset in result.items:
            logger.debug("Processing asset: id=%s name=%s", asset.asset_id, asset.name)
            # Only process assets prefixed with this data source ID
            if not asset.name.startswith(f"{ds_key}:"):
                continue
            table = _parse_asset(client, asset.asset_id, asset.name, data_source_id)
            if table:
                tables.append(table)
            else:
                logger.warning("Could not parse asset %s (%s) into table", asset.asset_id, asset.name)

        next_token = result.next_token
        if not next_token:
            break

    logger.info("Read %d assets for datasource %s", len(tables), data_source_id)
    return tables


def _parse_asset(client: SMUSClient, asset_id: str, asset_name: str, data_source_id: str) -> Table | None:
    """Parse a DataZone asset into a Table object by reading its form."""
    try:
        detail = client.get_asset_forms(asset_id=asset_id)
    except Exception:
        logger.debug("Failed to get asset %s", asset_id, exc_info=True)
        return None

    forms = detail.get("formsOutput", [])
    for form in forms:
        if form.get("formName") == FORM_TYPE_NAME:
            try:
                payload = json.loads(form["content"])
            except (json.JSONDecodeError, TypeError) as e:
                logger.error("Failed to parse form content for asset %s: %s", asset_id, e)
                return None
            table = deserialize_form(payload, data_source_id=data_source_id)
            return table

    return None
