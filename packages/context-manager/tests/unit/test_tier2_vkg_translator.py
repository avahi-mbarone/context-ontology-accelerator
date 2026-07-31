# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Tier 2 VKG translator (orchestration layer)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from coa_common.constants import RESOURCE_PREFIX
from coa_serve.clients.base import QueryResult as ExecQueryResult
from coa_serve.clients.vkg import VKGClient, VKGResult, VKGTranslationError
from coa_serve.tier2.ontop.vkg_translator import (
    Tier2Status,
    Tier2Step,
    VKGTranslator,
)
from coa_serve.tier2.sql_firewall import FirewallResult, SQLFirewall

_TEST_VKG_ENDPOINT = "http://vkg.test-services.local:8080"


def _make_vkg_client(sql="SELECT 1", tables=None, error=None):
    client = AsyncMock(spec=VKGClient)
    if error:
        client.translate.side_effect = error
    else:
        client.translate.return_value = VKGResult(
            sql=sql,
            dialect="postgresql",
            ontology_version="v2.1",
            source_table_refs=tables or ["catalog.schema.orders"],
        )
    return client


def _make_translator(vkg_client=None, firewall=None, executor=None):
    """Create a VKGTranslator with a mocked VKG client seeded for test namespaces."""
    translator = VKGTranslator(
        vkg_endpoint=_TEST_VKG_ENDPOINT,
        firewall=firewall or _make_firewall(),
        query_executor=executor or _make_executor(),
    )
    if vkg_client:
        translator._clients["demo"] = vkg_client
        translator._clients["target-ns-123"] = vkg_client
    return translator


def _make_firewall(denied=False, reason=None):
    fw = MagicMock(spec=SQLFirewall)
    fw.evaluate.return_value = FirewallResult(
        denied=denied,
        authorized_sql="SELECT 1" if not denied else "",
        reason=reason,
    )
    return fw


def _make_executor(rows=None, error=None):
    executor = AsyncMock()
    if error:
        executor.execute.side_effect = error
    else:
        executor.execute.return_value = ExecQueryResult(
            rows=rows or [{"id": 1, "amount": 100}],
            columns=["id", "amount"],
            row_count=len(rows) if rows else 1,
            truncated=False,
            duration_ms=30,
        )
    return executor


@pytest.mark.unit
class TestVKGTranslatorSuccess:
    async def test_full_pipeline_success(self):
        vkg = _make_vkg_client(sql="SELECT id, amount FROM orders")
        fw = _make_firewall()
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg, firewall=fw, executor=executor)
        result = await translator.resolve("SELECT ?o WHERE { ?o a :Order }", namespace="demo")

        assert result.error is None
        assert result.query_result is not None
        assert result.query_result.rows == [{"id": 1, "amount": 100}]
        assert result.vkg_result is not None
        assert result.vkg_result.sql == "SELECT id, amount FROM orders"
        assert len(result.trace_steps) == 4  # vkg_translate + authorize + firewall + execute

    async def test_trace_steps_recorded(self):
        translator = _make_translator(
            vkg_client=_make_vkg_client(),
            firewall=_make_firewall(),
            executor=_make_executor(),
        )
        result = await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        step_names = [s.step for s in result.trace_steps]
        assert Tier2Step.VKG_COMPILE in step_names
        assert Tier2Step.VKG_AUTHORIZE in step_names
        assert Tier2Step.SQL_FIREWALL in step_names
        assert Tier2Step.QUERY_EXECUTE in step_names

        for step in result.trace_steps:
            assert step.status == Tier2Status.OK
            assert step.duration_ms >= 0


