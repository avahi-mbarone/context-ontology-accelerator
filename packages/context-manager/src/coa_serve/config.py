# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Service configuration loaded from environment and SSM."""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import boto3
import structlog
from botocore.exceptions import ClientError
from coa_common import resolve_region, sync_boto_config

logger = structlog.get_logger(__name__)


def _valid_lexical_retriever_strategies() -> set[str]:
    """Return the valid ``RetrieverStrategy`` values for config validation.

    Reuses the ``RetrieverStrategy`` enum from
    ``coa_serve.lexical.strategies`` as the single source of truth.

    The enum is loaded directly from the ``strategies.py`` file (by path) rather
    than via a normal ``import``. Importing
    ``coa_serve.lexical.strategies`` the usual way executes the
    ``lexical`` package ``__init__``, which eagerly imports ``baseline_retriever``
    and thereby pulls in ``graphrag_toolkit`` at config-load time. Loading the
    module file standalone keeps ``strategies.py``'s own lazy-import discipline
    intact, so ``load_config`` never triggers the graphrag/botocore import chain.

    On a broken install (missing ``strategies.py``, unrecognized loader, or an
    exception while executing the module), falls back to a minimal set
    containing only the documented default — ``load_config``'s existing
    validate-or-warn handling will then warn-and-fall-back any non-default
    deployment value, which is the correct behavior when the registry can't be
    consulted.
    """
    fallback: set[str] = {"chunk_based_semantic"}

    strategies_path = Path(__file__).parent / "lexical" / "strategies.py"
    if not strategies_path.exists():
        logger.warning("lexical_strategies_module_missing", path=str(strategies_path))
        return fallback

    spec = importlib.util.spec_from_file_location("_lexical_strategies_for_config", strategies_path)
    if spec is None or spec.loader is None:
        logger.warning("lexical_strategies_spec_unavailable", path=str(strategies_path))
        return fallback

    module = importlib.util.module_from_spec(spec)
    # Register before exec: the strategies module uses `from __future__ import
    # annotations`, so dataclass field-type resolution looks the module up in
    # sys.modules by name while executing. Without this, exec_module raises
    # AttributeError on the frozen StrategySpec dataclass.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return {strategy.value for strategy in module.RetrieverStrategy}
    except Exception as e:
        logger.warning("lexical_strategies_load_failed", error=str(e), error_type=type(e).__name__)
        return fallback
    finally:
        sys.modules.pop(spec.name, None)


@dataclass(frozen=True)
class ServiceConfig:
    """Immutable runtime configuration for the serve component (endpoints, tables, model ids)."""

    guardrail_id: str
    vkg_endpoint: str
    neptune_endpoint: str
    opensearch_endpoint: str
    bedrock_model_id: str
    bedrock_region: str
    data_sources_table: str
    metric_definitions_table: str
    memory_id: str
    session_metadata_table: str
    retrieval_guardrail_id: str = ""
    retrieval_guardrail_version: str = "DRAFT"
    # Standard-mode Tier-3 engine. "lexical-baseline" + topic_beam is the default
    # because topic_beam is the strongest single-shot strategy on the SEC-10-Q
    # benchmark (45.13% strict vs 34.36% for hand-rolled, 195 questions).
    tier3_strategy: Literal["hand-rolled", "lexical-baseline", "agentic"] = "lexical-baseline"
    lexical_retriever_strategy: str = "topic_beam"
    # Agentic Tier-3 budgets (used only when tier3_strategy == "agentic" or a
    # per-request options.mode=agentic). Range-validated at load; see load_config.
    agentic_time_budget_s: int = 30
    agentic_max_steps: int = 10
    agentic_per_tool_timeout_s: int = 30
    agentic_max_fanout: int = 5
    # Wall-clock seconds reserved at session end for the final synthesis call, so
    # a late tool invocation cannot push synthesis past the time budget.
    agentic_synthesis_reserve_s: int = 8
    # Consecutive no-progress steps a sub-question loop tolerates before stopping
    # with no_new_information. Higher = more escalation attempts (switch tool,
    # reframe, switch modality) before giving up. 1 restores stop-on-first.
    agentic_max_no_progress_steps: int = 3
    # Where the agentic Ontology_Lookup_Tool reads the per-namespace ontology.
    # "graph" (default) queries the live published RDF graph in Neptune via the
    # serve graph client — correct for document-induced namespaces, which have no
    # standalone .ttl file. "file" reads a serialized .ttl at agentic_ontology_file
    # (dev/test convenience); it requires a non-empty, readable path.
    agentic_ontology_source: Literal["graph", "file"] = "graph"
    agentic_ontology_file: str = ""
    # How the ontology constrains edge-typed graph traversal. "soft_prior"
    # (default) treats the ontology's edge types as a PREFERENCE — ontology edges
    # are ordered first, but edge types the planner proposes beyond the ontology
    # are still traversed (the induced ontology is a heavily-pruned subset of the
    # graph's predicate vocabulary, so a hard allowlist starves traversal and drops
    # the majority of real edges). "strict" restores the allowlist (ontology edges
    # only), guarded so it never strips the request down to nothing.
    agentic_ontology_edge_mode: Literal["soft_prior", "strict"] = "soft_prior"


