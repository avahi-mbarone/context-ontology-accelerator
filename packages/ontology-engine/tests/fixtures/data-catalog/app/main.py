# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from app.routers import catalogs, database_schemas, databases, tables
from fastapi import FastAPI

app = FastAPI(
    title="Data Catalog (Mock)",
    description=(
        "Mock data catalog service with OpenMetadata-compatible entity model. Serves JSON fixtures for development."
    ),
    version="0.1.0",
)

app.include_router(catalogs.router, prefix="/api/v1/catalogs", tags=["catalogs"])
app.include_router(databases.router, prefix="/api/v1/databases", tags=["databases"])
app.include_router(database_schemas.router, prefix="/api/v1/databaseSchemas", tags=["databaseSchemas"])
app.include_router(tables.router, prefix="/api/v1/tables", tags=["tables"])


@app.get("/health")
async def health():
    return {"status": "ok"}