@pytest.mark.unit
class TestVKGTranslatorErrors:
    async def test_vkg_translation_error(self):
        vkg = _make_vkg_client(error=VKGTranslationError("VKG returned 500"))
        translator = _make_translator(
            vkg_client=vkg,
            firewall=_make_firewall(),
            executor=_make_executor(),
        )
        result = await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        assert result.error == "vkg_translation_error"
        assert result.query_result is None
        assert len(result.trace_steps) == 1
        assert result.trace_steps[0].status == Tier2Status.ERROR

    async def test_firewall_denied(self):
        translator = _make_translator(
            vkg_client=_make_vkg_client(),
            firewall=_make_firewall(denied=True, reason="Table not allowed"),
            executor=_make_executor(),
        )
        result = await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        assert result.error is not None
        assert "Firewall denied" in result.error
        assert result.query_result is None
        assert result.vkg_result is not None
        # Executor should not have been called
        assert len(result.trace_steps) == 3  # vkg_translate + authorize + firewall

    async def test_firewall_denied_is_terminal_before_datasource_resolution(self):
        # Rebase guard: a firewall DENY must stay
        # terminal BEFORE Kun's _resolve_data_source/40cd2b8 runs. Even when VKG
        # returns datasource_routing (which would drive resolution on the allowed
        # path), a deny must short-circuit so the executor is never reached.
        vkg = AsyncMock(spec=VKGClient)
        vkg.translate.return_value = VKGResult(
            sql="SELECT 1",
            dialect="postgresql",
            ontology_version="v2.1",
            source_table_refs=["restricted.public.orders"],
            datasource_routing={"orders": {"datasourceId": "pg_main"}},
        )
        executor = _make_executor()
        translator = _make_translator(
            vkg_client=vkg,
            firewall=_make_firewall(denied=True, reason="Table not allowed"),
            executor=executor,
        )
        result = await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        assert result.error is not None and "Firewall denied" in result.error
        assert result.firewall_result is not None and result.firewall_result.denied
        # The whole point: resolution/execution never ran on a deny.
        executor.execute.assert_not_awaited()
        assert len(result.trace_steps) == 3  # vkg_translate + authorize + firewall only

    async def test_execution_error(self):
        translator = _make_translator(
            vkg_client=_make_vkg_client(),
            firewall=_make_firewall(),
            executor=_make_executor(error=RuntimeError("DB connection failed")),
        )
        result = await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        assert result.error == "query_execution_error"
        assert result.query_result is None
        assert result.vkg_result is not None
        assert result.firewall_result is not None
        assert len(result.trace_steps) == 4  # vkg_translate + authorize + firewall + execute
        assert result.trace_steps[3].status == Tier2Status.ERROR

    async def test_firewall_error_exception(self):
        fw = MagicMock(spec=SQLFirewall)
        fw.evaluate.side_effect = RuntimeError("Firewall crash")

        translator = _make_translator(
            vkg_client=_make_vkg_client(),
            firewall=fw,
            executor=_make_executor(),
        )
        result = await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        assert result.error == "firewall_error"
        assert result.query_result is None


@pytest.mark.unit
class TestVKGTranslatorDataSourceInference:
    async def test_single_catalog_inferred(self):
        vkg = _make_vkg_client(tables=["mydb.public.orders", "mydb.public.customers"])
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg, firewall=_make_firewall(), executor=executor)
        await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        # Check that executor was called with inferred data_source_id
        executor.execute.assert_called_once()
        call_kwargs = executor.execute.call_args.kwargs
        assert call_kwargs["data_source_id"] == "mydb"

    async def test_multiple_catalogs_returns_empty(self):
        vkg = _make_vkg_client(tables=["db1.schema.t1", "db2.schema.t2"])
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg, firewall=_make_firewall(), executor=executor)
        await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        call_kwargs = executor.execute.call_args.kwargs
        assert call_kwargs["data_source_id"] == ""

    async def test_explicit_data_source_overrides_inference(self):
        vkg = _make_vkg_client(tables=["mydb.public.orders"])
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg, firewall=_make_firewall(), executor=executor)
        await translator.resolve(
            "SELECT ?s WHERE { ?s ?p ?o }",
            namespace="demo",
            data_source_id="override-ds",
        )

        call_kwargs = executor.execute.call_args.kwargs
        assert call_kwargs["data_source_id"] == "override-ds"

    async def test_datasource_routing_used_over_prefix_heuristic(self):
        """datasourceRouting provides deterministic resolution over prefix parsing."""
        vkg_client = AsyncMock(spec=VKGClient)
        vkg_client.translate.return_value = VKGResult(
            sql="SELECT 1",
            dialect="trino",
            ontology_version="v1",
            source_table_refs=["BIRD_PUBLIC_INCOME"],
            datasource_routing={"BIRD_PUBLIC_INCOME": {"datasourceId": "ds-abc-123", "sourceSchema": "public"}},
        )
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg_client, firewall=_make_firewall(), executor=executor)
        await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        call_kwargs = executor.execute.call_args.kwargs
        assert call_kwargs["data_source_id"] == "ds-abc-123"

    async def test_default_data_source_id_triggers_inference(self):
        """Passing "default" as data_source_id should not short-circuit inference."""
        vkg_client = AsyncMock(spec=VKGClient)
        vkg_client.translate.return_value = VKGResult(
            sql="SELECT 1",
            dialect="trino",
            ontology_version="v1",
            source_table_refs=["loan"],
            datasource_routing={"loan": {"datasourceId": "ds-from-routing", "sourceSchema": "public"}},
        )
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg_client, firewall=_make_firewall(), executor=executor)
        await translator.resolve(
            "SELECT ?s WHERE { ?s ?p ?o }",
            namespace="demo",
            data_source_id="default",
        )

        call_kwargs = executor.execute.call_args.kwargs
        assert call_kwargs["data_source_id"] == "ds-from-routing"

    async def test_empty_data_source_id_triggers_inference(self):
        """Empty string data_source_id should trigger inference."""
        vkg_client = AsyncMock(spec=VKGClient)
        vkg_client.translate.return_value = VKGResult(
            sql="SELECT 1",
            dialect="trino",
            ontology_version="v1",
            source_table_refs=["account"],
            datasource_routing={"account": {"datasourceId": "ds-inferred", "sourceSchema": "public"}},
        )
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg_client, firewall=_make_firewall(), executor=executor)
        await translator.resolve(
            "SELECT ?s WHERE { ?s ?p ?o }",
            namespace="demo",
            data_source_id="",
        )

        call_kwargs = executor.execute.call_args.kwargs
        assert call_kwargs["data_source_id"] == "ds-inferred"

    async def test_datasource_routing_multiple_sources_returns_empty(self):
        """Multiple distinct datasourceIds in routing → empty (cross-source)."""
        vkg_client = AsyncMock(spec=VKGClient)
        vkg_client.translate.return_value = VKGResult(
            sql="SELECT 1",
            dialect="trino",
            ontology_version="v1",
            source_table_refs=["T1", "T2"],
            datasource_routing={
                "T1": {"datasourceId": "ds-1", "sourceSchema": "public"},
                "T2": {"datasourceId": "ds-2", "sourceSchema": "analytics"},
            },
        )
        executor = _make_executor()

        translator = _make_translator(vkg_client=vkg_client, firewall=_make_firewall(), executor=executor)
        await translator.resolve("SELECT ?s WHERE { ?s ?p ?o }", namespace="demo")

        call_kwargs = executor.execute.call_args.kwargs
        assert call_kwargs["data_source_id"] == ""

    def test_infer_data_source_empty_means_cross_source_audit(self):
        # (c) DISPATCHER characterization, explicit audit:
        # `_infer_data_source` returning "" is the SINGLE-vs-CROSS-source signal.
        # - a single resolvable catalog/datasource id -> that id; the injected
        # CompositeQueryExecutor may then route it to direct JDBC (if the
        # has_jdbc_endpoint gate passes) or Athena
        # - "" -> cross-source / ambiguous -> always Athena federation
        translator = _make_translator()
        single = VKGResult(sql="SELECT 1", dialect="trino", ontology_version="v1", source_table_refs=["mydb.s.t"])
        multi = VKGResult(
            sql="SELECT 1", dialect="trino", ontology_version="v1", source_table_refs=["db1.s.t", "db2.s.t"]
        )
        # single resolvable catalog -> the catalog id (single-source signal)
        assert translator._infer_data_source(single) == "mydb"
        # multiple/ambiguous catalogs -> "" (cross-source signal)
        assert translator._infer_data_source(multi) == ""