class ConfigurationError(Exception):
    """Raised when required configuration cannot be loaded."""


def _parse_int_in_range(name: str, default: int, low: int, high: int) -> int:
    """Parse an int env var, falling back to ``default`` when absent/invalid/out-of-range.

    A malformed or out-of-range value logs a warning and returns ``default`` rather
    than raising, so a bad env var can never crash service startup.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("invalid_int_config", name=name, value=raw, fallback=default)
        return default
    if not (low <= value <= high):
        logger.warning("int_config_out_of_range", name=name, value=value, low=low, high=high, fallback=default)
        return default
    return value


def load_config() -> ServiceConfig:
    """Load config from env vars and SSM. Called once at startup."""
    environment = os.environ.get("ENVIRONMENT", "local")
    ssm_prefix = os.environ.get("SSM_PREFIX", "/coa")
    guardrail_id = _get_ssm_parameter(f"{ssm_prefix}/bedrock/guardrail-id", required=False)
    if guardrail_id == "none":
        guardrail_id = ""
    retrieval_guardrail_id = _get_ssm_parameter(f"{ssm_prefix}/bedrock/retrieval-guardrail-id", required=False)
    retrieval_guardrail_version = (
        _get_ssm_parameter(f"{ssm_prefix}/bedrock/retrieval-guardrail-version", required=False) or "DRAFT"
    )
    logger.info(
        "config_loaded",
        guardrail_configured=bool(guardrail_id),
        retrieval_guardrail_configured=bool(retrieval_guardrail_id),
        environment=environment,
    )

    tier3_strategy = os.environ.get("TIER3_STRATEGY", "lexical-baseline")
    if tier3_strategy not in ("hand-rolled", "lexical-baseline", "agentic"):
        logger.warning("invalid_tier3_strategy", value=tier3_strategy, fallback="lexical-baseline")
        tier3_strategy = "lexical-baseline"

    # Agentic Tier-3 budgets: validate-or-fallback within the documented ranges.
    agentic_time_budget_s = _parse_int_in_range("AGENTIC_TIME_BUDGET_S", 30, 1, 300)
    agentic_max_steps = _parse_int_in_range("AGENTIC_MAX_STEPS", 10, 1, 50)
    agentic_per_tool_timeout_s = _parse_int_in_range("AGENTIC_PER_TOOL_TIMEOUT_S", 30, 1, 120)
    agentic_max_fanout = _parse_int_in_range("AGENTIC_MAX_FANOUT", 5, 1, 20)
    agentic_synthesis_reserve_s = _parse_int_in_range("AGENTIC_SYNTHESIS_RESERVE_S", 8, 0, 120)
    agentic_max_no_progress_steps = _parse_int_in_range("AGENTIC_MAX_NO_PROGRESS_STEPS", 3, 1, 20)
    agentic_ontology_source = os.environ.get("AGENTIC_ONTOLOGY_SOURCE", "graph")
    if agentic_ontology_source not in ("graph", "file"):
        logger.warning("invalid_agentic_ontology_source", value=agentic_ontology_source, fallback="graph")
        agentic_ontology_source = "graph"
    agentic_ontology_file = os.environ.get("AGENTIC_ONTOLOGY_FILE", "")
    # A "file" source with no readable path is a misconfiguration (an empty path
    # makes rdflib parse the CWD → IsADirectoryError at invoke time). Fall back to
    # the graph source rather than ship a source that fails every lookup.
    if agentic_ontology_source == "file" and (not agentic_ontology_file or not Path(agentic_ontology_file).is_file()):
        logger.warning(
            "agentic_ontology_file_invalid_falling_back_to_graph",
            path=agentic_ontology_file or "(unset)",
        )
        agentic_ontology_source = "graph"
    agentic_ontology_edge_mode = os.environ.get("AGENTIC_ONTOLOGY_EDGE_MODE", "soft_prior")
    if agentic_ontology_edge_mode not in ("soft_prior", "strict"):
        logger.warning("invalid_agentic_ontology_edge_mode", value=agentic_ontology_edge_mode, fallback="soft_prior")
        agentic_ontology_edge_mode = "soft_prior"

    # Default topic_beam: the strongest single-shot strategy on the SEC-10-Q
    # benchmark (45.13% strict vs 34.36% hand-rolled, 195 questions).
    #
    # The FALLBACK is deliberately chunk_based_semantic, not topic_beam: the guard
    # fires when the value is absent from the registry's valid set, and that set
    # collapses to {"chunk_based_semantic"} when the registry itself cannot be
    # loaded (see _valid_lexical_retriever_strategies). Falling back to topic_beam
    # would "recover" to the value just rejected. chunk_based_semantic is the
    # registry's own DEFAULT_STRATEGY and its broken-install sentinel, so it is the
    # one value guaranteed to be resolvable.
    lexical_retriever_strategy = os.environ.get("LEXICAL_RETRIEVER_STRATEGY", "topic_beam")
    if lexical_retriever_strategy not in _valid_lexical_retriever_strategies():
        logger.warning(
            "invalid_lexical_retriever_strategy",
            value=lexical_retriever_strategy,
            fallback="chunk_based_semantic",
        )
        lexical_retriever_strategy = "chunk_based_semantic"

    return ServiceConfig(
        guardrail_id=guardrail_id,
        retrieval_guardrail_id=retrieval_guardrail_id,
        retrieval_guardrail_version=retrieval_guardrail_version,
        vkg_endpoint=os.environ.get("VKG_ENDPOINT", "http://vkg.local:8080"),
        neptune_endpoint=os.environ.get("NEPTUNE_ENDPOINT", ""),
        opensearch_endpoint=os.environ.get("OPENSEARCH_ENDPOINT", ""),
        bedrock_model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5"),
        bedrock_region=os.environ.get("BEDROCK_REGION", resolve_region()),
        data_sources_table=os.environ.get("DATA_SOURCES_TABLE", ""),
        metric_definitions_table=os.environ.get("METRIC_DEFINITIONS_TABLE", ""),
        memory_id=os.environ.get("MEMORY_ID", ""),
        session_metadata_table=os.environ.get("SESSION_METADATA_TABLE", ""),
        tier3_strategy=tier3_strategy,
        lexical_retriever_strategy=lexical_retriever_strategy,
        agentic_time_budget_s=agentic_time_budget_s,
        agentic_max_steps=agentic_max_steps,
        agentic_per_tool_timeout_s=agentic_per_tool_timeout_s,
        agentic_max_fanout=agentic_max_fanout,
        agentic_synthesis_reserve_s=agentic_synthesis_reserve_s,
        agentic_max_no_progress_steps=agentic_max_no_progress_steps,
        agentic_ontology_source=agentic_ontology_source,
        agentic_ontology_file=agentic_ontology_file,
        agentic_ontology_edge_mode=agentic_ontology_edge_mode,
    )


def _get_ssm_parameter(name: str, *, required: bool = False) -> str:
    """Fetch a parameter from SSM Parameter Store.

    Args:
        name: The SSM parameter path.
        required: If True, raises ConfigurationError on failure instead of
                  returning a placeholder. Set to True in non-local environments.
    """
    try:
        region = resolve_region()
        ssm = boto3.client("ssm", region_name=region, config=sync_boto_config())
        return ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ParameterNotFound":
            if required:
                raise ConfigurationError(f"Required SSM parameter not found: {name}") from e
            logger.warning("ssm_parameter_not_found", name=name)
            return ""
        if required:
            raise ConfigurationError(f"Failed to load SSM parameter {name}: {error_code}") from e
        logger.error("ssm_parameter_error", name=name, error_code=error_code)
        return ""
    except Exception as e:
        if required:
            raise ConfigurationError(f"Failed to load SSM parameter {name}: {e}") from e
        logger.error("ssm_parameter_unexpected_error", name=name, error=str(e))
        return ""
