# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from app.fixtures_loader import load_databases
from app.schemas import Database
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/", response_model=list[Database])
async def list_databases(service: str | None = None):
    dbs = load_databases()
    if service:
        dbs = [d for d in dbs if d.service and d.service.name == service]
    return dbs


@router.get("/{database_id}", response_model=Database)
async def get_database(database_id: str):
    for d in load_databases():
        if d.id == database_id or d.fullyQualifiedName == database_id:
            return d
    raise HTTPException(404, "Database not found")
