# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Composite Query Executor — single-vs-cross-source dispatch.

Implements the ``QueryExecutor`` protocol by routing each query to the
cheapest correct engine, per Serve LLD §2.2.1 Option D:

- **single-source, JDBC-backed** → ``SourceDBQueryExecutor`` (direct asyncpg,
  ~20-50ms p50)
- **cross-source / Glue-only / ambiguous** → ``AthenaQueryExecutor`` (federation,
  ~500-800ms p50)

The routing decision reuses the SQL Firewall's AST table extraction
(``SQLFirewall.extract_tables``) rather than re-parsing — exactly the
``unique_catalogs(...)`` heuristic the architecture note describes.

Graceful degradation (MVP safety): the direct-JDBC executor is OPTIONAL. When
it is not configured (no ``DATA_SOURCES_TABLE``, or it failed to build), the
composite delegates EVERY query to Athena — i.e. it behaves exactly like the
deployed Athena-only path. Wiring the composite therefore never regresses the
current behaviour; it only ADDS the direct-JDBC fast path when that executor is
available. Authorization is unchanged — both underlying executors run the SQL
Firewall ``validate()`` themselves, and data-level ``evaluate()`` already ran in
the caller (Tier-1 orchestrator / Tier-2 VKGTranslator) before dispatch.
"""

from __future__ import annotations

from typing import Any

import sqlglot
import sqlglot.errors
import structlog

from ..tier2.sql_firewall import SQLFirewall
from .base import QueryExecutor, QueryResult
from .db_adapters import get_adapter, is_direct_query_engine

logger = structlog.get_logger(__name__)


class CompositeQueryExecutor:
    """Routes SQL to a direct-JDBC or Athena executor by source cardinality.

    Args:
        athena_executor: Cross-source / federation executor. Always required —
            it is the fallback for every case the JDBC path cannot serve.
        source_db_executor: Optional single-source direct-JDBC executor. When
            ``None``, every query goes to Athena (deployed Athena-only behaviour).
        firewall: SQL Firewall used only for its AST ``extract_tables`` helper
            (table/catalog extraction for the routing decision). Defaults to a
            fresh instance; no authorization state is held here.
    """

    def __init__(
        self,
        athena_executor: QueryExecutor,
        source_db_executor: QueryExecutor | None = None,
        firewall: SQLFirewall | None = None,
        sources_registry=None,
    ):
        """Wire the Athena and optional JDBC executors and the routing helpers.

        Args:
            athena_executor: Cross-source / federation executor; always the fallback.
            source_db_executor: Optional single-source direct-JDBC executor.
            firewall: SQLFirewall used only for its ``extract_tables`` AST helper;
                defaults to a fresh instance.
            sources_registry: Optional registry used solely for the
                ``has_jdbc_endpoint`` routing gate.
        """
        self._athena = athena_executor
        self._source_db = source_db_executor
        self._firewall = firewall or SQLFirewall()
        # Optional registry used ONLY for the has_jdbc_endpoint gate:
        # confirm a candidate single source is direct-JDBC capable before routing
        # to the JDBC executor. NOTE: get_source() is NOT cached today, so this
        # adds one DDB GetItem on the JDBC-candidate path (single-source + explicit
        # id only; cross-source/no-id queries skip it). A cached source-metadata
        # read is a tracked follow-up if this lookup shows up in latency.
        self._sources = sources_registry

    async def execute(
        self,
        sql: str,
        *,
        namespace: str,
        data_source_id: str = "",
        params: dict[str, Any] | None = None,
        max_rows: int = 1000,
        timeout_seconds: int = 10,
    ) -> QueryResult:
        """Dispatch to the JDBC or Athena executor based on source cardinality.

        Direct JDBC (fast path) is chosen when ALL hold: a JDBC executor exists,
        an explicit single ``data_source_id`` is supplied, the SQL targets a
        single source (either fully qualified or all-bare-table), AND that
        source is a JDBC-capable DATABASE source (``has_jdbc_endpoint``).

        NL-to-SQL provides ``data_source_id`` resolved from OpenSearch class
        metadata (all retrieved hits agree on one source) — its SQL uses bare
        table names, which are unambiguous when the source is known.

        Fallback: when no data_source_id is provided but the namespace has
        exactly one DATABASE source with queryEngine=JDBC, bare-table SQL is
        routed to JDBC (covers namespaces not yet re-ingested with the
        data_source_id field in OpenSearch).
        """
        # JDBC fast path requires BOTH: a structurally single-source query (cheap
        # AST check) AND a confirmed JDBC-capable source (registry lookup — only
        # performed when the cheap check passes).
        resolved_source_id = data_source_id
        is_jdbc_candidate = self._source_db is not None and self._select_jdbc_candidate(sql, data_source_id)

        # The source record backing the JDBC decision, fetched ONCE and reused for
        # dialect resolution so the fast path does a single get_source DDB lookup.
        jdbc_source: dict[str, Any] | None = None

        # Fallback: for bare-table SQL with no explicit data_source_id, try to
        # resolve the namespace's sole DATABASE source for JDBC routing.
        # Guard: only attempt if SQL is actually bare-table — qualified
        # catalog.schema.table SQL cannot run on a single Postgres source.
        sole_source_resolved = False
        if (
            not is_jdbc_candidate
            and self._source_db is not None
            and self._sources
            and (not data_source_id or data_source_id == "default")
        ):
            catalogs_check, _ = self._catalog_analysis(sql)
            if not catalogs_check:
                sole_source, sole_source_record = await self._resolve_sole_jdbc_source(namespace)
                if sole_source:
                    resolved_source_id = sole_source
                    is_jdbc_candidate = True
                    sole_source_resolved = True
                    jdbc_source = sole_source_record

        # _resolve_sole_jdbc_source already validated queryEngine=JDBC + queryable=True
        # AND handed back the source record, so skip the redundant _fetch_jdbc_source
        # DDB round-trip for that path. Otherwise fetch (and reuse) the record once.
        if is_jdbc_candidate and not sole_source_resolved:
            jdbc_source = await self._fetch_jdbc_source(namespace, resolved_source_id)
        # A source whose engine has no direct adapter — or is withheld from the
        # product (PREVIEW_DATABASE_ENGINES: Snowflake, Oracle) — must NOT take the
        # direct route: get_adapter would hand back the PostgreSQL fail-safe and we
        # would transpile Trino->postgres and execute it against the wrong engine.
        # Athena federation speaks Trino natively and is the route these sources
        # already take (queryEngine is ATHENA for them), so this is a belt-and-braces
        # guard against a stale queryEngine value on the record.
        use_jdbc = is_jdbc_candidate and jdbc_source is not None and self._engine_has_direct_route(jdbc_source)
        if use_jdbc:
            # VKG translates to Trino dialect; re-transpile to the source engine's
            # dialect for direct JDBC. Redshift and PostgreSQL diverge on
            # constructs sqlglot rewrites differently (date arithmetic ->
            # DATEADD vs INTERVAL, TRY_CAST, type-name normalization); a
            # postgres-target transpile produces SQL Redshift rejects.
            # Dialect is derived from the ALREADY-fetched source record (no 2nd lookup).
            # sqlglot.transpile is fast (~μs per statement) — no need for run_in_executor.
            target_dialect = self._target_dialect_for_source(jdbc_source)
            try:
                transpiled_sql = sqlglot.transpile(sql, read="trino", write=target_dialect, identify=False)[0]
            except sqlglot.errors.SqlglotError as exc:
                # Catch transpilation failures specifically (parse/unsupported/optimize)
                # — a genuine bug (AttributeError, etc.) must surface, not be silently
                # rerouted to Athena. Mirrors base.inject_limit's SqlglotError handling.
                #
                # `sql` here is post-substitution (contains caller-supplied
                # dimension values — potential PII). Log length only, not the
                # statement; mirrors the orchestrator's SQL-log discipline.
                #
                # Do NOT forward the untranspiled Trino SQL to the JDBC engine:
                # Trino-only constructs run with different (silently wrong) semantics
                # on MySQL/Postgres, and a Trino `LIMIT` is invalid T-SQL. Fall back
                # to Athena, which executes Trino SQL natively — the same safe path
                # taken when no JDBC executor is configured.
                logger.warning(
                    "jdbc_trino_transpile_failed_fallback_athena",
                    target_dialect=target_dialect,
                    sql_len=len(sql),
                    error=str(exc),
                )
                logger.info("composite_dispatch", route="athena_federation", data_source_id=data_source_id or "")
                return await self._athena.execute(
                    sql,
                    namespace=namespace,
                    data_source_id=data_source_id,
                    max_rows=max_rows,
                    timeout_seconds=timeout_seconds,
                )
            logger.info(
                "composite_dispatch",
                route="jdbc_direct",
                data_source_id=resolved_source_id,
                target_dialect=target_dialect,
            )
            return await self._source_db.execute(  # type: ignore[union-attr]
                transpiled_sql,
                namespace=namespace,
                data_source_id=resolved_source_id,
                params=params,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )
        # AthenaQueryExecutor.execute() takes NO ``params`` kwarg (it never used
        # bind params — federation SQL is fully materialized). Forwarding params
        # here would TypeError, so omit it — this keeps the Athena call shape
        # bit-for-bit identical to the previously-deployed direct-Athena wiring.
        logger.info("composite_dispatch", route="athena_federation", data_source_id=data_source_id or "")
        return await self._athena.execute(
            sql,
            namespace=namespace,
            data_source_id=data_source_id,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )

    def _select_jdbc_candidate(self, sql: str, data_source_id: str) -> bool:
        """Return True if ``sql`` is a single-source candidate for the JDBC path.

        True when:
        1. an explicit, resolvable ``data_source_id`` is supplied (the JDBC
           executor needs it to locate credentials);
        2. One of:
           a) EVERY referenced table is qualified to the SAME single catalog
              (no bare/unqualified table references) — unambiguous catalog routing;
           b) ALL tables are bare/unqualified — when an explicit data_source_id is
              provided, bare tables are unambiguous (they belong to that source).
              This is the NL-to-SQL path: retrieval-based resolution provides the
              source externally.

        Mixed (some qualified to a catalog + some bare) remains ambiguous and
        routes to Athena federation.
        """
        if not data_source_id or data_source_id == "default":
            return False
        catalogs, has_bare_table = self._catalog_analysis(sql)
        # All tables qualified to exactly one catalog — unambiguous.
        # All tables bare + explicit source — unambiguous (single-source routing).
        return (len(catalogs) == 1 and not has_bare_table) or (len(catalogs) == 0 and has_bare_table)

    async def _fetch_jdbc_source(self, namespace: str, data_source_id: str) -> dict[str, Any] | None:
        """Return the source record IFF it is direct-JDBC capable AND queryable, else None.

        Source records set ``sourceType=DATABASE`` for BOTH Glue-federated and
        direct-JDBC sources — so sourceType does NOT discriminate. The authoritative
        signal is ``queryEngine`` (set by the control plane's _resolve_query_engine:
        ``JDBC`` only when a direct dialect exists — PostgreSQL/Redshift today —
        else ``ATHENA``). We additionally require ``queryable is True`` (a JDBC
        source is only queryable after federation provisioning). A Glue/S3 source,
        an Athena-engine source, or a not-yet-queryable source → None (Athena).

        Returns the fetched source dict so the caller can reuse it (e.g. to resolve
        the transpile dialect) WITHOUT a second DDB ``get_source`` round-trip on the
        JDBC fast path. With no registry wired, or any lookup error, we FAIL SAFE to
        None (never route an unconfirmed source to direct JDBC).
        """
        if self._sources is None:
            return None
        try:
            source = await self._sources.get_source(namespace, data_source_id)
        except Exception as exc:
            # Fail-safe to Athena, but keep transient registry errors (throttling,
            # network) distinguishable from a genuinely missing source in the logs.
            logger.warning(
                "jdbc_endpoint_check_failed",
                namespace=namespace,
                data_source_id=data_source_id,
                error=type(exc).__name__,
                error_msg=str(exc),
            )
            return None
        if not source:
            return None
        # queryEngine is a str-enum serialized as "JDBC"/"ATHENA"; compare uppercased.
        query_engine = str(source.get("queryEngine", "")).upper()
        if query_engine == "JDBC" and source.get("queryable") is True:
            return source
        return None

    def _engine_has_direct_route(self, source: dict[str, Any] | None) -> bool:
        """True when the source's engine may be executed over direct JDBC.

        Reads the engine from the ``configuration`` JSON blob (same place
        :meth:`_target_dialect_for_source` reads it) and defers the decision to
        ``db_adapters.is_direct_query_engine`` — so the route choice and the
        engine->dialect mapping can never disagree about which engines are enabled.
        A source with no parseable engine keeps the historical behavior (the
        PostgreSQL default), matching ``get_adapter(None)``.
        """
        if not source or self._sources is None:
            return False
        config = self._sources.parse_configuration(source)
        engine = str(config.get("engine", "")).upper()
        # Absent engine == legacy PostgreSQL source; get_adapter defaults the same way.
        return is_direct_query_engine(engine or "POSTGRESQL")

    def _target_dialect_for_source(self, source: dict[str, Any] | None) -> str:
        """Return the sqlglot write-dialect for an already-fetched JDBC source.

        VKG emits Trino SQL that we re-transpile to the source engine's dialect
        before direct JDBC execution. Engines diverge on constructs sqlglot
        rewrites per target (e.g. ``DATE_ADD`` -> ``ts + INTERVAL '1 DAY'`` for
        postgres, ``DATEADD(DAY, 1, ts)`` for redshift, ``DATE_ADD(ts, INTERVAL 1
        DAY)`` for mysql; ``LIMIT`` -> ``TOP`` for tsql), so a wrong-target
        transpile raises at execution time.

        The dialect comes from the per-engine adapter registry (the SAME
        ``get_adapter`` the direct executor uses), so the composite and executor
        never drift on the engine->dialect mapping. The source engine lives in the
        ``configuration`` JSON blob under the ``engine`` key. FAILS SAFE to
        ``"postgres"`` (the PostgreSQL adapter) for a missing source or an unknown
        engine — preserving the previous behavior for every non-mapped source.

        Takes the source dict the caller ALREADY fetched (via _fetch_jdbc_source or
        _resolve_sole_jdbc_source) so the JDBC fast path performs exactly ONE
        ``get_source`` DDB lookup, not two.
        """
        if not source or self._sources is None:
            return "postgres"
        config = self._sources.parse_configuration(source)
        engine = str(config.get("engine", "")).upper()
        return get_adapter(engine).sqlglot_dialect

    async def _resolve_sole_jdbc_source(self, namespace: str) -> tuple[str, dict[str, Any] | None]:
        """Resolve the namespace's sole JDBC source for bare-table SQL routing.

        Returns ``(source_id, source_record)`` only when exactly one DATABASE source
        exists in the namespace AND it has queryEngine=JDBC and queryable=True. Returns
        ``("", None)`` if zero, multiple, or non-JDBC sources — Athena handles it. The
        source record is returned alongside the id so the caller can reuse it for
        dialect resolution WITHOUT a second DDB lookup on the JDBC fast path.
        """
        try:
            source = await self._sources.find_sole_database_source(namespace)
        except Exception as exc:
            logger.warning(
                "sole_jdbc_resolve_failed",
                namespace=namespace,
                error=type(exc).__name__,
                error_msg=str(exc),
            )
            return "", None
        if not source:
            return "", None
        if str(source.get("queryEngine", "")).upper() != "JDBC":
            return "", None
        if source.get("queryable") is not True:
            return "", None
        source_id = source.get("sourceId", "")
        if source_id:
            logger.info(
                "composite_sole_jdbc_resolved",
                namespace=namespace,
                source_id=source_id,
            )
        return source_id, source

    def _catalog_analysis(self, sql: str) -> tuple[set[str], bool]:
        """Return (distinct catalog prefixes, any-bare-table-present) for ``sql``.

        Reuses the firewall's AST table extraction (qualified ``catalog.db.table``
        / ``db.table`` names) — never re-parses. A bare table name (no dotted
        prefix) cannot be attributed to a catalog, so its presence makes routing
        ambiguous and forces the Athena path.
        """
        catalogs: set[str] = set()
        has_bare_table = False
        for qualified in self._firewall.extract_tables(sql):
            parts = qualified.split(".")
            if len(parts) >= 2:
                catalogs.add(parts[0])
            else:
                has_bare_table = True
        return catalogs, has_bare_table

    async def health_check(self) -> dict[str, Any]:
        """Aggregate the Athena (and JDBC, if present) executor health into one dict."""
        athena_health = await self._athena.health_check()
        health: dict[str, Any] = {"status": athena_health.get("status", "unknown"), "athena": athena_health}
        if self._source_db is not None:
            health["source_db"] = await self._source_db.health_check()
        return health

    async def close(self) -> None:
        """Close both wrapped executors, logging (not raising) any close errors."""
        for executor in (self._athena, self._source_db):
            close_fn = getattr(executor, "close", None)
            if close_fn and callable(close_fn):
                try:
                    await close_fn()
                except Exception:
                    logger.warning("composite_close_error", executor=type(executor).__name__)
