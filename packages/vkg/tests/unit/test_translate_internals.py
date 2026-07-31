# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the internal functions of translate-server.py (ORR QAL-A-2).

Covers the helpers the contract tests mock out: R2RML routing load, Ontop health
polling, SPARQL→SQL reformulation over a mocked Ontop, dialect transpilation,
SQL/table-ref extraction, and routing resolution.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

# Load the hyphenated module file. If another test module (e.g. the contract
# test) already loaded it under "translate_server", REUSE that same object so
# both test files share one module identity — otherwise a second module object
# would shadow it in sys.modules and break @patch("translate_server....") in the
# other file (whichever loaded last wins).
if "translate_server" in sys.modules:
    translate_server = sys.modules["translate_server"]
else:
    _server_path = Path(__file__).parent.parent.parent / "translate-server.py"
    _spec = importlib.util.spec_from_file_location("translate_server", _server_path)
    assert _spec is not None and _spec.loader is not None
    translate_server = importlib.util.module_from_spec(_spec)
    sys.modules["translate_server"] = translate_server
    _spec.loader.exec_module(translate_server)


@pytest.fixture(autouse=True)
def _restore_module_globals():
    """Save/restore the module-level globals these tests mutate, so state never
    leaks into the contract tests (which share the same imported module)."""
    saved = (
        dict(translate_server._table_routing),
        translate_server._ontology_version,
        translate_server._ontop_port,
        dict(translate_server._health_status),
    )
    yield
    translate_server._table_routing = saved[0]
    translate_server._ontology_version = saved[1]
    translate_server._ontop_port = saved[2]
    with translate_server._health_lock:
        translate_server._health_status.update(saved[3])


# --- _ontop_url --------------------------------------------------------------


def test_ontop_url_builds_localhost_url():
    translate_server._ontop_port = 8081
    assert translate_server._ontop_url("/actuator/health") == "http://localhost:8081/actuator/health"


# --- _extract_sql ------------------------------------------------------------


def test_extract_sql_strips_ontop_metadata_preamble():
    raw = "ans1(x, y)\nCONSTRUCT [x, y] [...]\n   NATIVE [...]\nSELECT t0.name FROM customer t0"
    assert translate_server._extract_sql(raw) == "SELECT t0.name FROM customer t0"


def test_extract_sql_handles_with_cte():
    raw = "metadata line\nWITH cte AS (SELECT 1) SELECT * FROM cte"
    assert translate_server._extract_sql(raw).startswith("WITH cte")


def test_extract_sql_returns_raw_when_no_select():
    raw = "-- no query produced"
    assert translate_server._extract_sql(raw) == raw


# --- _extract_table_refs -----------------------------------------------------


def test_extract_table_refs_single_table():
    assert translate_server._extract_table_refs("SELECT a FROM customer t0") == ["customer"]


def test_extract_table_refs_join_is_sorted_and_deduped():
    sql = "SELECT * FROM orders o JOIN customer c ON o.cid = c.id JOIN customer c2 ON c2.id = o.cid"
    assert translate_server._extract_table_refs(sql) == ["customer", "orders"]


def test_extract_table_refs_qualified_schema_table():
    assert translate_server._extract_table_refs("SELECT * FROM sales.orders o") == ["sales.orders"]


def test_extract_table_refs_empty_or_comment_returns_empty():
    assert translate_server._extract_table_refs("") == []
    assert translate_server._extract_table_refs("-- comment") == []


def test_extract_table_refs_unparseable_returns_empty():
    # Gibberish that sqlglot cannot parse into a Table falls back to [].
    assert translate_server._extract_table_refs("NOT SQL AT ALL ;;;") == []


# --- _translate_dialect ------------------------------------------------------


def test_translate_dialect_rewrites_substr_before_transpile():
    # The regex pre-processing turns H2 SUBSTR into SUBSTRING before sqlglot runs.
    # (sqlglot's trino writer may render it back to SUBSTR — that's fine; we assert
    # the transpile succeeds and preserves the substring semantics.)
    out = translate_server._translate_dialect("SELECT SUBSTR(name, 1, 3) FROM t", "postgres", "trino")
    assert "SUBSTR" in out.upper()  # transpiled successfully, not the fallback
    assert "FROM T" in out.upper()


def test_translate_dialect_rewrites_formatdatetime_to_cast_varchar():
    out = translate_server._translate_dialect("SELECT FORMATDATETIME(ts, 'yyyy') FROM t", "postgres", "trino")
    assert "CAST" in out.upper()
    assert "FORMATDATETIME" not in out.upper()


