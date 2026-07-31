# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared query utilities: stop words, entity extraction, namespace validation, graph URI helpers."""

from __future__ import annotations

import os
import re

from coa_common import validate_namespace_name

# Filtered from NL queries before matching against ontology class labels — these common
# words would produce false-positive matches and dilute the keyword relevance signal.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "what",
        "is",
        "the",
        "how",
        "many",
        "show",
        "me",
        "all",
        "for",
        "in",
        "by",
        "a",
        "an",
        "of",
        "to",
        "and",
        "or",
        "list",
        "find",
        "get",
        "total",
        "count",
        "average",
        "where",
        "which",
        "each",
        "with",
        "from",
        "between",
        "their",
        "has",
        "have",
        "does",
        "are",
        "was",
        "were",
        "this",
        "that",
        "these",
        "those",
        "can",
        "will",
        "do",
    }
)

# Graph URI template — {namespace} is replaced at query time.
# Set via GRAPH_URI_TEMPLATE env var (e.g. "https://ontology.example.com/{namespace}").
# TODO: Resolve graph URIs dynamically from the ontology catalog (DynamoDB registry).

# Regex for extracting safe tokens from NL queries.
# Supports alphanumeric identifiers and hyphenated terms like S3, order-id.
_ENTITY_RE = re.compile(r"\b[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\b")


def extract_query_entities(query: str, *, max_count: int = 10) -> list[str]:
    """Extract key terms from a natural language query.

    Tokenizes using a regex that supports alphanumeric tokens and hyphenated
    identifiers (e.g., S3, order-id). Applies lowercase normalization, filters
    out stop words and tokens of length <= 2, and caps output at max_count.

    Args:
        query: Natural language query string.
        max_count: Maximum number of entities to return.

    Returns:
        List of lowercase entity strings, at most max_count entries.
    """
    tokens = _ENTITY_RE.findall(query.lower())
    return [t for t in tokens if t not in STOP_WORDS and len(t) > 2][:max_count]


def validate_namespace(namespace: str) -> None:
    """Validate a namespace string for safe use in SPARQL interpolation.

    Delegates to ``coa_common.validate_namespace_name``.
    """
    validate_namespace_name(namespace)


DEFAULT_GRAPH_URI_TEMPLATE = os.environ.get("GRAPH_URI_TEMPLATE", "")


def get_graph_uri_template(override: str | None = None) -> str:
    """Return the graph URI template to use, respecting override and env-var fallback.

    Resolution order:
    1. ``override`` parameter (if non-empty)
    2. ``GRAPH_URI_TEMPLATE`` environment variable

    Args:
        override: Caller-supplied template string; ``None`` or empty string to skip.

    Returns:
        A graph URI template string with a ``{namespace}`` placeholder, or empty string if unconfigured.

    Raises:
        ValueError: If the resolved template is non-empty but missing the ``{namespace}`` placeholder.
    """
    result = override or os.environ.get("GRAPH_URI_TEMPLATE", "")
    if result and "{namespace}" not in result:
        raise ValueError(f"GRAPH_URI_TEMPLATE must contain '{{namespace}}' placeholder, got: {result!r}")
    return result


def namespace_graph_prefix(template: str, namespace: str) -> str:
    """Return the graph URI prefix for a namespace, suitable for STRSTARTS filtering.

    All Neptune queries that target namespace-scoped named graphs should use::

        GRAPH ?g { ... }
        FILTER(STRSTARTS(STR(?g), "<prefix>"))

    where ``<prefix>`` is the return value of this function.

    Args:
        template: The graph URI template (from ``get_graph_uri_template()``).
        namespace: The namespace identifier.

    Returns:
        A URI prefix ending with ``/`` (e.g. ``https://ontology-workbench.local/my-ns/``).
    """
    return template.format(namespace=namespace).rstrip("/") + "/"
