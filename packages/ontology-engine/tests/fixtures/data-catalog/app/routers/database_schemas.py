# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from app.fixtures_loader import load_schemas
from app.schemas import DatabaseSchema
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/", response_model=list[DatabaseSchema])
async def list_database_schemas(database: str | None = None):
    schemas = load_schemas()
    if database:
        schemas = [
            s
            for s in schemas
            if s.database and (s.database.id == database or s.database.fullyQualifiedName == database)
        ]
    return schemas


@router.get("/{schema_id}", response_model=DatabaseSchema)
async def get_database_schema(schema_id: str):
    for s in load_schemas():
        if s.id == schema_id or s.fullyQualifiedName == schema_id:
            return s
    raise HTTPException(404, "DatabaseSchema not found")