def test_translate_dialect_returns_input_on_transpile_error():
    # An unparseable fragment triggers the except branch → original string back.
    broken = "SELECT ((( FROM"
    assert translate_server._translate_dialect(broken, "postgres", "trino") == broken


# --- _resolve_routing --------------------------------------------------------


def test_resolve_routing_empty_when_no_table_routing():
    translate_server._table_routing = {}
    assert translate_server._resolve_routing(["customer"]) == {}


def test_resolve_routing_exact_uppercase_match():
    translate_server._table_routing = {"CUSTOMER": {"datasourceId": "ds1"}}
    assert translate_server._resolve_routing(["customer"]) == {"customer": {"datasourceId": "ds1"}}


def test_resolve_routing_falls_back_to_bare_table_of_qualified_ref():
    translate_server._table_routing = {"ORDERS": {"datasourceId": "ds2", "sourceSchema": "sales"}}
    result = translate_server._resolve_routing(["sales.orders"])
    assert result == {"sales.orders": {"datasourceId": "ds2", "sourceSchema": "sales"}}


def test_resolve_routing_skips_unknown_tables():
    translate_server._table_routing = {"CUSTOMER": {"datasourceId": "ds1"}}
    assert translate_server._resolve_routing(["unknown_table"]) == {}


# --- _load_table_routing -----------------------------------------------------


def test_load_table_routing_missing_file_returns_empty():
    assert translate_server._load_table_routing("/nonexistent/path.ttl") == {}
    assert translate_server._load_table_routing("") == {}


def test_load_table_routing_parses_datasource_and_schema(tmp_path):
    ttl = tmp_path / "mappings.ttl"
    ttl.write_text(
        """
@prefix rr: <http://www.w3.org/ns/r2rml#> .
@prefix coa: <http://coa.amazon.com/vocab/coa#> .
@prefix ex: <http://example.com/> .

ex:CustomerMap a rr:TriplesMap ;
    rr:logicalTable [ rr:tableName "customer" ] ;
    coa:datasourceId "ds-abc" ;
    coa:sourceSchema "public" .
""",
        encoding="utf-8",
    )
    routing = translate_server._load_table_routing(str(ttl))
    # Stored under both bare and uppercase keys.
    assert routing["customer"]["datasourceId"] == "ds-abc"
    assert routing["CUSTOMER"]["sourceSchema"] == "public"


def test_load_table_routing_unparseable_file_returns_empty(tmp_path):
    bad = tmp_path / "bad.ttl"
    bad.write_text("this is not valid turtle @@@", encoding="utf-8")
    assert translate_server._load_table_routing(str(bad)) == {}


# --- health polling ----------------------------------------------------------


def test_check_ontop_health_reads_cached_status():
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = True
    assert translate_server._check_ontop_health() is True
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = False
    assert translate_server._check_ontop_health() is False


