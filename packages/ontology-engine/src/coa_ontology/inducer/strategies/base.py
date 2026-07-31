# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Base class for induction strategies."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

from coa_common import sql_ident
from coa_common.bedrock_metrics import CostTracker
from coa_common.constants import VOCAB_URI
from rdflib import RDF, XSD, BNode, Graph, Literal, Namespace, URIRef

from coa_ontology.inducer.schemas import ConceptMatch
from coa_ontology.inducer.services.data_catalog import CatalogTable

log = logging.getLogger(__name__)

# R2RML namespace

RR = Namespace("http://www.w3.org/ns/r2rml#")

# SCL vocabulary for datasource provenance annotations on TriplesMaps
SCL = Namespace(VOCAB_URI)

# SQL → XSD datatype mapping (shared across strategies)
_SQL_TO_XSD = {
    "INT": XSD.integer,
    "BIGINT": XSD.long,
    "SMALLINT": XSD.short,
    "TINYINT": XSD.byte,
    "FLOAT": XSD.float,
    "DOUBLE": XSD.double,
    "DECIMAL": XSD.decimal,
    "NUMERIC": XSD.decimal,
    "VARCHAR": XSD.string,
    "TEXT": XSD.string,
    "CHAR": XSD.string,
    "STRING": XSD.string,
    "BOOLEAN": XSD.boolean,
    "DATE": XSD.date,
    "TIMESTAMP": XSD.dateTime,
    "DATETIME": XSD.dateTime,
    "TIME": XSD.time,
    "BINARY": XSD.hexBinary,
    "BLOB": XSD.hexBinary,
    "UUID": XSD.string,
}


# Column names that strongly suggest numeric content even when schema says VARCHAR.
# Used by xsd_for_column() to override VARCHAR→string when the column name implies a number.
_NUMERIC_COLUMN_PATTERNS = {
    "amount",
    "total",
    "sum",
    "count",
    "price",
    "cost",
    "revenue",
    "profit",
    "salary",
    "income",
    "balance",
    "budget",
    "spent",
    "remaining",
    "quantity",
    "rate",
    "ratio",
    "percentage",
    "pct",
    "score",
    "rating",
    "weight",
    "height",
    "width",
    "length",
    "size",
    "age",
    "duration",
    "distance",
    "consumption",
    "lat",
    "lng",
    "longitude",
    "latitude",
    "altitude",
    "elevation",
}


def xsd_for(data_type: str) -> URIRef:
    """Map a SQL data type to its XSD datatype URI.

    Args:
        data_type: SQL type name, optionally with a length/precision suffix.

    Returns:
        The mapped XSD datatype URI, defaulting to ``xsd:string``.
    """
    base = (data_type or "").split("(")[0].upper()
    return _SQL_TO_XSD.get(base, XSD.string)


def xsd_for_column(data_type: str, column_name: str) -> URIRef:
    """Determine XSD type considering both SQL type and column name semantics.

    For VARCHAR/TEXT columns whose names suggest numeric content (e.g. 'spent',
    'amount', 'consumption'), returns xsd:decimal instead of xsd:string. This
    enables Ontop to perform numeric aggregation (SUM, AVG) on these columns.
    """
    base = (data_type or "").split("(")[0].upper()
    xsd_type = _SQL_TO_XSD.get(base, XSD.string)

    # If schema says string but column name implies numeric, use decimal
    if xsd_type == XSD.string and column_name:
        col_lower = column_name.lower().strip()
        # Check exact match or suffix match (e.g. 'total_spent' ends with 'spent')
        for pattern in _NUMERIC_COLUMN_PATTERNS:
            if col_lower == pattern or col_lower.endswith(f"_{pattern}") or col_lower.startswith(f"{pattern}_"):
                return XSD.decimal
    return xsd_type


