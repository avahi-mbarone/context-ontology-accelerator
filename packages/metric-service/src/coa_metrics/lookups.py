# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Data source and ontology lookup implementations for metric validation.

Extracted from validator.py per review feedback — keeps the validator focused
on orchestrating checks while concrete lookup logic lives here.

Contains:
  - Base interfaces: DataSourceLookup, ColumnMetadata, OntologyLookup
  - Production: SmusCatalogDataSourceLookup (SMUS/DataZone)
  - Production: NeptuneOntologyLookup (Neptune SPARQL)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


# ── Data types ──────────────────────────────────────────────────────────


@dataclass
class ColumnMetadata:
    """Metadata for a single column in a table."""

    name: str
    data_type: str  # e.g., "varchar", "integer", "decimal", "date", "timestamp"


# ── Abstract interfaces ─────────────────────────────────────────────────


class DataSourceLookup:
    """Interface for looking up data source and table metadata.

    Implementations can query SMUS (production), DynamoDB snapshots,
    or mock data for testing.
    """

    def data_source_exists(self, data_source_id: str) -> bool:
        """Check if a data source ID exists."""
        raise NotImplementedError

    def table_exists(self, data_source_id: str, table_name: str) -> bool:
        """Check if a table exists in a data source."""
        raise NotImplementedError

    def get_table_columns(self, data_source_id: str, table_name: str) -> list[ColumnMetadata] | None:
        """Get column metadata for a table. Returns None if unavailable."""
        raise NotImplementedError

    def get_column_type(self, data_source_id: str, table_name: str, column_name: str) -> str | None:
        """Get the data type of a specific column. Returns None if not found."""
        columns = self.get_table_columns(data_source_id, table_name)
        if columns is None:
            return None
        for col in columns:
            if col.name.lower() == column_name.lower():
                return col.data_type
        return None


class OntologyLookup:
    """Interface for verifying ontology class existence in Neptune."""

    def class_exists(self, class_uri: str, namespace: str) -> bool:
        """Check if an OWL class exists in the namespace's published graph."""
        raise NotImplementedError


# ── Production: SMUS Catalog Lookup ─────────────────────────────────────


