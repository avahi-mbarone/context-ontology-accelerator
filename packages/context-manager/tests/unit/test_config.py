# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for configuration loading."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from coa_serve.config import ServiceConfig, load_config


@pytest.mark.unit
class TestLoadConfig:
    @patch("coa_serve.config.boto3")
    def test_loads_config_with_ssm(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-12345"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()

        assert isinstance(config, ServiceConfig)
        assert config.guardrail_id == "gr-12345"
        assert config.retrieval_guardrail_id == "gr-12345"
        mock_ssm.get_parameter.assert_any_call(Name="/coa/bedrock/guardrail-id")
        mock_ssm.get_parameter.assert_any_call(Name="/coa/bedrock/retrieval-guardrail-id")
        mock_ssm.get_parameter.assert_any_call(Name="/coa/bedrock/retrieval-guardrail-version")

    @patch("coa_serve.config.boto3")
    def test_missing_ssm_parameter_returns_empty_in_local(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "not found"}},
            "GetParameter",
        )
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.guardrail_id == ""

    @patch.dict("os.environ", {"ENVIRONMENT": "production"})
    @patch("coa_serve.config.boto3")
    def test_missing_ssm_parameter_returns_empty_guardrail(self, mock_boto3):
        """Guardrail SSM param missing is not fatal — enforcement is at Synthesizer level."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "not found"}},
            "GetParameter",
        )
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.guardrail_id == ""

    @patch.dict("os.environ", {"ENVIRONMENT": "production"})
    @patch("coa_serve.config.boto3")
    def test_ssm_access_denied_returns_empty_guardrail(self, mock_boto3):
        """SSM access errors are non-fatal for guardrail (enforcement at Synthesizer)."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
            "GetParameter",
        )
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.guardrail_id == ""

    @patch.dict(
        "os.environ",
        {
            "VKG_ENDPOINT": "http://custom-vkg:9090",
            "NEPTUNE_ENDPOINT": "neptune.cluster.us-east-1.neptune.amazonaws.com",
            "OPENSEARCH_ENDPOINT": "search.us-east-1.es.amazonaws.com",
            "BEDROCK_MODEL_ID": "us.anthropic.claude-opus-4-6-v1",
            "BEDROCK_REGION": "us-west-2",
            "DATA_SOURCES_TABLE": "my-ds-table",
            "METRIC_DEFINITIONS_TABLE": "my-metrics-table",
        },
    )
    @patch("coa_serve.config.boto3")
    def test_loads_env_vars(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()

        assert config.vkg_endpoint == "http://custom-vkg:9090"
        assert config.neptune_endpoint == "neptune.cluster.us-east-1.neptune.amazonaws.com"
        assert config.opensearch_endpoint == "search.us-east-1.es.amazonaws.com"
        assert config.bedrock_model_id == "us.anthropic.claude-opus-4-6-v1"
        assert config.bedrock_region == "us-west-2"
        assert config.data_sources_table == "my-ds-table"
        assert config.metric_definitions_table == "my-metrics-table"

    @patch("coa_serve.config.boto3")
    def test_config_is_frozen(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()

        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            config.guardrail_id = "new-value"


@pytest.mark.unit
class TestAgenticBudgetConfig:
    """Agentic Tier-3 budget knobs, including the P0 synthesis reserve."""

    @patch("coa_serve.config.boto3")
    def test_agentic_budget_defaults(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()

        assert config.agentic_time_budget_s == 30
        assert config.agentic_max_steps == 10
        assert config.agentic_per_tool_timeout_s == 30
        assert config.agentic_max_fanout == 5
        assert config.agentic_synthesis_reserve_s == 8

    @patch.dict("os.environ", {"AGENTIC_SYNTHESIS_RESERVE_S": "12"})
    @patch("coa_serve.config.boto3")
    def test_synthesis_reserve_env_override(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_synthesis_reserve_s == 12

    @patch.dict("os.environ", {"AGENTIC_SYNTHESIS_RESERVE_S": "9999"})
    @patch("coa_serve.config.boto3")
    def test_synthesis_reserve_out_of_range_falls_back(self, mock_boto3):
        """Out-of-range (>120) reserve warns and falls back to the default."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_synthesis_reserve_s == 8

    @patch("coa_serve.config.boto3")
    def test_ontology_edge_mode_defaults_to_soft_prior(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_ontology_edge_mode == "soft_prior"

    @patch.dict("os.environ", {"AGENTIC_ONTOLOGY_EDGE_MODE": "strict"})
    @patch("coa_serve.config.boto3")
    def test_ontology_edge_mode_strict_honored(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_ontology_edge_mode == "strict"

    @patch.dict("os.environ", {"AGENTIC_ONTOLOGY_EDGE_MODE": "bogus"})
    @patch("coa_serve.config.boto3")
    def test_ontology_edge_mode_invalid_falls_back(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_ontology_edge_mode == "soft_prior"

    @patch("coa_serve.config.boto3")
    def test_ontology_source_defaults_to_graph(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_ontology_source == "graph"

    @patch.dict("os.environ", {"AGENTIC_ONTOLOGY_SOURCE": "file"})
    @patch("coa_serve.config.boto3")
    def test_ontology_source_file_without_path_falls_back_to_graph(self, mock_boto3):
        """A 'file' source with no AGENTIC_ONTOLOGY_FILE is a misconfig (rdflib would
        parse the CWD → IsADirectoryError). load_config falls back to 'graph'."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_ontology_source == "graph"

    @patch.dict("os.environ", {"AGENTIC_ONTOLOGY_SOURCE": "file", "AGENTIC_ONTOLOGY_FILE": "/nonexistent/onto.ttl"})
    @patch("coa_serve.config.boto3")
    def test_ontology_source_file_with_missing_path_falls_back_to_graph(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_ontology_source == "graph"

    @patch("coa_serve.config.boto3")
    def test_max_no_progress_steps_default(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_max_no_progress_steps == 3

    @patch.dict("os.environ", {"AGENTIC_MAX_NO_PROGRESS_STEPS": "5"})
    @patch("coa_serve.config.boto3")
    def test_max_no_progress_steps_env_override(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.agentic_max_no_progress_steps == 5


@pytest.mark.unit
class TestLexicalRetrieverStrategyConfig:
    """LEXICAL_RETRIEVER_STRATEGY parsing into ServiceConfig.lexical_retriever_strategy.

    Mirrors the existing tier3_strategy validate-or-warn handling: a valid value
    is honored, an invalid value warns (invalid_lexical_retriever_strategy) and
    falls back to the default, and an absent var yields the documented default.
    structlog.testing.capture_logs() is used for the warning assertion
    (the package does not configure caplog), consistent with test_strategies.py.
    """

    @patch("coa_serve.config.boto3")
    def test_absent_var_yields_default(self, mock_boto3):
        """No env var → topic_beam, the strongest single-shot strategy.

        Standard mode's default engine. Guards the deployment default against a
        silent revert: topic_beam scores 45.13% strict on the SEC-10-Q benchmark
        (195 questions) versus 34.36% for the older hand-rolled path, so a
        regression here costs ~11pp for every caller that does not explicitly set
        options.retrieverStrategy.
        """
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.lexical_retriever_strategy == "topic_beam"

    @patch("coa_serve.config.boto3")
    def test_absent_var_yields_lexical_baseline_tier3_strategy(self, mock_boto3):
        """No env var → lexical-baseline, so standard mode actually runs topic_beam.

        Both halves are load-bearing: under "hand-rolled", main.py passes
        lexical_retriever_strategy=None to the Orchestrator and Tier 3 runs the
        hand-rolled VectorRetriever + GraphTraverser path regardless of what
        LEXICAL_RETRIEVER_STRATEGY says.
        """
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.tier3_strategy == "lexical-baseline"

    @patch.dict("os.environ", {"LEXICAL_RETRIEVER_STRATEGY": "traversal"})
    @patch("coa_serve.config.boto3")
    def test_valid_value_is_honored(self, mock_boto3):
        """A valid value is parsed straight through."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.lexical_retriever_strategy == "traversal"

    @patch.dict("os.environ", {"LEXICAL_RETRIEVER_STRATEGY": "entity_based"})
    @patch("coa_serve.config.boto3")
    def test_other_valid_value_is_honored(self, mock_boto3):
        """All registered strategy values are accepted (sourced from the enum)."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        config = load_config()
        assert config.lexical_retriever_strategy == "entity_based"

    @patch.dict("os.environ", {"LEXICAL_RETRIEVER_STRATEGY": "not-a-real-strategy"})
    @patch("coa_serve.config.boto3")
    def test_invalid_value_warns_and_falls_back(self, mock_boto3):
        """An invalid value logs invalid_lexical_retriever_strategy (warn) and falls back."""
        import structlog

        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        with structlog.testing.capture_logs() as logs:
            config = load_config()

        # Falls back to chunk_based_semantic, NOT the topic_beam default: the guard
        # also fires when the registry itself is unloadable (valid set collapses to
        # {"chunk_based_semantic"}), so recovering to topic_beam could "recover" to a
        # value that is not resolvable. See config.load_config.
        assert config.lexical_retriever_strategy == "chunk_based_semantic"
        warn_entries = [entry for entry in logs if entry.get("event") == "invalid_lexical_retriever_strategy"]
        assert warn_entries, "expected an invalid_lexical_retriever_strategy warning"
        assert warn_entries[0]["log_level"] == "warning"
        assert warn_entries[0]["value"] == "not-a-real-strategy"
        assert warn_entries[0]["fallback"] == "chunk_based_semantic"

    def test_load_config_does_not_import_graphrag_toolkit(self):
        """load_config must not pull in graphrag_toolkit (botocore sync-only invariant).

        Run in a fresh subprocess so a graphrag_toolkit already imported by a
        sibling test in the same process cannot mask a regression. Asserts that
        after calling load_config, no graphrag module is present in sys.modules.
        """
        import subprocess
        import sys

        code = (
            "import sys; "
            "from unittest.mock import MagicMock, patch; "
            "import coa_serve.config as cfg; "
            "p = patch.object(cfg, 'boto3'); m = p.start(); "
            "ssm = MagicMock(); "
            "ssm.get_parameter.return_value = {'Parameter': {'Value': 'gr-test'}}; "
            "m.client.return_value = ssm; "
            "c = cfg.load_config(); "
            "assert c.lexical_retriever_strategy == 'topic_beam', c.lexical_retriever_strategy; "
            "leaked = sorted(mod for mod in sys.modules if 'graphrag' in mod); "
            "assert not leaked, leaked; "
            "print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"load_config import-leak check failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "OK" in result.stdout


@pytest.mark.unit
class TestValidLexicalRetrieverStrategiesFallback:
    """`_valid_lexical_retriever_strategies` defensive paths.

    The function loads the `RetrieverStrategy` enum from `lexical/strategies.py`
    by path so config-load doesn't trigger the graphrag/botocore import chain.
    These tests cover the three broken-install / load-failure fallbacks: missing
    file, unrecognized loader (None spec), and an exception during exec_module.
    All three log a structured warning and fall back to {"chunk_based_semantic"}
    so the documented default still loads on a broken install.
    """

    def test_missing_strategies_file_warns_and_falls_back(self):
        """Missing strategies.py → warn + fallback to {chunk_based_semantic}."""
        from pathlib import Path

        import structlog
        from coa_serve.config import _valid_lexical_retriever_strategies

        # Force the file-existence probe to return False, simulating a broken install.
        with patch.object(Path, "exists", return_value=False), structlog.testing.capture_logs() as logs:
            strategies = _valid_lexical_retriever_strategies()

        assert strategies == {"chunk_based_semantic"}
        warn_entries = [entry for entry in logs if entry.get("event") == "lexical_strategies_module_missing"]
        assert warn_entries, "expected a lexical_strategies_module_missing warning"
        assert warn_entries[0]["log_level"] == "warning"

    def test_none_spec_warns_and_falls_back(self):
        """spec_from_file_location returning None → warn + fallback."""
        import structlog
        from coa_serve.config import _valid_lexical_retriever_strategies

        with (
            patch(
                "coa_serve.config.importlib.util.spec_from_file_location",
                return_value=None,
            ),
            structlog.testing.capture_logs() as logs,
        ):
            strategies = _valid_lexical_retriever_strategies()

        assert strategies == {"chunk_based_semantic"}
        warn_entries = [entry for entry in logs if entry.get("event") == "lexical_strategies_spec_unavailable"]
        assert warn_entries, "expected a lexical_strategies_spec_unavailable warning"
        assert warn_entries[0]["log_level"] == "warning"

    def test_exec_module_exception_warns_and_falls_back(self):
        """An exception while executing strategies.py → warn + fallback + sys.modules cleanup."""
        import sys

        import structlog
        from coa_serve.config import _valid_lexical_retriever_strategies

        # Build a real spec but force exec_module to raise.
        real_spec_from_file_location = __import__(
            "importlib.util", fromlist=["spec_from_file_location"]
        ).spec_from_file_location

        def fake_spec_from_file_location(name, location):
            spec = real_spec_from_file_location(name, location)
            spec.loader.exec_module = MagicMock(side_effect=SyntaxError("simulated"))
            return spec

        with (
            patch(
                "coa_serve.config.importlib.util.spec_from_file_location",
                side_effect=fake_spec_from_file_location,
            ),
            structlog.testing.capture_logs() as logs,
        ):
            strategies = _valid_lexical_retriever_strategies()

        assert strategies == {"chunk_based_semantic"}
        warn_entries = [entry for entry in logs if entry.get("event") == "lexical_strategies_load_failed"]
        assert warn_entries, "expected a lexical_strategies_load_failed warning"
        assert warn_entries[0]["log_level"] == "warning"
        assert warn_entries[0]["error_type"] == "SyntaxError"
        # The half-built module was popped from sys.modules in the finally block.
        assert "_lexical_strategies_for_config" not in sys.modules

    @patch("coa_serve.config.boto3")
    def test_load_config_still_succeeds_when_registry_load_fails(self, mock_boto3):
        """End-to-end: load_config() returns a valid config even if the registry can't be loaded."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": "gr-test"}}
        mock_boto3.client.return_value = mock_ssm

        with patch(
            "coa_serve.config._valid_lexical_retriever_strategies",
            return_value={"chunk_based_semantic"},
        ):
            config = load_config()

        # Default value still loads cleanly.
        assert config.lexical_retriever_strategy == "chunk_based_semantic"
