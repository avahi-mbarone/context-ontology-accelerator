# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""SQL Server adapter (python-tds / pytds, pure-Python, run in a threadpool).

There is no maintained SQLAlchemy async driver for SQL Server that avoids a
native ODBC dependency. Rather than bake unixODBC + msodbcsql18 into the serve
runtime image, this adapter reuses ``python-tds`` — the SAME pure-Python driver
the discovery side already uses (``connectors/dialects.py`` ``SqlServerDialect``)
— and runs its blocking calls in ``asyncio.to_thread`` so the event loop is never
blocked.

Connection model — CONNECT-PER-QUERY (deliberate):
- pytds connections are synchronous and NOT concurrency-safe, and a shared cached
  connection creates two hazards: (a) LRU eviction could ``close()`` a socket while
  another coroutine is mid-query on it, and (b) an ``asyncio.wait_for`` query
  timeout cannot cancel the OS thread, so the abandoned thread would keep using the
  connection and a subsequent query on the same (reused) connection would interleave
  on a non-thread-safe socket → TDS protocol corruption. To avoid BOTH, each
  ``run()`` opens a FRESH pytds connection, executes, and closes it — all inside one
  ``asyncio.to_thread`` unit. There is no shared mutable connection to race on, and a
  poisoned/abandoned connection is never reused. Single-source metric lookups are
  low-QPS, so the per-query connect cost is acceptable (the same trade-off the plan
  accepted for pytds/aiomysql not using SQLAlchemy pooling).
- The cached ``ConnHandle`` is therefore just the resolved ``DBCredentials`` (no live
  socket); ``close()`` is a no-op.

Other engine-specific behavior:
- Row-limit idiom is ``SELECT TOP N`` — the base ``inject_limit`` renders the ROOT
  sqlglot ``limit`` node as ``TOP`` for the ``tsql`` dialect; this class only
  overrides ``_limit_fallback`` so a parse failure never emits a literal ``LIMIT``
  that SQL Server would reject.
- Statement timeout is enforced driver-side via pytds ``timeout`` (server aborts the
  query) plus an outer ``asyncio.wait_for`` bound.
- No ``search_path``; SQL reaching here is fully qualified (``schema.table``),
  matching the discovery connector's convention.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import structlog

from .base import ConnHandle, DBCredentials, EngineAdapter

logger = structlog.get_logger(__name__)

# Bounded connect/login timeout (seconds) so an unreachable SQL Server host can't
# hang the connect indefinitely and leak a threadpool worker.
_LOGIN_TIMEOUT_S = 15


