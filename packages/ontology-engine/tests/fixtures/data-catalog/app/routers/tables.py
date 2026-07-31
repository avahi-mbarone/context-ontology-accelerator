# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from app.fixtures_loader import load_tables
from app.schemas import Table
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/", response_model=list[Table])
async def list_tables(
    databaseSchema: str | None = None,
    database: str | None = None,
):
    tables = load_tables()
    if databaseSchema:
        tables = [
            t
            for t in tables
            if t.databaseSchema
            and (t.databaseSchema.id == databaseSchema or t.databaseSchema.fullyQualifiedName == databaseSchema)
        ]
    if database:
        tables = [t for t in tables if t.fullyQualifiedName and t.fullyQualifiedName.startswith(database)]
    return tables


@router.get("/{table_id}", response_model=Table)
async def get_table(table_id: str):
    for t in load_tables():
        if t.id == table_id or t.fullyQualifiedName == table_id:
            return t
    raise HTTPException(404, "Table not found")
