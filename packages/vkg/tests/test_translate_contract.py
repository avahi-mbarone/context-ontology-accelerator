# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Translation Interface Contract Tests

Verifies:
  - translate(sparql) -> {sql, dialect, ontologyVersion, sourceTableRefs}
    for: simple SELECT, multi-table JOIN, FILTER/OPTIONAL, aggregation
  - 503 when ontology not yet loaded
"""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

_server_path = Path(__file__).parent.parent / "translate-server.py"
_spec = importlib.util.spec_from_file_location("translate_server", _server_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Failed to load translate_server from {_server_path}")
translate_server = importlib.util.module_from_spec(_spec)
sys.modules["translate_server"] = translate_server
_spec.loader.exec_module(translate_server)

TranslateHandler = translate_server.TranslateHandler
_extract_table_refs = translate_server._extract_table_refs
_rewrite_h2_functions = translate_server._rewrite_h2_functions


def _make_handler(method, path, body=None):
    """Create a mock handler and invoke the request."""

    class MockHandler(TranslateHandler):
        def __init__(self):
            self.rfile = io.BytesIO(json.dumps(body).encode() if body else b"")
            self.wfile = io.BytesIO()
            self.path = path
            self.headers = {"Content-Length": str(len(self.rfile.getvalue()))}
            self._status = None
            self.client_address = ("127.0.0.1", 0)

        def send_response(self, code):
            self._status = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

        def log_message(self, fmt, *args):
            pass

    handler = MockHandler()
    if method == "GET":
        handler.do_GET()
    elif method == "POST":
        handler.do_POST()

    handler.wfile.seek(0)
    data = json.loads(handler.wfile.read()) if handler.wfile.getvalue() else {}
    return handler._status, data


class TestHealthEndpoint:
    @patch("translate_server._check_ontop_health", return_value=False)
    def test_503_when_ontology_not_loaded(self, mock_health):
        status, data = _make_handler("GET", "/health")
        assert status == 503
        assert data["ontologyLoaded"] is False

    @patch("translate_server._check_ontop_health", return_value=True)
    def test_200_when_ontology_loaded(self, mock_health):
        import translate_server

        translate_server._ontology_version = "1.0.0"
        status, data = _make_handler("GET", "/health")
        assert status == 200
        assert data["status"] == "healthy"
        assert data["ontologyVersion"] == "1.0.0"
        assert data["ontologyLoaded"] is True


class TestTranslateEndpoint:
    @patch("translate_server._check_ontop_health", return_value=True)
    @patch("translate_server._translate_sparql")
    def test_simple_select(self, mock_translate, mock_health):
        mock_translate.return_value = {
            "sql": "SELECT t0.customer_name FROM customer t0",
            "dialect": "postgresql",
            "ontologyVersion": "1.0.0",
            "sourceTableRefs": ["customer"],
        }
        status, data = _make_handler(
            "POST",
            "/sparql/translate",
            {
                "sparql": "SELECT ?name WHERE { ?c a :Customer ; :customerName ?name }",
                "namespace": "default",
                "targetDialect": "postgresql",
            },
        )
        assert status == 200
        assert "sql" in data
        assert "dialect" in data
        assert "ontologyVersion" in data
        assert "sourceTableRefs" in data
        assert data["dialect"] == "postgresql"
        assert data["ontologyVersion"] == "1.0.0"

    @patch("translate_server._check_ontop_health", return_value=True)
    @patch("translate_server._translate_sparql")
    def test_multi_table_join(self, mock_translate, mock_health):
        mock_translate.return_value = {
            "sql": "SELECT t0.name FROM customer t0 JOIN policy t1 ON t0.id = t1.customer_id",
            "dialect": "postgresql",
            "ontologyVersion": "1.0.0",
            "sourceTableRefs": ["customer", "policy"],
        }
        status, data = _make_handler(
            "POST",
            "/sparql/translate",
            {
                "sparql": "SELECT ?name ?policy WHERE { ?c :customerName ?name . ?p :heldBy ?c }",
                "namespace": "default",
                "targetDialect": "postgresql",
            },
        )
        assert status == 200
        assert len(data["sourceTableRefs"]) >= 2

    @patch("translate_server._check_ontop_health", return_value=True)
    @patch("translate_server._translate_sparql")
    def test_filter_optional(self, mock_translate, mock_health):
        mock_translate.return_value = {
            "sql": "SELECT t0.name FROM customer t0 WHERE t0.id > 5",
            "dialect": "postgresql",
            "ontologyVersion": "1.0.0",
            "sourceTableRefs": ["customer"],
        }
        status, data = _make_handler(
            "POST",
            "/sparql/translate",
            {
                "sparql": "SELECT ?name WHERE { ?c a :Customer ; :customerName ?name FILTER(?id > 5) }",
                "namespace": "default",
                "targetDialect": "postgresql",
            },
        )
        assert status == 200
        assert "sql" in data

    @patch("translate_server._check_ontop_health", return_value=True)
    @patch("translate_server._translate_sparql")
    def test_aggregation(self, mock_translate, mock_health):
        mock_translate.return_value = {
            "sql": "SELECT COUNT(*) FROM claim t0 GROUP BY t0.policy_id",
            "dialect": "postgresql",
            "ontologyVersion": "1.0.0",
            "sourceTableRefs": ["claim"],
        }
        status, data = _make_handler(
            "POST",
            "/sparql/translate",
            {
                "sparql": "SELECT (COUNT(?c) AS ?count) WHERE { ?c a :Claim } GROUP BY ?policy",
                "namespace": "default",
                "targetDialect": "postgresql",
            },
        )
        assert status == 200
        assert "sql" in data

    @patch("translate_server._check_ontop_health", return_value=True)
    @patch("translate_server._translate_sparql")
    def test_ontology_version_always_present(self, mock_translate, mock_health):
        mock_translate.return_value = {
            "sql": "SELECT 1",
            "dialect": "h2",
            "ontologyVersion": "2.0.0",
            "sourceTableRefs": [],
        }
        status, data = _make_handler(
            "POST",
            "/sparql/translate",
            {
                "sparql": "SELECT ?s WHERE { ?s ?p ?o }",
            },
        )
        assert status == 200
        assert "ontologyVersion" in data

    @patch("translate_server._check_ontop_health", return_value=False)
    def test_503_when_not_ready(self, mock_health):
        status, data = _make_handler(
            "POST",
            "/sparql/translate",
            {
                "sparql": "SELECT ?s WHERE { ?s ?p ?o }",
            },
        )
        assert status == 503

    @patch("translate_server._check_ontop_health", return_value=True)
    def test_400_missing_sparql(self, mock_health):
        status, data = _make_handler(
            "POST",
            "/sparql/translate",
            {
                "namespace": "test",
            },
        )
        assert status == 400
        assert "sparql" in data["error"].lower()


class TestDialectTranslation:
    """Test _translate_dialect preserves identifier quoting from Ontop."""

    # ── Reserved-word quoting (the #525 fix) ────────────────────────────

    def test_reserved_word_identifiers_stay_quoted(self):
        sql = 'SELECT "order"."date", "order"."user" FROM "order"'
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert '"order"' in result
        assert '"date"' in result
        assert '"user"' in result

    def test_non_reserved_identifiers_stay_unquoted(self):
        sql = "SELECT customer_name FROM customers"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert '"customer_name"' not in result
        assert "customer_name" in result.lower()

    def test_mixed_reserved_and_normal_identifiers(self):
        sql = 'SELECT t0."type", t0.amount FROM "table" t0 WHERE t0."status" = \'active\''
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert '"type"' in result
        assert '"table"' in result
        assert '"status"' in result
        assert '"amount"' not in result
        assert "amount" in result

    def test_quoted_identifiers_in_join(self):
        sql = 'SELECT "order"."date" FROM "order" JOIN customer ON "order".customer_id = customer.id'
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert '"order"' in result
        assert '"date"' in result
        assert '"customer_id"' not in result

    def test_unquoted_reserved_word_gets_quoted(self):
        sql = 'SELECT order."date", order."user" FROM order'
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert '"order"' in result
        assert '"date"' in result
        assert '"user"' in result

    # ── H2 function rewrites ────────────────────────────────────────────

    def test_formatdatetime_rewritten_to_cast(self):
        sql = "SELECT FORMATDATETIME(created_at, 'yyyy-MM-dd') FROM events"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()

    def test_replace_formatdatetime_rewritten(self):
        sql = "SELECT REPLACE(FORMATDATETIME(ts, 'yyyy-MM-dd'), '-', '/') FROM events"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()

    def test_substr_rewritten_for_target_dialect(self):
        # H2 SUBSTR → standard SUBSTRING → sqlglot picks target's preferred form.
        # Trino uses SUBSTR; Postgres uses SUBSTRING.
        sql = "SELECT SUBSTR(name, 1, 3) FROM customers"
        trino_result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "SUBSTR" in trino_result.upper()

        pg_result = translate_server._translate_dialect(sql, "postgres", "postgres")
        assert "SUBSTRING" in pg_result.upper()

    def test_nested_formatdatetime_calls(self):
        """Nested FORMATDATETIME calls should be handled by AST traversal."""
        sql = "SELECT CONCAT(FORMATDATETIME(start_date, 'yyyy'), FORMATDATETIME(end_date, 'yyyy')) FROM ranges"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        # Both calls should be rewritten to CAST
        assert result.upper().count("CAST") >= 2

    def test_formatdatetime_with_complex_first_arg(self):
        """FORMATDATETIME with expression as first argument (not just column name)."""
        sql = "SELECT FORMATDATETIME(DATEADD('day', 1, created_at), 'yyyy-MM-dd') FROM events"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()

    def test_formatdatetime_in_where_clause(self):
        """FORMATDATETIME can appear in WHERE clause, not just SELECT."""
        sql = "SELECT id FROM events WHERE FORMATDATETIME(created_at, 'yyyy-MM-dd') = '2024-01-01'"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()

    def test_multiple_h2_functions_in_same_query(self):
        """Multiple H2-specific functions in the same query."""
        sql = "SELECT SUBSTR(name, 1, 5), FORMATDATETIME(created_at, 'yyyy') FROM events"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        # SUBSTR should be converted to SUBSTRING/SUBSTR depending on dialect
        assert "SUBSTR" in result.upper() or "SUBSTRING" in result.upper()
        assert "CAST" in result.upper()

    def test_formatdatetime_with_different_pattern_formats(self):
        """FORMATDATETIME should be rewritten regardless of pattern format."""
        patterns = [
            "SELECT FORMATDATETIME(d, 'yyyy-MM-dd') FROM t",
            "SELECT FORMATDATETIME(d, 'dd/MM/yyyy HH:mm:ss') FROM t",
            "SELECT FORMATDATETIME(d, 'yyyyMMdd') FROM t",
        ]
        for sql in patterns:
            result = translate_server._translate_dialect(sql, "postgres", "trino")
            assert "FORMATDATETIME" not in result.upper(), f"Failed for pattern: {sql}"
            assert "CAST" in result.upper(), f"No CAST found for: {sql}"

    # ── Fallback behavior ───────────────────────────────────────────────

    def test_transpile_attempts_best_effort_on_unusual_input(self):
        """sqlglot will attempt to parse/transpile even unusual input."""
        sql = "NOT VALID SQL {{{"
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        # sqlglot does its best — result may differ from input but won't raise
        assert isinstance(result, str)
        assert len(result) > 0

    # ── Realistic Ontop output ──────────────────────────────────────────

    def test_typical_ontop_output_with_aliases(self):
        """Ontop produces SQL with table aliases like t0, t1 and quoted reserved words."""
        sql = (
            'SELECT t0."user", t0.claim_id, t1."date" '
            'FROM "order" t0 '
            "JOIN claims t1 ON t0.id = t1.order_id "
            "WHERE t0.amount > 100"
        )
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert '"user"' in result
        assert '"date"' in result
        assert '"order"' in result
        assert "claim_id" in result
        assert '"claim_id"' not in result


class TestH2FunctionRewrite:
    """Test _rewrite_h2_functions AST-based transformation."""

    def test_formatdatetime_basic(self):
        sql = "SELECT FORMATDATETIME(created_at, 'yyyy-MM-dd') FROM events"
        result = _rewrite_h2_functions(sql)
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()
        assert "VARCHAR" in result.upper()

    def test_formatdatetime_nested_in_replace(self):
        """Nested FORMATDATETIME inside REPLACE should be rewritten."""
        sql = "SELECT REPLACE(FORMATDATETIME(ts, 'yyyy-MM-dd'), '-', '/') FROM events"
        result = _rewrite_h2_functions(sql)
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()
        assert "REPLACE" in result.upper()

    def test_multiple_formatdatetime_same_query(self):
        """Multiple FORMATDATETIME calls should all be rewritten."""
        sql = "SELECT FORMATDATETIME(start_dt, 'yyyy'), FORMATDATETIME(end_dt, 'MM-dd') FROM ranges"
        result = _rewrite_h2_functions(sql)
        assert "FORMATDATETIME" not in result.upper()
        assert result.upper().count("CAST") == 2

    def test_formatdatetime_with_complex_expression(self):
        """FORMATDATETIME with non-trivial first argument."""
        sql = "SELECT FORMATDATETIME(t0.created_at + INTERVAL '1' DAY, 'yyyy-MM-dd') FROM t0"
        result = _rewrite_h2_functions(sql)
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()

    def test_substr_survives_rewrite(self):
        """SUBSTR is handled natively by sqlglot's parser (as exp.Substring),
        not our Anonymous branch. The rewrite pass leaves it intact for the
        downstream transpile to normalize.
        """
        sql = "SELECT SUBSTR(name, 1, 3) FROM customers"
        result = _rewrite_h2_functions(sql)
        assert "SUBSTR" in result.upper() or "SUBSTRING" in result.upper()

    def test_no_h2_functions_unchanged(self):
        """SQL without H2 functions should pass through unchanged."""
        sql = "SELECT id, name FROM customers WHERE status = 'active'"
        result = _rewrite_h2_functions(sql)
        assert "SELECT" in result.upper()
        assert "FROM" in result.upper()
        assert "customers" in result.lower()

    def test_preserves_quoted_identifiers(self):
        """Quoted identifiers should be preserved during rewrite."""
        sql = 'SELECT FORMATDATETIME("order"."date", \'yyyy\') FROM "order"'
        result = _rewrite_h2_functions(sql)
        assert '"order"' in result
        assert '"date"' in result
        assert "FORMATDATETIME" not in result.upper()

    def test_formatdatetime_no_args_preserved(self):
        """Malformed FORMATDATETIME() with no arguments must NOT be dropped.

        Regression guard: an earlier version returned ``None`` from the AST
        transform when expressions were empty, which sqlglot interprets as
        "delete this node." That silently mangled the SQL. The node must
        pass through unchanged instead.
        """
        sql = "SELECT FORMATDATETIME() FROM events"
        result = _rewrite_h2_functions(sql)
        # The call is preserved (not deleted from the SELECT list).
        assert "FORMATDATETIME" in result.upper()


# NOTE: SUBSTR() empty-args behaviour lives in sqlglot's parser (`exp.Substring`),
# not in our Anonymous branch. Any regression there is on sqlglot, not this
# module — see the docstring of `_rewrite_h2_functions` for the SUBSTR note.


class TestH2FunctionRewriteErrorHandling:
    """Pin the parse-error and implementation-error contracts.

    On a sqlglot parse failure the rewrite returns ``sql`` unchanged — the
    prior regex fallback couldn't match nested calls like
    ``FORMATDATETIME(DATEADD(..., ...))`` anyway (``[^,]+`` stopped at the
    first comma), so keeping it would advertise safety that isn't there.
    Only ``SqlglotError`` is caught; any other exception surfaces so bugs
    in the transform callback fail loudly instead of degrading silently.
    """

    def test_ast_parse_failure_returns_sql_unchanged(self):
        """When sqlglot raises SqlglotError, the rewrite is a no-op."""
        import sqlglot as _sqlglot

        sql = "SELECT FORMATDATETIME(t.d, 'yyyy') FROM t"

        with patch.object(
            translate_server.sqlglot,
            "parse_one",
            side_effect=_sqlglot.errors.SqlglotError("simulated parse failure"),
        ):
            result = _rewrite_h2_functions(sql)

        # No rewrite applied — the caller (_translate_dialect) gets the
        # original SQL back and can still attempt transpile.
        assert result == sql

    def test_unparseable_input_returned_unchanged(self):
        """Structurally-broken SQL must survive the rewrite untouched.

        Regression guard: an earlier version parsed with
        ``error_level=IGNORE``, which silently reconstructed a mangled AST
        from broken input (``"SELECT ((( FROM"`` became
        ``"SELECT (((SELECT * FROM )))"``). That defeats the
        ``_translate_dialect`` contract of "return input unchanged on
        transpile error." Real ``ParseError`` now flows through the
        SqlglotError catch and the input is returned verbatim.
        """
        broken = "SELECT ((( FROM"
        assert _rewrite_h2_functions(broken) == broken

    def test_transform_implementation_bug_propagates(self):
        """Non-parse errors (impl bugs) MUST propagate, not be swallowed.

        The earlier ``except Exception`` swallowed AttributeError/IndexError
        from the transform callback itself — masking real bugs by silently
        degrading to regex. This test pins the narrower exception contract:
        only ``SqlglotError`` is caught; everything else surfaces.
        """
        import sqlglot.expressions as _exp

        def _boom(*_args, **_kwargs):
            raise AttributeError("simulated transform bug")

        with (
            patch.object(_exp.Expression, "transform", _boom),
            pytest.raises(AttributeError, match="simulated transform bug"),
        ):
            _rewrite_h2_functions("SELECT FORMATDATETIME(x, 'yyyy') FROM t")


class TestEndToEndH2Translation:
    """End-to-end tests simulating realistic Ontop output with H2 functions."""

    def test_realistic_ontop_query_with_formatdatetime(self):
        """Simulate a typical Ontop-generated query with FORMATDATETIME."""
        sql = """
        SELECT t0."order_id",
               FORMATDATETIME(t0."order_date", 'yyyy-MM-dd') AS formatted_date,
               t0.customer_name
        FROM "order" t0
        WHERE t0.status = 'active'
        """
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()
        assert '"order"' in result
        assert '"order_date"' in result or "order_date" in result.lower()

    def test_complex_nested_h2_functions(self):
        """Multiple levels of nesting with H2 functions."""
        sql = """
        SELECT
            CONCAT(
                SUBSTR(customer_name, 1, 10),
                ' - ',
                FORMATDATETIME(created_at, 'yyyy')
            ) AS display_name
        FROM customers
        """
        result = translate_server._translate_dialect(sql, "postgres", "trino")
        assert "FORMATDATETIME" not in result.upper()
        assert "CAST" in result.upper()
        # SUBSTR should be converted to standard form
        assert "SUBSTRING" in result.upper() or "SUBSTR" in result.upper()


class TestExtractTableRefs:
    def test_single_table(self):
        assert "customer" in _extract_table_refs("SELECT * FROM customer")

    def test_join(self):
        refs = _extract_table_refs("SELECT * FROM customer JOIN policy ON 1=1")
        assert "customer" in refs
        assert "policy" in refs

    def test_no_tables(self):
        assert _extract_table_refs("SELECT 1") == []


class TestPython39Compatibility:
    """``translate-server.py`` must import under the CONTAINER's Python, not the repo's.

    The Dockerfile installs AL2023's system ``python3`` (3.9) and the entrypoint
    runs the server with it, while the rest of the repo targets 3.12. A PEP 604
    annotation (``dict[str, Any] | None``) without ``from __future__ import
    annotations`` is evaluated at import time and raises TypeError on 3.9, so the
    container dies before serving /health — invisible to any test running on 3.12.
    """

    def test_module_has_future_annotations_import(self):
        """Guards PEP 604 / PEP 585 annotations against the 3.9 runtime."""
        source = _server_path.read_text()
        assert "from __future__ import annotations" in source, (
            "translate-server.py runs on Python 3.9 in the container; "
            "`from __future__ import annotations` is required or PEP 604 "
            "annotations raise TypeError at import and kill the server."
        )

    def test_compiles_under_python39_grammar(self):
        """Syntax must be valid for the container interpreter's feature set."""
        import ast

        tree = ast.parse(_server_path.read_text())
        # match statements (3.10+) and PEP 695 type params (3.12+) would not
        # parse on 3.9 even with the __future__ import.
        for node in ast.walk(tree):
            assert type(node).__name__ != "Match", "match statement requires Python 3.10+"
            assert not getattr(node, "type_params", None), "PEP 695 type params require Python 3.12+"
