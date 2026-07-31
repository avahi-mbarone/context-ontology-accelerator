# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Tier 1 MetricResolver — in-memory metric cache.

Tests cover:
- Index building from seed data
- Exact name matching (case-insensitive substring)
- Synonym matching (word-boundary regex)
- Multi-metric detection
- Namespace filtering
- Lookup by ID
- list_all() compact summaries
- Background refresh lifecycle
- Neptune load (mocked)
- match() exact-then-fuzzy interface
- Fuzzy near-miss matching + dimension substitution (branch additions)
"""

from __future__ import annotations

import pytest
from coa_common.constants import URN_PREFIX
from coa_serve.tier1.metric_resolver import (
    MetricDefinition,
    MetricResolver,
)

from .conftest import SEED_METRICS_ALL

_SENTINEL = object()


def _make_resolver(seed=_SENTINEL) -> MetricResolver:
    """Create a MetricResolver with seed data."""
    if seed is _SENTINEL:
        return MetricResolver(seed=SEED_METRICS_ALL)
    return MetricResolver(seed=seed)


@pytest.mark.unit
class TestMetricResolverIndexBuilding:
    async def test_load_builds_indexes(self):
        resolver = _make_resolver()

        assert resolver.loaded
        assert len(resolver._snapshot.by_id) == 4
        assert "m-revenue" in resolver._snapshot.by_id
        assert "m-cost" in resolver._snapshot.by_id
        assert "m-claims" in resolver._snapshot.by_id
        assert "m-premium" in resolver._snapshot.by_id

    async def test_by_name_index_is_lowercase(self):
        resolver = _make_resolver()

        assert "total_revenue" in resolver._snapshot.by_name
        assert "claims_count" in resolver._snapshot.by_name
        assert "total_premium" in resolver._snapshot.by_name

    async def test_by_synonym_index_is_lowercase(self):
        resolver = _make_resolver()

        assert "revenue" in resolver._snapshot.by_synonym
        assert "sales total" in resolver._snapshot.by_synonym
        assert "number of claims" in resolver._snapshot.by_synonym
        assert "premium amount" in resolver._snapshot.by_synonym

    async def test_by_namespace_index(self):
        resolver = _make_resolver()

        assert len(resolver._snapshot.by_namespace["finance"]) == 2
        assert len(resolver._snapshot.by_namespace["insurance"]) == 2

    async def test_empty_seed_produces_empty_indexes(self):
        resolver = _make_resolver(seed=[])

        assert resolver.loaded
        assert len(resolver._snapshot.by_id) == 0

    async def test_items_missing_id_skipped(self):
        resolver = _make_resolver(seed=[{"name": "test"}])
        assert len(resolver._snapshot.by_id) == 0

    async def test_items_missing_name_skipped(self):
        resolver = _make_resolver(seed=[{"metric_id": "m1"}])
        assert len(resolver._snapshot.by_id) == 0


@pytest.mark.unit
class TestExactNameMatch:
    async def test_exact_name_substring_match(self):
        resolver = _make_resolver()

        result = resolver.exact_name_synonym_match("what is the total_revenue?", "finance")
        assert result.found
        assert result.metric_name == "total_revenue"
        assert result.metric_id == "m-revenue"
        assert result.match_source == "name"
        assert result.match_count == 1

    async def test_name_match_case_insensitive(self):
        resolver = _make_resolver()

        result = resolver.exact_name_synonym_match("What is TOTAL_REVENUE?", "finance")
        assert result.found
        assert result.metric_name == "total_revenue"

    async def test_name_match_filters_by_namespace(self):
        resolver = _make_resolver()

        # total_revenue is in "finance" namespace, not "insurance"
        result = resolver.exact_name_synonym_match("total_revenue", "insurance")
        assert not result.found or result.metric_name != "total_revenue"

    async def test_name_no_match(self):
        resolver = _make_resolver()

        result = resolver.exact_name_synonym_match("what is the churn rate?", "finance")
        assert not result.found
        assert result.match_count == 0


@pytest.mark.unit
class TestSynonymMatch:
    async def test_synonym_word_boundary_match(self):
        resolver = _make_resolver()

        result = resolver.exact_name_synonym_match("show me the revenue by region", "finance")
        assert result.found
        assert result.metric_name == "total_revenue"
        assert result.match_source == "synonym"

    async def test_synonym_multi_word_match(self):
        resolver = _make_resolver()

        result = resolver.exact_name_synonym_match("what is the number of claims?", "insurance")
        assert result.found
        assert result.metric_name == "claims_count"
        assert result.match_source == "synonym"

    async def test_synonym_case_insensitive(self):
        resolver = _make_resolver()

        result = resolver.exact_name_synonym_match("Show me Revenue by quarter", "finance")
        assert result.found
        assert result.metric_name == "total_revenue"

    async def test_synonym_no_partial_match(self):
        """Synonym 'revenue' should not match 'irrevenued' (word boundary)."""
        resolver = _make_resolver()

        # "revenues" contains "revenue" as substring but not at word boundary
        # Actually "revenue" IS at a word boundary in "revenues" since \b matches between word chars
        # Let's test with something that genuinely fails word boundary
        result = resolver.exact_name_synonym_match("prevenued metrics", "finance")
        assert not result.found


@pytest.mark.unit
class TestMultiMetricDetection:
    async def test_single_metric_match_count_1(self):
        resolver = _make_resolver()

        result = resolver.exact_name_synonym_match("what is the claims_count?", "insurance")
        assert result.found
        assert result.match_count == 1

    async def test_multi_metric_match_count_gt_1(self):
        resolver = _make_resolver()

        # Both claims_count and total_premium are in insurance namespace
        result = resolver.exact_name_synonym_match("compare claims_count and total_premium", "insurance")
        assert result.found
        assert result.match_count == 2

    async def test_multi_metric_via_synonyms(self):
        resolver = _make_resolver()

        # "claim count" matches claims_count synonym, "premium amount" matches total_premium synonym
        result = resolver.exact_name_synonym_match("show claim count vs premium amount", "insurance")
        assert result.found
        assert result.match_count == 2


@pytest.mark.unit
class TestLookup:
    async def test_lookup_by_id(self):
        resolver = _make_resolver()

        defn = resolver.lookup("m-revenue")
        assert defn is not None
        assert defn.name == "total_revenue"
        assert defn.namespace == "finance"
        assert defn.sql_template == "SELECT SUM(amount) AS total_revenue FROM orders"

    async def test_lookup_miss(self):
        resolver = _make_resolver()

        defn = resolver.lookup("nonexistent")
        assert defn is None


@pytest.mark.unit
class TestListAll:
    async def test_list_all_for_namespace(self):
        resolver = _make_resolver()

        summaries = resolver.list_all("insurance")
        assert len(summaries) == 2
        names = {s["name"] for s in summaries}
        assert names == {"claims_count", "total_premium"}

    async def test_list_all_compact_summary_format(self):
        resolver = _make_resolver()

        summaries = resolver.list_all("finance")
        assert len(summaries) == 2
        s = summaries[0]
        assert "metric_id" in s
        assert "name" in s
        assert "display_name" in s
        assert "description" in s
        assert "dimensions" in s

    async def test_list_all_empty_namespace(self):
        resolver = _make_resolver()

        summaries = resolver.list_all("nonexistent")
        assert summaries == []

    async def test_list_all_case_insensitive(self):
        resolver = _make_resolver()

        summaries = resolver.list_all("Finance")
        assert len(summaries) == 2


@pytest.mark.unit
class TestStartStop:
    async def test_start_is_noop(self):
        resolver = _make_resolver()
        await resolver.start()
        assert resolver.loaded

    async def test_stop_is_noop(self):
        resolver = _make_resolver()
        await resolver.stop()
        assert resolver.loaded


@pytest.mark.unit
class TestLegacyMatchInterface:
    async def test_legacy_match_delegates_to_exact_match(self):
        resolver = _make_resolver()

        result = await resolver.match("show me the total_revenue", "finance")
        assert result.found
        assert result.metric_name == "total_revenue"

        result = await resolver.match("total_revenue", "finance")
        assert resolver.loaded
        assert result.found


@pytest.mark.unit
class TestMetricDefinition:
    def test_compact_summary(self):
        defn = MetricDefinition(
            metric_id="m1",
            name="test_metric",
            display_name="Test Metric",
            description="A test",
            dimensions=["dim1"],
        )
        summary = defn.compact_summary
        assert summary["metric_id"] == "m1"
        assert summary["name"] == "test_metric"
        assert summary["display_name"] == "Test Metric"
        assert summary["description"] == "A test"
        assert summary["dimensions"] == ["dim1"]

    def test_compact_summary_uses_name_as_display_name_fallback(self):
        defn = MetricDefinition(metric_id="m1", name="my_metric")
        summary = defn.compact_summary
        assert summary["display_name"] == "my_metric"


@pytest.mark.unit
class TestNeptuneRefresh:
    """Tests for loading metrics from Neptune via SPARQL."""

    async def test_refresh_from_neptune_builds_indexes(self):
        from unittest.mock import AsyncMock

        mock_neptune = AsyncMock()
        mock_neptune.query.return_value = [
            {
                "name": "catastrophe_count",
                "description": "Count of catastrophes",
                "expressionDialects": ('[{"dialect":"POSTGRESQL","expression":"SELECT COUNT(*) FROM catastrophe"}]'),
                "aiContext": (
                    '{"synonyms":["how many catastrophes","CAT count"],"instructions":"Use for catastrophe counts."}'
                ),
                "dataSourceId": "ds-123",
                "namespace": "insurance",
            },
            {
                "name": "total_premium",
                "description": "Total premium",
                "expressionDialects": ('[{"dialect":"POSTGRESQL","expression":"SELECT SUM(amount) FROM premium"}]'),
                "namespace": "insurance",
            },
        ]

        resolver = MetricResolver(neptune_client=mock_neptune)
        await resolver.start()

        assert resolver.loaded
        assert len(resolver._snapshot.by_id) == 2
        assert "catastrophe_count" in resolver._snapshot.by_name
        assert "total_premium" in resolver._snapshot.by_name
        assert "how many catastrophes" in resolver._snapshot.by_synonym
        assert "cat count" in resolver._snapshot.by_synonym

    async def test_refresh_empty_neptune(self):
        from unittest.mock import AsyncMock

        mock_neptune = AsyncMock()
        mock_neptune.query.return_value = []

        resolver = MetricResolver(neptune_client=mock_neptune)
        await resolver.start()

        assert resolver.loaded
        assert len(resolver._snapshot.by_id) == 0

    async def test_refresh_neptune_error_doesnt_crash(self):
        from unittest.mock import AsyncMock

        mock_neptune = AsyncMock()
        mock_neptune.query.side_effect = RuntimeError("Neptune unreachable")

        resolver = MetricResolver(neptune_client=mock_neptune)
        await resolver.start()

        # Should not raise, resolver stays empty
        assert len(resolver._snapshot.by_id) == 0

    async def test_synonym_match_after_neptune_load(self):
        from unittest.mock import AsyncMock

        mock_neptune = AsyncMock()
        mock_neptune.query.return_value = [
            {
                "name": "catastrophe_count",
                "aiContext": '{"synonyms":["how many catastrophes"]}',
                "namespace": "insurance",
            },
        ]

        resolver = MetricResolver(neptune_client=mock_neptune)
        await resolver.start()

        result = resolver.exact_name_synonym_match("how many catastrophes are there?", "insurance")
        assert result.found
        assert result.metric_name == "catastrophe_count"
        assert result.match_source == "synonym"

    async def test_seed_fallback_without_neptune(self):
        """When no neptune_client provided, seed data is used."""
        resolver = MetricResolver(seed=SEED_METRICS_ALL)
        assert resolver.loaded
        assert len(resolver._snapshot.by_id) == 4

    async def test_match_lazy_loads_when_snapshot_empty(self):
        """match() must lazily refresh from Neptune when the snapshot is empty.

        start() is fire-and-forget at init, so the first request on a fresh
        serve instance can race ahead of the initial refresh and match an EMPTY
        index (Tier-1 false miss). match() guards against this by refreshing
        on-demand when the snapshot has no metrics and a Neptune client exists.
        """
        from unittest.mock import AsyncMock

        mock_neptune = AsyncMock()
        mock_neptune.query.return_value = [
            {
                "name": "total_claims",
                "aiContext": '{"synonyms":["claim count"]}',
                "namespace": "insurance",
            },
        ]
        # Construct the resolver but DO NOT call start() — simulates a request
        # arriving before the background load completes (empty snapshot).
        resolver = MetricResolver(neptune_client=mock_neptune)
        assert len(resolver._snapshot.by_id) == 0

        m = await resolver.match("how many total_claims are there?", "insurance")
        # The lazy-load kicked a refresh, so the match now succeeds.
        assert mock_neptune.query.await_count >= 1
        assert m.found
        assert m.metric_name == "total_claims"

    async def test_match_does_not_reload_when_snapshot_populated(self):
        """Once the snapshot is populated, match() must NOT re-query Neptune
        (the lazy-load predicate is false after the first load)."""
        from unittest.mock import AsyncMock

        mock_neptune = AsyncMock()
        mock_neptune.query.return_value = [
            {"name": "total_claims", "namespace": "insurance"},
        ]
        resolver = MetricResolver(neptune_client=mock_neptune)
        await resolver.start()  # one refresh
        calls_after_start = mock_neptune.query.await_count

        await resolver.match("total_claims", "insurance")
        # No additional Neptune query — snapshot already populated.
        assert mock_neptune.query.await_count == calls_after_start


@pytest.mark.unit
class TestFuzzyMatch:
    """fuzzy near-miss matching (typos/plurals/abbreviations)."""

    async def test_exact_takes_precedence_over_fuzzy(self):
        resolver = _make_resolver()
        m = await resolver.match("show me the total_revenue please", "finance")
        assert m.found
        assert m.match_source in ("name", "synonym")
        assert m.match_confidence == 1.0

    async def test_typo_fuzzy_matches_with_sub_unit_confidence(self):
        resolver = _make_resolver()
        # "total_revenu" (missing trailing e) — a near-miss typo of total_revenue.
        m = await resolver.match("what is the total_revenu", "finance")
        assert m.found
        assert m.match_source == "fuzzy"
        assert 0.88 <= m.match_confidence < 1.0
        assert m.metric_id == "m-revenue"

    async def test_unrelated_query_does_not_fuzzy_match(self):
        resolver = _make_resolver()
        m = await resolver.match("what is the weather tomorrow", "finance")
        assert not m.found  # nothing clears the high threshold → Tier-2 fallthrough

    async def test_fuzzy_respects_namespace(self):
        resolver = _make_resolver()
        # total_premium is an insurance metric — a near-miss in finance ns must miss.
        m = await resolver.match("total_premiu", "finance")
        assert not m.found

    def test_empty_query_no_match(self):
        resolver = _make_resolver()
        m = resolver.fuzzy_match("", "finance")
        assert not m.found


@pytest.mark.unit
class TestDimensionSubstitution:
    """parameterized dimension substitution (sqlglot literals, not interp)."""

    def test_no_placeholders_unchanged(self):
        sql = "SELECT SUM(amount) FROM revenue"
        assert MetricResolver.substitute_dimensions(sql, {}, []) == sql

    def test_substitutes_string_dimension_as_quoted_literal(self):
        sql = "SELECT SUM(amount) FROM revenue WHERE region = :region"
        out = MetricResolver.substitute_dimensions(sql, {"region": "EMEA"}, ["region"])
        assert "'EMEA'" in out
        assert ":region" not in out

    def test_substitutes_numeric_without_quotes(self):
        sql = "SELECT SUM(amount) FROM revenue WHERE year = {year}"
        out = MetricResolver.substitute_dimensions(sql, {"year": 2024}, ["year"])
        assert "2024" in out
        assert "'2024'" not in out

    def test_sql_injection_value_is_escaped_not_interpolated(self):
        sql = "SELECT * FROM revenue WHERE region = :region"
        out = MetricResolver.substitute_dimensions(sql, {"region": "x'); DROP TABLE users;--"}, ["region"])
        # The malicious value is rendered as a single quoted literal (escaped),
        # never as raw SQL — sqlglot doubles the quote.
        assert "''" in out  # escaped quote
        assert "DROP TABLE users" in out  # present, but INSIDE the string literal
        # The whole value sits in one literal — no bare statement terminator breaks out.
        assert out.count("'") % 2 == 0  # balanced quotes

    def test_undeclared_dimension_raises(self):
        sql = "SELECT * FROM revenue WHERE region = :region"
        with pytest.raises(ValueError, match="not a declared dimension"):
            MetricResolver.substitute_dimensions(sql, {"region": "x"}, ["year"])

    def test_dimension_value_lookup_is_case_insensitive(self):
        # MR !279 review: the allowed-set check was case-insensitive but the value
        # lookup wasn't — {"Region": "EMEA"} must satisfy placeholder :region.
        sql = "SELECT * FROM revenue WHERE region = :region"
        out = MetricResolver.substitute_dimensions(sql, {"Region": "EMEA"}, ["region"])
        assert "'EMEA'" in out
        assert ":region" not in out

    def test_missing_value_raises(self):
        sql = "SELECT * FROM revenue WHERE region = :region"
        with pytest.raises(ValueError, match="No value supplied"):
            MetricResolver.substitute_dimensions(sql, {"year": 1}, ["region", "year"])

    def test_placeholders_present_but_no_values_raises(self):
        sql = "SELECT * FROM revenue WHERE region = :region"
        with pytest.raises(ValueError, match="requires dimensions"):
            MetricResolver.substitute_dimensions(sql, {}, ["region"])

    def test_postgres_cast_not_mistaken_for_placeholder(self):
        sql = "SELECT amount::text FROM revenue"
        # No placeholder → unchanged even though '::' is present.
        assert MetricResolver.substitute_dimensions(sql, {}, []) == sql


@pytest.mark.unit
class TestCrossNamespaceMetrics:
    """Metrics with same name in different namespaces must coexist."""

    async def test_same_metric_name_in_two_namespaces_both_resolve(self):
        """Same metric name in two namespaces resolves independently for each."""
        seed = [
            {
                "metric_id": "induction-demo:total_claims",
                "name": "total_claims",
                "sql_template": "SELECT SUM(amount) FROM old_claims",
                "namespace": "induction-demo",
            },
            {
                "metric_id": "insurance:total_claims",
                "name": "total_claims",
                "sql_template": "SELECT COUNT(*) FROM new_claims",
                "namespace": "insurance",
            },
        ]
        resolver = MetricResolver(seed=seed)

        # Query against 'insurance' must resolve the 'insurance:total_claims' metric, not miss
        result = resolver.exact_name_synonym_match("How many total claims are there?", "insurance")
        assert result.found
        assert result.metric_id == "insurance:total_claims"
        assert result.metric_name == "total_claims"
        assert "new_claims" in result.sql_template

        # Query against 'induction-demo' must resolve the 'induction-demo:total_claims' metric
        result2 = resolver.exact_name_synonym_match("How many total claims are there?", "induction-demo")
        assert result2.found
        assert result2.metric_id == "induction-demo:total_claims"
        assert result2.metric_name == "total_claims"
        assert "old_claims" in result2.sql_template

    async def test_same_synonym_in_two_namespaces_both_resolve(self):
        """Same synonym across namespaces must not shadow."""
        seed = [
            {
                "metric_id": "finance:rev",
                "name": "revenue",
                "synonyms": ["total sales"],
                "namespace": "finance",
                "sql_template": "SELECT SUM(amount) FROM orders",
            },
            {
                "metric_id": "insurance:rev",
                "name": "premium_revenue",
                "synonyms": ["total sales"],
                "namespace": "insurance",
                "sql_template": "SELECT SUM(premium) FROM policies",
            },
        ]
        resolver = MetricResolver(seed=seed)

        result = resolver.exact_name_synonym_match("What are our total sales?", "finance")
        assert result.found
        assert result.metric_id == "finance:rev"
        assert result.match_source == "synonym"

        result2 = resolver.exact_name_synonym_match("What are our total sales?", "insurance")
        assert result2.found
        assert result2.metric_id == "insurance:rev"
        assert result2.match_source == "synonym"

    async def test_fuzzy_match_respects_namespace_with_duplicate_names(self):
        """Fuzzy match must also respect namespace with duplicate names."""
        seed = [
            {
                "metric_id": "ns1:metric_a",
                "name": "total_revenue",
                "namespace": "ns1",
            },
            {
                "metric_id": "ns2:metric_a",
                "name": "total_revenue",
                "namespace": "ns2",
            },
        ]
        resolver = MetricResolver(seed=seed)

        # Typo "total_revenu" should fuzzy-match in ns1
        m = await resolver.match("what is the total_revenu", "ns1")
        assert m.found
        assert m.match_source == "fuzzy"
        assert m.metric_id == "ns1:metric_a"

        # Same typo should fuzzy-match in ns2
        m2 = await resolver.match("what is the total_revenu", "ns2")
        assert m2.found
        assert m2.match_source == "fuzzy"
        assert m2.metric_id == "ns2:metric_a"


@pytest.mark.unit
class TestMetricListSparql:
    """The metric-list SPARQL must read the configured graph-URI
    scheme (`GRAPH_URI_TEMPLATE`) — `{base}/{namespace}/{ontology_id}` — not the
    legacy hardcoded `urn:coa:{ns}:published` convention no writer uses."""

    def test_uses_configured_graph_prefix_not_legacy_urn(self):
        from coa_serve.tier1.metric_resolver import _metric_list_sparql

        sparql = _metric_list_sparql("https://ontology-workbench.local/{namespace}")
        # Filters graphs under the configured base prefix...
        assert 'STRSTARTS(STR(?g), "https://ontology-workbench.local/")' in sparql
        # ...and no longer uses the legacy urn:coa published scheme.
        assert f"urn:{URN_PREFIX}:" not in sparql.replace(f"urn:{URN_PREFIX}:vocab#", "")  # vocab IRIs are fine
        assert "published" not in sparql

    def test_namespace_extracted_as_first_segment_after_prefix(self):
        import re as _re

        from coa_serve.tier1.metric_resolver import _metric_list_sparql

        sparql = _metric_list_sparql("https://ontology-workbench.local/{namespace}")
        # Pull the REPLACE regex out of the generated SPARQL and apply it to a
        # real metric graph URI: {base}/{ns-uuid}/{encoded ontology id}.
        m = _re.search(r'REPLACE\(STR\(\?g\), "([^"]+)", "\$1"\)', sparql)
        assert m, f"REPLACE pattern not found in:\n{sparql}"
        # The regex is SPARQL-escaped (backslashes doubled for the string literal).
        # Undo one layer of escaping to get the XPath regex for Python re.
        ns_regex = m.group(1).replace("\\\\", "\\")
        ns_uuid = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        graph = f"https://ontology-workbench.local/{ns_uuid}/urn%3Acoa%3Avocab%23GovernedMetricsOntology"
        extracted = _re.sub(ns_regex, r"\1", graph)
        assert extracted == ns_uuid, f"expected {ns_uuid}, got {extracted}"

    def test_falls_back_to_default_template_when_unconfigured(self):
        from coa_serve.tier1.metric_resolver import (
            _DEFAULT_GRAPH_URI_TEMPLATE,
            _metric_list_sparql,
        )

        prefix = _DEFAULT_GRAPH_URI_TEMPLATE.split("{namespace}", 1)[0]
        sparql = _metric_list_sparql("")
        assert f'STRSTARTS(STR(?g), "{prefix}")' in sparql

    def test_resolver_builds_sparql_from_env_template(self, monkeypatch):
        monkeypatch.setenv("GRAPH_URI_TEMPLATE", "https://graph.example/{namespace}")
        resolver = MetricResolver(seed=[])
        assert 'STRSTARTS(STR(?g), "https://graph.example/")' in resolver._metric_list_sparql

    def test_prefix_xpath_metacharacters_are_escaped(self):
        """Review (Kun): a graph prefix containing an XPath regex metacharacter
        (e.g. `+`) must be escaped in the REPLACE pattern, otherwise namespace
        capture is corrupted or Neptune fails to parse the regex."""
        import re as _re

        from coa_serve.tier1.metric_resolver import _metric_list_sparql

        sparql = _metric_list_sparql("https://host/path+to/{namespace}")
        m = _re.search(r'REPLACE\(STR\(\?g\), "([^"]+)", "\$1"\)', sparql)
        assert m, f"REPLACE pattern not found in:\n{sparql}"
        ns_regex = m.group(1)
        # The '+' must be escaped (\+) in XPath regex, which becomes \\+ in SPARQL string.
        assert "path\\\\+to" in ns_regex
        # Undo SPARQL escaping for Python re validation
        ns_regex_py = ns_regex.replace("\\\\", "\\")
        ns_uuid = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        graph = f"https://host/path+to/{ns_uuid}/urn%3Acoa"
        assert _re.sub(ns_regex_py, r"\1", graph) == ns_uuid


@pytest.mark.unit
class TestSelectExpression:
    """#809: Tier-1 must pick the TRINO expression, not blindly ``dialects[0]``.

    The direct-JDBC path re-transpiles with sqlglot ``read="trino"``, so a
    non-Trino expression at index 0 would be mis-parsed (wrong results or a
    spurious firewall reject) against a PostgreSQL/Redshift source.
    """

    def test_prefers_trino_when_not_first(self):
        dialects = [
            {"dialect": "REDSHIFT", "expression": "SELECT DATEADD(day, 1, ts) FROM t"},
            {"dialect": "TRINO", "expression": "SELECT ts + INTERVAL '1' DAY FROM t"},
        ]
        assert MetricResolver._select_expression(dialects) == "SELECT ts + INTERVAL '1' DAY FROM t"

    def test_dialect_label_case_insensitive(self):
        dialects = [
            {"dialect": "postgresql", "expression": "PG"},
            {"dialect": "trino", "expression": "TRINO_EXPR"},
        ]
        assert MetricResolver._select_expression(dialects) == "TRINO_EXPR"

    def test_falls_back_to_first_when_no_trino(self):
        dialects = [
            {"dialect": "REDSHIFT", "expression": "REDSHIFT_EXPR"},
            {"dialect": "POSTGRESQL", "expression": "PG_EXPR"},
        ]
        assert MetricResolver._select_expression(dialects) == "REDSHIFT_EXPR"

    def test_single_trino_expression(self):
        dialects = [{"dialect": "TRINO", "expression": "ONLY"}]
        assert MetricResolver._select_expression(dialects) == "ONLY"

    def test_missing_dialect_key_treated_as_non_trino(self):
        dialects = [{"expression": "NO_LABEL"}]
        assert MetricResolver._select_expression(dialects) == "NO_LABEL"

    def test_empty_dialects_list_returns_empty_string(self):
        """An empty list must not IndexError on the ``dialects[0]`` fallback (#809 bot review)."""
        assert MetricResolver._select_expression([]) == ""

    def test_none_expression_value_coerces_to_empty_string(self):
        """Neptune stores expressionDialects as JSON, so ``{"expression": null}`` parses
        to ``None``. ``dict.get(k, "")`` only defaults on a MISSING key, not a present
        ``None`` — so the method must coerce None -> "" to honor its ``-> str`` contract
        (#809 bot review). Covers both the TRINO-match branch and the fallback branch."""
        # TRINO entry with null expression -> "" (not None)
        assert MetricResolver._select_expression([{"dialect": "TRINO", "expression": None}]) == ""
        # Fallback (no TRINO) with null expression at index 0 -> "" (not None)
        assert MetricResolver._select_expression([{"dialect": "REDSHIFT", "expression": None}]) == ""

    async def test_refresh_selects_trino_expression_from_neptune(self):
        """End-to-end through _bindings_to_seed: a metric whose TRINO expression
        is not first still resolves to the TRINO SQL, not ``dialects[0]``."""
        from unittest.mock import AsyncMock

        mock_neptune = AsyncMock()
        mock_neptune.query.return_value = [
            {
                "name": "order_span",
                "description": "Order date span",
                "expressionDialects": (
                    '[{"dialect":"REDSHIFT","expression":"SELECT DATEADD(day,1,d) FROM o"},'
                    '{"dialect":"TRINO","expression":"SELECT d + INTERVAL \'1\' DAY FROM o"}]'
                ),
                "dataSourceId": "ds-1",
                "namespace": "sales",
            },
        ]

        resolver = MetricResolver(neptune_client=mock_neptune)
        await resolver.start()

        defn = resolver._snapshot.by_name["order_span"][0]
        assert defn.sql_template == "SELECT d + INTERVAL '1' DAY FROM o"


@pytest.mark.unit
class TestSelectExpressionTranspileRoundTrip:
    """#809 end-to-end guard: prove the SELECTED expression survives the direct-JDBC
    executor's ``sqlglot.transpile(read="trino", write=<engine>)`` step as
    engine-valid SQL — the exact chain that produced silently-wrong results before
    the fix.

    ``CompositeQueryExecutor`` (clients/composite_executor.py) re-transpiles every
    metric with ``read="trino"`` before direct JDBC. If Tier-1 hands it a
    non-Trino ``dialects[0]`` expression, the Trino parser mis-reads it: a
    Redshift ``DATEADD(...)`` passes through *unchanged* into a PostgreSQL target
    (Postgres has no ``DATEADD`` -> runtime failure / wrong result). Selecting the
    TRINO expression yields ``... + INTERVAL '1 DAY'`` which Postgres accepts.
    """

    # A metric authored in BOTH dialects, TRINO NOT first (reproduces the bug shape).
    _DIALECTS = [
        {"dialect": "REDSHIFT", "expression": "SELECT DATEADD(day, 1, order_ts) AS d FROM orders"},
        {"dialect": "TRINO", "expression": "SELECT order_ts + INTERVAL '1' DAY AS d FROM orders"},
    ]

    @staticmethod
    def _executor_transpile(sql: str, engine: str) -> str:
        """Mirror composite_executor.py's transpile step verbatim (read='trino')."""
        import sqlglot

        return sqlglot.transpile(sql, read="trino", write=engine, identify=False)[0]

    def test_selected_trino_expr_transpiles_to_valid_postgres(self):
        """The #809-selected expression -> valid Postgres interval arithmetic
        (no bare DATEADD, which Postgres cannot execute)."""
        selected = MetricResolver._select_expression(self._DIALECTS)
        out = self._executor_transpile(selected, "postgres")
        assert "INTERVAL" in out.upper()
        assert "DATEADD" not in out.upper()

    def test_old_index0_pick_would_emit_invalid_postgres(self):
        """Discriminator: the pre-#809 behavior (dialects[0] = REDSHIFT) transpiled
        read='trino' passes DATEADD through UNCHANGED -> invalid for Postgres. This
        is the silently-wrong SQL the fix prevents; asserting it here documents why
        selecting TRINO matters and fails if someone reverts to dialects[0]."""
        index0_expr = self._DIALECTS[0]["expression"]
        out = self._executor_transpile(index0_expr, "postgres")
        assert "DATEADD" in out.upper()
        # And the fix must diverge from this broken output.
        selected = MetricResolver._select_expression(self._DIALECTS)
        assert self._executor_transpile(selected, "postgres") != out

    def test_selected_expr_passes_sql_firewall(self):
        """The selected + transpiled SQL clears the Tier-2 SQLFirewall parsed with
        the ENGINE dialect (source_db.py calls ``validate(sql, dialect=<engine>)``).
        Guards against the 'spurious UnsafeSQLError' symptom from the commit."""
        from coa_serve.tier2.sql_firewall import SQLFirewall

        selected = MetricResolver._select_expression(self._DIALECTS)
        for engine in ("postgres", "redshift"):
            transpiled = self._executor_transpile(selected, engine)
            # Should not raise UnsafeSQLError / parse error.
            SQLFirewall().validate(transpiled, dialect=engine)