class SmusCatalogDataSourceLookup(DataSourceLookup):
    """Look up data source / table / column metadata from the SMUS catalog.

    Uses ``read_approved_catalog`` from libs/common (same function the
    ontology-induction pipeline uses). Table/column metadata lives in
    DataZone as steward-approved assets, not in DynamoDB.

    The catalog is fetched lazily (first lookup per data source) and cached
    in-memory for the Lambda invocation lifetime. Only steward-approved
    tables/columns are returned.
    """

    def __init__(
        self,
        *,
        domain_id: str,
        project_id: str,
        namespace_id: str,
        datasources_table: str,
        region: str = "us-east-1",
    ) -> None:
        """Configure the SMUS/DataZone catalog lookup and its caches.

        Args:
            domain_id: DataZone domain id owning the catalog.
            project_id: DataZone project id scoping the assets.
            namespace_id: Namespace the lookup serves.
            datasources_table: DynamoDB table mapping data sources.
            region: AWS region for catalog reads.
        """
        self._domain_id = domain_id
        self._project_id = project_id
        self._namespace_id = namespace_id
        self._datasources_table = datasources_table
        self._region = region
        self._tables_by_source: dict[str, dict[str, list[ColumnMetadata]]] = {}
        self._source_present: dict[str, bool] = {}

    def _ensure_loaded(self, data_source_id: str) -> None:
        """Fetch and index the approved catalog for a data source (once)."""
        if data_source_id in self._tables_by_source:
            return

        from coa_common.metadata_store.catalog_reader import read_approved_catalog

        tables_index: dict[str, list[ColumnMetadata]] = {}
        present = False

        try:
            catalog = read_approved_catalog(
                domain_id=self._domain_id,
                project_id=self._project_id,
                namespace_id=self._namespace_id,
                data_source_ids=[data_source_id],
                datasources_table=self._datasources_table,
                region=self._region,
            )
        except Exception as exc:
            logger.warning(
                "smus_catalog_read_failed",
                data_source_id=data_source_id,
                namespace=self._namespace_id,
                error=str(exc),
            )
            self._tables_by_source[data_source_id] = tables_index
            self._source_present[data_source_id] = False
            return

        for source in catalog.get("sources", []):
            if source.get("datasourceId") != data_source_id:
                continue
            present = True
            for db in source.get("databases", []):
                for tbl in db.get("tables", []):
                    name = tbl.get("name", "")
                    if not name:
                        continue
                    columns = [
                        ColumnMetadata(
                            name=col.get("name", ""),
                            data_type=(col.get("type") or "unknown"),
                        )
                        for col in tbl.get("columns", [])
                        if col.get("name")
                    ]
                    tables_index[name.lower()] = columns

        self._tables_by_source[data_source_id] = tables_index
        self._source_present[data_source_id] = present

    def data_source_exists(self, data_source_id: str) -> bool:
        """Return whether the data source is present in the approved catalog.

        Args:
            data_source_id: The data source id to check.

        Returns:
            True if the catalog contains the data source, else False.
        """
        self._ensure_loaded(data_source_id)
        return self._source_present.get(data_source_id, False)

    def table_exists(self, data_source_id: str, table_name: str) -> bool:
        """Return whether the named table exists in the data source's catalog.

        Args:
            data_source_id: The data source id owning the table.
            table_name: The table name (matched case-insensitively).

        Returns:
            True if the approved catalog contains the table, else False.
        """
        self._ensure_loaded(data_source_id)
        return table_name.lower() in self._tables_by_source.get(data_source_id, {})

    def get_table_columns(self, data_source_id: str, table_name: str) -> list[ColumnMetadata] | None:
        """Return the approved column metadata for a table.

        Args:
            data_source_id: The data source id owning the table.
            table_name: The table name (matched case-insensitively).

        Returns:
            The list of column metadata, or None if the source or table is
            unknown.
        """
        self._ensure_loaded(data_source_id)
        source_tables = self._tables_by_source.get(data_source_id)
        if not source_tables:
            return None
        return source_tables.get(table_name.lower())


# ── Production: Neptune Ontology Lookup ─────────────────────────────────


class NeptuneOntologyLookup(OntologyLookup):
    """Verify ontology class existence via Neptune SPARQL ASK query."""

    # Defense-in-depth: ontology concepts are user-controlled (request body).
    _SAFE_CONCEPT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[A-Za-z0-9_.:/#\-]+$")

    def __init__(self) -> None:
        """Bind the Neptune SPARQL helpers used for class-existence checks."""
        from coa_metrics.neptune_client import (
            OWL,
            RDF,
            _esc,
            _iri,
            _resolve_graph_base,
            _sparql_query,
        )

        self._iri = _iri
        self._esc = _esc
        self._sparql_query = _sparql_query
        self._resolve_graph_base = _resolve_graph_base
        self._OWL = OWL
        self._RDF = RDF

    def class_exists(self, class_uri: str, namespace: str) -> bool:
        """ASK if the class exists as an owl:Class in any graph within this namespace."""
        if not isinstance(class_uri, str) or not self._SAFE_CONCEPT_RE.match(class_uri):
            logger.warning("ontology_concept_rejected", class_uri=class_uri, namespace=namespace)
            return False
        ns_prefix = f"{self._resolve_graph_base()}/{namespace}/"
        query = f"""
        ASK {{
          GRAPH ?g {{
            {self._iri(class_uri)} {self._iri(self._RDF + "type")} {self._iri(self._OWL + "Class")} .
          }}
          FILTER(STRSTARTS(STR(?g), "{self._esc(ns_prefix)}"))
        }}
        """
        try:
            result = self._sparql_query(query)
            return result.get("boolean", False)
        except Exception as exc:
            logger.warning(
                "ontology_lookup_failed",
                class_uri=class_uri,
                namespace=namespace,
                error=str(exc),
            )
            return False  # Fail open — don't block on Neptune errors