def to_pascal(s: str) -> str:
    """Convert an arbitrary string to PascalCase for use as a class name.

    Args:
        s: Input string (may contain spaces, underscores, or hyphens).

    Returns:
        The PascalCase form, or ``"Entity"`` if nothing usable remains.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9\s_\-]", "", s or "")
    return "".join(w.capitalize() for w in re.split(r"[\s_\-]+", cleaned) if w) or "Entity"


def to_camel(s: str) -> str:
    """Convert an arbitrary string to camelCase for use as a property name.

    Args:
        s: Input string (may contain spaces, underscores, or hyphens).

    Returns:
        The camelCase form derived from :func:`to_pascal`.
    """
    p = to_pascal(s)
    return p[0].lower() + p[1:] if p else p


def _annotate_triples_map(g: Graph, tmap: URIRef, table: CatalogTable) -> None:
    """Annotate a TriplesMap with datasource provenance (coa:datasourceId, coa:sourceSchema).

    These annotations are ignored by Ontop (custom predicates are transparent
    to R2RML processors) but are parsed by the VKG translation layer to route
    queries to the correct data source at execution time.
    """
    if table.datasourceId:
        g.add((tmap, SCL.datasourceId, Literal(table.datasourceId)))
    if table.sourceSchema:
        g.add((tmap, SCL.sourceSchema, Literal(table.sourceSchema)))


class InductionStrategy(ABC):
    """Abstract induction strategy.

    Each strategy takes table metadata and produces:
      - A proposal ontology graph (novel classes only)
      - A set of novel table names
      - A list of ConceptMatch results

    Each strategy also owns the R2RML mapping generation for its own
    ontology via :meth:`build_r2rml`. The default implementation
    reconstructs predicate IRIs from ``{table}_{col}`` naming which
    matches the ``table_to_ontology`` strategy's output. Strategies
    that generate class/property names via other means (e.g. LLM)
    should override :meth:`build_r2rml` to look up predicates from the
    generated graph.
    """

    @abstractmethod
    def induce(
        self,
        tables: list[CatalogTable],
        ontology_uri_prefix: str,
        config: dict,
        pipeline,
        confidence_threshold: float = 0.80,
        embedding_backend: str | None = None,
        scoring_strategy: str = "lexical",
        structural_weight: float = 0.05,
        grounding_ontology_ids: list[str] | None = None,
        grounding_mode: str = "ENHANCED",
        cost_tracker: CostTracker | None = None,
    ) -> tuple[Graph, set[str], list[ConceptMatch]]:
        """Run induction and return (proposal_graph, novel_tables, matches).

        ``grounding_ontology_ids`` restricts the embedding search to a subset
        of the namespace's loaded ontologies (e.g. user-selected foundationals
        like FIBO Agreements). When None or empty, search runs unrestricted.

        ``cost_tracker`` is an optional per-job Bedrock usage accumulator; when
        present the strategy threads it into every Bedrock seam (grounding
        rerank, LLM generate) so token/cost metrics are captured for the job.
        """
        ...

    # ── R2RML generation ─────────────────────────────────────────────

    def build_r2rml(
        self,
        ontology_uri_prefix: str,
        tables: list[CatalogTable],
        novel_tables: set[str],
        proposal_graph: Graph,
    ) -> Graph:
        """Default R2RML builder matching the ``table_to_ontology`` naming scheme.

        For each table (novel AND grounded):
          - class IRI = ``ind:<PascalCase(table)>``
          - property IRI = ``ind:<camelCase(table)>_<camelCase(col)>``

        FK columns produce Referencing Object Maps (R2RML §7.5) using
        ``rr:parentTriplesMap`` + ``rr:joinCondition``. This is the spec-standard
        mechanism for expressing JOINs and works correctly for all FK cardinalities
        including composite FKs referencing composite PKs.

        Non-FK columns produce datatype ObjectMaps with ``rr:column``.

        NOTE: ontology_uri_prefix MUST end with '#' or '/' to produce valid,
        parseable URIs. We normalize here defensively.

        SQL identifiers (``rr:tableName``, ``rr:column``, and join condition
        child/parent columns) use the **verbatim original** table/column name
        wrapped as a SQL-delimited identifier via :func:`sql_ident`. This
        preserves names exactly as they appear in the source datasource --
        spaces, mixed case, reserved words, special chars -- so the SQL Ontop
        emits references the real columns without any reverse mapping.
        Class/property IRIs keep their readable PascalCase/camelCase form.

        Strategies whose output doesn't follow this naming convention
        should override this method.
        """
        if not ontology_uri_prefix.endswith(("#", "/")):
            ontology_uri_prefix += "#"
        g = Graph()
        ns = Namespace(ontology_uri_prefix)
        g.bind("rr", RR)
        g.bind("scl", SCL)
        g.bind("ind", ns)
        g.bind("xsd", XSD)

        # Build a lookup from table name → TriplesMap URI for parentTriplesMap refs
        tmap_by_name: dict[str, URIRef] = {}
        for table in tables:
            tmap_by_name[table.name] = ns[f"TriplesMap_{to_pascal(table.name)}"]

        for table in tables:
            tmap = tmap_by_name[table.name]
            table_cls = ns[to_pascal(table.name)]

            g.add((tmap, RDF.type, RR.TriplesMap))
            _annotate_triples_map(g, tmap, table)
            lt = BNode()
            g.add((tmap, RR.logicalTable, lt))
            g.add((lt, RR.tableName, Literal(sql_ident(table.name))))

            pk_cols = []
            if table.tableConstraints:
                for tc in table.tableConstraints:
                    if tc.constraintType == "PRIMARY_KEY" and tc.columns:
                        pk_cols = tc.columns
                        break

            # Build subject URI template from all PK columns to ensure uniqueness
            # for composite PKs (e.g. {prefix}/table/{col1}/{col2}).
            # Fall back to first column, then literal "ID".
            if pk_cols:
                pk_id = "/".join(f"{{{sql_ident(c)}}}" for c in pk_cols)
            elif table.columns:
                pk_id = f"{{{sql_ident(table.columns[0].name)}}}"
            else:
                pk_id = "{ID}"
            subj = URIRef(f"{tmap}/SubjectMap")
            g.add((tmap, RR.subjectMap, subj))
            template = f"{ontology_uri_prefix}{table.name}/{pk_id}"
            g.add((subj, RR.template, Literal(template)))
            g.add((subj, RR["class"], table_cls))

            # Pre-collect composite FK constraints so we can detect when a column
            # participates in a multi-column FK (needs special handling).
            composite_fk_constraints = []
            if table.tableConstraints:
                for tc in table.tableConstraints:
                    if tc.constraintType == "FOREIGN_KEY" and tc.referredColumns and len(tc.columns) > 1:
                        composite_fk_constraints.append(tc)

            # Track which columns have already been emitted as part of a composite FK
            # to avoid emitting duplicate POMs.
            composite_fk_emitted: set[str] = set()

            for col in table.columns:
                # Skip columns already emitted as part of a composite FK POM
                if col.name in composite_fk_emitted:
                    continue

                pom = URIRef(f"{tmap}/POM_{to_pascal(col.name)}")
                g.add((tmap, RR.predicateObjectMap, pom))

                prop_uri = ns[f"{to_camel(table.name)}_{to_camel(col.name)}"]
                g.add((pom, RR.predicate, prop_uri))

                om = URIRef(f"{pom}/ObjectMap")
                g.add((pom, RR.objectMap, om))

                # Check if this column is part of a composite FK
                composite_fk = None
                for tc in composite_fk_constraints:
                    if col.name in tc.columns:
                        composite_fk = tc
                        break

                if composite_fk is not None and composite_fk.referredColumns:
                    # Composite FK: emit a single Referencing Object Map for the
                    # entire relationship, with one joinCondition per column pair.

                    # Validate: columns and referredColumns must have equal length.
                    if len(composite_fk.columns) != len(composite_fk.referredColumns):
                        log.warning(
                            "Skipping malformed composite FK on %s: columns/referredColumns length mismatch (%d vs %d)",
                            table.name,
                            len(composite_fk.columns),
                            len(composite_fk.referredColumns),
                        )
                        for c in composite_fk.columns:
                            composite_fk_emitted.add(c)
                        composite_fk_constraints.remove(composite_fk)
                        g.add((om, RR.column, Literal(sql_ident(col.name))))
                        dt = xsd_for(col.dataType)
                        g.add((om, RR.datatype, dt))
                        continue

                    # Validate: all referredColumns must reference the same target table.
                    fk_tables = {rc.split(".")[0] for rc in composite_fk.referredColumns if "." in rc}
                    if len(fk_tables) > 1:
                        log.warning(
                            "Skipping composite FK on %s: referredColumns span multiple tables %s",
                            table.name,
                            fk_tables,
                        )
                        for c in composite_fk.columns:
                            composite_fk_emitted.add(c)
                        composite_fk_constraints.remove(composite_fk)
                        g.add((om, RR.column, Literal(sql_ident(col.name))))
                        dt = xsd_for(col.dataType)
                        g.add((om, RR.datatype, dt))
                        continue

                    fk_target = composite_fk.referredColumns[0].split(".")[0]
                    parent_tmap = tmap_by_name.get(fk_target)
                    if parent_tmap is None:
                        parent_tmap = ns[f"TriplesMap_{to_pascal(fk_target)}"]

                    g.add((om, RR.parentTriplesMap, parent_tmap))
                    for child_col, ref_col in zip(composite_fk.columns, composite_fk.referredColumns, strict=True):
                        parts = ref_col.split(".")
                        parent_col = parts[-1] if len(parts) >= 2 else parts[0]
                        jc = BNode()
                        g.add((om, RR.joinCondition, jc))
                        g.add((jc, RR.child, Literal(sql_ident(child_col))))
                        g.add((jc, RR.parent, Literal(sql_ident(parent_col))))

                    # Mark all columns in this composite FK as emitted
                    for c in composite_fk.columns:
                        composite_fk_emitted.add(c)
                    # Remove from composite list to avoid re-processing
                    composite_fk_constraints.remove(composite_fk)
                    continue

                # Check for simple (single-column) FK
                is_fk = False
                simple_fk_target: str | None = None
                fk_parent_col: str | None = None
                if table.tableConstraints:
                    for tc in table.tableConstraints:
                        if (
                            tc.constraintType == "FOREIGN_KEY"
                            and len(tc.columns) == 1
                            and col.name in tc.columns
                            and tc.referredColumns
                        ):
                            is_fk = True
                            parts = tc.referredColumns[0].split(".")
                            simple_fk_target = parts[0]
                            fk_parent_col = parts[-1] if len(parts) >= 2 else None
                            break

                if is_fk and simple_fk_target and fk_parent_col:
                    # Simple FK: Referencing Object Map with single joinCondition.
                    # fk_parent_col is required — without it we cannot emit a valid
                    # joinCondition and a bare parentTriplesMap would produce a
                    # Cartesian product in Ontop (R2RML §7.5).
                    parent_tmap = tmap_by_name.get(simple_fk_target)
                    if parent_tmap is None:
                        parent_tmap = ns[f"TriplesMap_{to_pascal(simple_fk_target)}"]

                    g.add((om, RR.parentTriplesMap, parent_tmap))
                    jc = BNode()
                    g.add((om, RR.joinCondition, jc))
                    g.add((jc, RR.child, Literal(sql_ident(col.name))))
                    g.add((jc, RR.parent, Literal(sql_ident(fk_parent_col))))
                else:
                    # Non-FK: datatype ObjectMap
                    g.add((om, RR.column, Literal(sql_ident(col.name))))
                    dt = xsd_for_column(col.dataType, col.name)
                    g.add((om, RR.datatype, dt))

        return g
