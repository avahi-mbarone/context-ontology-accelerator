# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for query_utils — entity extraction, namespace validation, graph URI template."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from coa_serve.query_utils import (
    DEFAULT_GRAPH_URI_TEMPLATE,
    extract_query_entities,
    get_graph_uri_template,
    validate_namespace,
)


@pytest.mark.unit
class TestExtractQueryEntities:
    def test_filters_stop_words(self):
        entities = extract_query_entities("What is the total claim amount for all customers")
        assert "what" not in entities
        assert "the" not in entities
        assert "claim" in entities
        assert "amount" in entities
        assert "customers" in entities

    def test_filters_short_words(self):
        entities = extract_query_entities("go to db")
        assert "go" not in entities
        assert "to" not in entities

    def test_max_count(self):
        entities = extract_query_entities("one two three four five six seven eight nine ten eleven", max_count=3)
        assert len(entities) <= 3

    def test_lowercase_normalization(self):
        entities = extract_query_entities("Show CLAIMS by CUSTOMER")
        assert "claims" in entities
        assert "customer" in entities

    def test_hyphenated_terms(self):
        entities = extract_query_entities("check order-id for S3 bucket")
        assert "order-id" in entities


@pytest.mark.unit
class TestValidateNamespace:
    def test_valid_namespace(self):
        validate_namespace("insurance")
        validate_namespace("my-namespace-01")

    def test_invalid_namespace_raises(self):
        with pytest.raises(ValueError, match="Invalid namespace"):
            validate_namespace("bad namespace!")

    def test_empty_namespace_raises(self):
        with pytest.raises(ValueError, match="Invalid namespace"):
            validate_namespace("")


@pytest.mark.unit
class TestGetGraphUriTemplate:
    def test_default_template(self):
        result = get_graph_uri_template()
        assert result == DEFAULT_GRAPH_URI_TEMPLATE

    def test_override_takes_precedence(self):
        result = get_graph_uri_template("custom://template/{namespace}")
        assert result == "custom://template/{namespace}"

    def test_env_var_fallback(self):
        with patch.dict("os.environ", {"GRAPH_URI_TEMPLATE": "env://t/{namespace}"}):
            result = get_graph_uri_template()
            assert result == "env://t/{namespace}"

    def test_override_beats_env_var(self):
        with patch.dict("os.environ", {"GRAPH_URI_TEMPLATE": "env://t/{namespace}"}):
            result = get_graph_uri_template("override://t/{namespace}")
            assert result == "override://t/{namespace}"