class SqlServerAdapter(EngineAdapter):
    """Direct-JDBC adapter for Microsoft SQL Server over python-tds (connect-per-query)."""

    engine_type: ClassVar[str] = "SQLSERVER"
    sqlglot_dialect: ClassVar[str] = "tsql"
    default_port: ClassVar[int] = 1433

    async def open_connection(self, creds: DBCredentials) -> ConnHandle:
        """Return the resolved credentials as the cached handle — NO live socket.

        The actual pytds connection is opened per-query inside ``run()`` (see the
        module docstring for why a shared cached connection is unsafe here). Caching
        the immutable creds keeps the executor's cache/adapter contract unchanged
        while avoiding any shared mutable connection state.
        """
        return creds

    async def run(
        self,
        conn: ConnHandle,
        sql: str,
        params: dict[str, Any] | None,
        timeout_seconds: int,
        schema: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Open a fresh pytds connection, run the SELECT, and close it — in one thread.

        The timeout is enforced BOTH driver-side (pytds ``timeout=timeout_seconds`` so
        the server aborts the query and the worker thread returns) AND with an outer
        ``asyncio.wait_for`` bound. Because a new connection is opened and closed per
        call, an abandoned thread (if ``wait_for`` fires first) can never corrupt a
        subsequent query. Bind ``params`` are not supported on this path (pytds uses
        ``%s`` paramstyle, not the SQLAlchemy ``:name`` style the other adapters
        accept) — the serve layer always passes fully-materialized SQL, so a non-empty
        ``params`` here is a programming error, rejected loudly.
        """
        if params:
            raise ValueError(
                "SqlServerAdapter does not support bind params (pytds paramstyle differs); pass literal SQL"
            )
        creds: DBCredentials = conn

        def _connect_execute() -> tuple[list[dict[str, Any]], list[str]]:
            import pytds  # noqa: PLC0415

            # TLS: pytds encrypts the LOGIN handshake by default (enc_login_only)
            # but leaves the DATA stream plaintext unless the server REQUIRES
            # encryption OR a ``cafile`` is supplied. We deliberately pass no
            # ``cafile``: pytds only offers full-stream TLS *with* CA/hostname
            # verification, and source endpoints (RDS/managed SQL Server) commonly
            # present certs that don't chain to the container trust store — the same
            # reason base.build_ssl_context uses CERT_NONE for the other engines.
            # The security boundary is therefore credentials + VPC/SG network
            # isolation, not TLS peer-identity (matches the asyncpg/aiomysql posture;
            # see base.build_ssl_context). A future hardening step could bundle the
            # AWS RDS/SQL Server CA and pass ``cafile`` to encrypt the data channel.
            # timeout = per-query server-side abort; login_timeout bounds connect.
            connection = pytds.connect(
                server=creds.host,
                port=creds.port,
                database=creds.database,
                user=creds.username,
                password=creds.password,
                autocommit=True,
                login_timeout=_LOGIN_TIMEOUT_S,
                timeout=int(timeout_seconds),
            )
            try:
                cur = connection.cursor()
                try:
                    cur.execute(sql)
                    columns = [d[0] for d in cur.description] if cur.description else []
                    # strict=True: columns come from cur.description and each row from
                    # the same cursor, so lengths always match — strict surfaces a
                    # driver/protocol mismatch loudly instead of silently truncating.
                    rows = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()] if columns else []
                    return rows, columns
                finally:
                    cur.close()
            finally:
                connection.close()

        # Outer bound: connect + query + close together. Grace over the driver
        # timeout + login timeout so the driver's own aborts normally win the race.
        outer_timeout = float(timeout_seconds) + _LOGIN_TIMEOUT_S + 5
        return await asyncio.wait_for(asyncio.to_thread(_connect_execute), timeout=outer_timeout)

    async def close(self, conn: ConnHandle) -> None:
        """No-op — connections are opened and closed per-query inside ``run()``."""
        return None

    def _limit_fallback(self, sql: str, max_rows: int) -> str:
        """SQL Server row-cap fallback: ``SELECT TOP N`` (never a literal ``LIMIT``).

        Overrides the base hook so the shared AST logic in ``base.inject_limit``
        (which already renders the ROOT ``limit`` node as ``TOP`` for the ``tsql``
        dialect on the happy path) falls back to a TOP-based string rewrite rather
        than an engine-invalid ``LIMIT`` when sqlglot can't parse/render the SQL.
        """
        return self._top_fallback(sql, max_rows)

    @staticmethod
    def _top_fallback(sql: str, max_rows: int) -> str:
        """Inject ``TOP N`` into a leading SELECT when AST parsing fails.

        SQL Server requires ``TOP`` AFTER an optional ``DISTINCT`` /``ALL`` keyword
        (``SELECT DISTINCT TOP N ...``), not before it. This fallback only runs when
        sqlglot cannot parse the SQL — which the firewall (also sqlglot-based) would
        already have rejected upstream — so it is defensive; when the leading shape
        isn't a plain ``SELECT`` we can safely rewrite, we log and return it
        unchanged (the executor's ``max_rows`` slice still bounds what the caller
        sees) rather than emit invalid T-SQL.
        """
        stripped = sql.rstrip(";")
        lowered = stripped.lstrip()
        prefix_len = len(stripped) - len(lowered)
        upper = lowered.upper()
        if not upper.startswith("SELECT "):
            # Cannot safely inject TOP into this shape (e.g. a leading WITH CTE), so
            # the SQL goes to the server UNCAPPED and only the executor's post-fetch
            # rows[:max_rows] slice bounds the caller. Log so a reachable case (the
            # upstream sqlglot firewall should already have rejected unparseable SQL)
            # is diagnosable rather than a silent memory risk.
            logger.warning("sqlserver_top_fallback_uncapped", sql_len=len(sql), max_rows=max_rows)
            return stripped
        # Preserve a leading DISTINCT / ALL quantifier before TOP.
        after_select = lowered[7:]
        for quant in ("DISTINCT ", "ALL "):
            if after_select.upper().startswith(quant):
                q_len = len(quant)
                return f"{stripped[:prefix_len]}SELECT {after_select[:q_len]}TOP {int(max_rows)} {after_select[q_len:]}"
        return f"{stripped[:prefix_len]}SELECT TOP {int(max_rows)} {after_select}"
