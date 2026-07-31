# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from app.fixtures_loader import load_catalogs
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{datasource_id}")
async def get_catalog_by_datasource(datasource_id: str):
    """Retrieve catalog metadata for a given datasource ID."""
    for catalog in load_catalogs():
        for source in catalog.get("sources", []):
            if source.get("datasourceId") == datasource_id:
                return source
    raise HTTPException(404, f"Datasource '{datasource_id}' not found")


@router.get("/")
async def list_catalogs():
    """List all catalog files."""
    return load_catalogs()