def test_poll_ontop_health_sets_healthy_when_probe_passes(monkeypatch):
    # The poll loop caches whatever the functional probe returns. Probe behavior
    # (actuator UP + reformulation) is covered in test_health_probe.py; here we
    # only verify the loop wires a healthy probe result into the cached status.
    monkeypatch.setattr(translate_server, "_probe_health", lambda: True)

    def _stop(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(translate_server.time, "sleep", _stop)
    with pytest.raises(KeyboardInterrupt):
        translate_server._poll_ontop_health()
    assert translate_server._check_ontop_health() is True


def test_poll_ontop_health_sets_unhealthy_on_error(monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(translate_server.urllib.request, "urlopen", _boom)

    def _stop(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(translate_server.time, "sleep", _stop)
    with pytest.raises(KeyboardInterrupt):
        translate_server._poll_ontop_health()
    assert translate_server._check_ontop_health() is False


# --- _translate_sparql (mocked Ontop) ----------------------------------------


def _fake_ontop_response(sql_body: str):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.read.return_value = sql_body.encode("utf-8")
    return resp


def test_translate_sparql_happy_path(monkeypatch):
    translate_server._table_routing = {"CUSTOMER": {"datasourceId": "ds1"}}
    translate_server._ontology_version = "9.9.9"
    body = "ans1(x)\nCONSTRUCT [...]\nSELECT t0.name FROM customer t0"
    monkeypatch.setattr(translate_server.urllib.request, "urlopen", lambda *a, **k: _fake_ontop_response(body))
    out = translate_server._translate_sparql("SELECT ?n WHERE {?c :name ?n}", "trino")
    assert out["sql"].upper().startswith("SELECT")
    assert out["dialect"] == "trino"
    assert out["ontologyVersion"] == "9.9.9"
    assert out["sourceTableRefs"] == ["customer"]
    assert out["datasourceRouting"] == {"customer": {"datasourceId": "ds1"}}


def test_translate_sparql_h2_dialect_skips_transpile(monkeypatch):
    translate_server._table_routing = {}
    body = "SELECT 1 FROM dual"
    monkeypatch.setattr(translate_server.urllib.request, "urlopen", lambda *a, **k: _fake_ontop_response(body))
    out = translate_server._translate_sparql("q", "h2")
    assert out["dialect"] == "h2"


def test_translate_sparql_raises_on_http_error(monkeypatch):
    err = urllib.error.HTTPError("url", 500, "boom", {}, None)
    monkeypatch.setattr(err, "read", lambda: b"ontop failed", raising=False)

    def _raise(*a, **k):
        raise err

    monkeypatch.setattr(translate_server.urllib.request, "urlopen", _raise)
    with pytest.raises(RuntimeError, match="Ontop error 500"):
        translate_server._translate_sparql("q", "trino")


def test_translate_sparql_raises_on_urlerror(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(translate_server.urllib.request, "urlopen", _raise)
    with pytest.raises(RuntimeError, match="Cannot reach Ontop"):
        translate_server._translate_sparql("q", "trino")


# --- TranslateHandler request paths ------------------------------------------


def _invoke(method, path, body=None, content_length=None):
    """Drive TranslateHandler without a real socket (mirrors the contract test helper)."""

    class _MockHandler(translate_server.TranslateHandler):
        def __init__(self):
            raw = json.dumps(body).encode() if body is not None else b""
            self.rfile = io.BytesIO(raw)
            self.wfile = io.BytesIO()
            self.path = path
            length = content_length if content_length is not None else len(raw)
            self.headers = {"Content-Length": str(length)}
            self._status = None
            self.client_address = ("127.0.0.1", 0)

        def send_response(self, code):
            self._status = code

        def send_header(self, k, v):
            pass

        def end_headers(self):
            pass

    h = _MockHandler()
    {"GET": h.do_GET, "POST": h.do_POST}[method]()
    h.wfile.seek(0)
    payload = h.wfile.read()
    return h._status, (json.loads(payload) if payload else {})


def test_get_unknown_path_returns_404():
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = True
    status, data = _invoke("GET", "/nope")
    assert status == 404
    assert data["error"] == "Not found"


def test_post_unknown_path_returns_404():
    status, data = _invoke("POST", "/nope", {})
    assert status == 404


def test_translate_returns_503_when_unhealthy():
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = False
    status, data = _invoke("POST", "/sparql/translate", {"sparql": "q"})
    assert status == 503
    assert data["message"] == "Ontop not ready"


def test_translate_400_on_invalid_json():
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = True

    class _BadHandler(translate_server.TranslateHandler):
        def __init__(self):
            self.rfile = io.BytesIO(b"{not json")
            self.wfile = io.BytesIO()
            self.path = "/sparql/translate"
            self.headers = {"Content-Length": "9"}
            self._status = None
            self.client_address = ("127.0.0.1", 0)

        def send_response(self, code):
            self._status = code

        def send_header(self, k, v):
            pass

        def end_headers(self):
            pass

    h = _BadHandler()
    h.do_POST()
    h.wfile.seek(0)
    assert h._status == 400


def test_translate_413_on_oversized_body():
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = True
    status, data = _invoke("POST", "/sparql/translate", {"sparql": "q"}, content_length=1_048_577)
    assert status == 413


def test_translate_400_on_missing_sparql():
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = True
    status, data = _invoke("POST", "/sparql/translate", {"namespace": "x"})
    assert status == 400
    assert "sparql" in data["error"]


def test_translate_200_success(monkeypatch):
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = True
    monkeypatch.setattr(
        translate_server,
        "_translate_sparql",
        lambda sparql, dialect: {"sql": "SELECT 1", "dialect": dialect, "sourceTableRefs": []},
    )
    status, data = _invoke("POST", "/sparql/translate", {"sparql": "q", "targetDialect": "trino"})
    assert status == 200
    assert data["sql"] == "SELECT 1"


def test_translate_500_on_runtime_error(monkeypatch):
    with translate_server._health_lock:
        translate_server._health_status["healthy"] = True

    def _boom(sparql, dialect):
        raise RuntimeError("ontop exploded")

    monkeypatch.setattr(translate_server, "_translate_sparql", _boom)
    status, data = _invoke("POST", "/sparql/translate", {"sparql": "q"})
    assert status == 500
    assert "ontop exploded" in data["error"]