@pytest.mark.unit
class TestVKGTranslatorDynamicRouting:
    """Tests for per-namespace VKG client resolution via endpoint URL rewriting."""

    async def test_resolves_namespace_to_per_namespace_endpoint(self):
        translator = VKGTranslator(
            vkg_endpoint=f"http://vkg.{RESOURCE_PREFIX}-dev-services.local:8080",
            firewall=_make_firewall(),
            query_executor=_make_executor(),
        )
        client = translator._resolve_client("ns-abc")
        assert client._base_url == f"http://vkg-ns-abc.{RESOURCE_PREFIX}-dev-services.local:8080"

    async def test_different_namespaces_resolve_different_endpoints(self):
        translator = VKGTranslator(
            vkg_endpoint=f"http://vkg.{RESOURCE_PREFIX}-dev-services.local:8080",
            firewall=_make_firewall(),
            query_executor=_make_executor(),
        )
        client_a = translator._resolve_client("ns-a")
        client_b = translator._resolve_client("ns-b")
        assert client_a is not client_b
        assert "vkg-ns-a" in client_a._base_url
        assert "vkg-ns-b" in client_b._base_url

    async def test_caches_client_per_namespace(self):
        translator = VKGTranslator(
            vkg_endpoint=f"http://vkg.{RESOURCE_PREFIX}-dev-services.local:8080",
            firewall=_make_firewall(),
            query_executor=_make_executor(),
        )
        client_1 = translator._resolve_client("ns-a")
        client_2 = translator._resolve_client("ns-a")
        assert client_1 is client_2

    async def test_invalid_endpoint_raises(self):
        translator = VKGTranslator(
            vkg_endpoint="http://localhost:8080",
            firewall=_make_firewall(),
            query_executor=_make_executor(),
        )
        with pytest.raises(ValueError, match="does not contain"):
            translator._resolve_client("ns-abc")

    async def test_resolve_routes_to_namespace_endpoint(self):
        """Full resolve() call uses the per-namespace VKG client."""
        mock_client = _make_vkg_client(sql="SELECT ns_specific")
        translator = _make_translator(vkg_client=mock_client)
        result = await translator.resolve(
            "SELECT ?s WHERE { ?s ?p ?o }",
            namespace="target-ns-123",
        )
        mock_client.translate.assert_called_once()
        assert result.vkg_result.sql == "SELECT ns_specific"
