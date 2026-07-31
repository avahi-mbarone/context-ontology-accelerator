# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Client for the data-catalog mock service."""

import httpx
from pydantic import BaseModel


class CatalogColumn(BaseModel):
    """A column entry from the data catalog, with type, constraints, and sample values."""

    name: str
    dataType: str
    dataLength: int | None = None
    precision: int | None = None
    scale: int | None = None
    description: str | None = None
    synonyms: list[str] = []
    constraint: str | None = None
    ordinalPosition: int | None = None
    tags: list[dict] = []
    # Sampled distinct values for low-cardinality categorical columns; emitted
    # into the induced ontology so serve's NL→SQL context can hint enum literals.
    distinctValues: list[str] = []


class CatalogConstraint(BaseModel):
    """A table constraint (e.g. primary or foreign key) reported by the data catalog."""

    constraintType: str
    columns: list[str]
    referredColumns: list[str] | None = None
    relationshipType: str | None = None


class CatalogTable(BaseModel):
    """A table from the data catalog, with its columns, constraints, and datasource."""

    id: str
    name: str
    fullyQualifiedName: str
    description: str | None = None
    synonyms: list[str] = []
    columns: list[CatalogColumn] = []
    tableConstraints: list[CatalogConstraint] | None = None
    datasourceId: str | None = None
    sourceSchema: str | None = None


class DataCatalogClient:
    """HTTP client for fetching table metadata from the data-catalog service."""

    def __init__(self, base_url: str):
        """Store the base URL of the data-catalog service.

        Args:
            base_url: Root URL of the data-catalog HTTP API.
        """
        self.base_url = base_url

    def get_table(self, table_id: str) -> CatalogTable:
        """Fetch a single table's metadata by id.

        Args:
            table_id: Catalog table id or fully qualified name.

        Returns:
            The parsed :class:`CatalogTable`.
        """
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{self.base_url}/api/v1/tables/{table_id}")
            resp.raise_for_status()
            return CatalogTable(**resp.json())

    def list_tables(self) -> list[CatalogTable]:
        """Fetch metadata for all tables in the catalog.

        Returns:
            A list of :class:`CatalogTable` for every table the catalog exposes.
        """
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{self.base_url}/api/v1/tables")
            resp.raise_for_status()
            return [CatalogTable(**t) for t in resp.json()]
