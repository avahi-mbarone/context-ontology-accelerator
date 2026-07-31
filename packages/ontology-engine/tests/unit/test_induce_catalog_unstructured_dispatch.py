# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the structured→unstructured dispatch in induce_catalog.

``induce_catalog.start_induction`` is the single ``POST /induce/`` entry point
the web app calls for BOTH strategies. When ``strategy ==
'unstructured_lexical_graph'`` it delegates to the unstructured router,
building an ``UnstructuredInductionRequest`` from the ``WorkbenchInductionRequest``.

Regression: that hand-off previously DROPPED ``grounding_ontology_ids`` and
``grounding_mode``, so a UI-selected foundational ontology never reached the
unstructured pipeline (grounding silently no-op'd, foundational_grounded=0).
These tests pin that the grounding params are forwarded.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from coa_common.constants import GRAPH_BASE_URI
from coa_ontology import induce_catalog
from coa_ontology.induce_catalog import (
    WorkbenchInductionRequest,
    start_induction,
)

pytestmark = pytest.mark.unit

_NS = "ns-1"
_PREFIX = f"{GRAPH_BASE_URI}/namespace/ns-1/ontology/induced#"


def _request_with_config(config: dict) -> MagicMock:
    """A fake FastAPI Request exposing ``app.state.config``."""
    req = MagicMock()
    req.app.state.config = config
    return req


def _dispatch(body: WorkbenchInductionRequest):
    """Invoke start_induction with the unstructured start patched; return the
    UnstructuredInductionRequest it was called with."""
    with (
        patch.object(induce_catalog, "dynamo_store", autospec=True),
        patch("coa_ontology.inducer.routers.induce_unstructured.start_induction") as mock_unstructured,
    ):
        mock_unstructured.return_value = SimpleNamespace(job_id="j", status="pending")
        # graph_arn must satisfy UnstructuredInductionRequest's SSRF-guard
        # pattern (12-digit account, valid graph id) added on main; a bare
        # ``:0:graph/g-x`` now fails validation.
        req = _request_with_config({"neptune_endpoint": "arn:aws:neptune-graph:us-east-1:000000000000:graph/g-test123"})
        start_induction(body=body, request=req, namespace=_NS)
        mock_unstructured.assert_called_once()
        return mock_unstructured.call_args.kwargs["body"]


class TestUnstructuredDispatchForwardsGrounding:
    def test_grounding_ontology_ids_and_mode_forwarded(self):
        body = WorkbenchInductionRequest(
            datasource_ids=["ds-1"],
            ontology_uri_prefix=_PREFIX,
            strategy="unstructured_lexical_graph",
            grounding_ontology_ids=["fibo-agreements"],
            grounding_mode="STANDARD",
        )
        unstructured_body = _dispatch(body)
        assert unstructured_body.grounding_ontology_ids == ["fibo-agreements"]
        assert unstructured_body.grounding_mode == "STANDARD"
        # Datasources + prefix still threaded.
        assert unstructured_body.datasource_ids == ["ds-1"]
        assert unstructured_body.ontology_uri_prefix == _PREFIX

    def test_no_grounding_selection_forwards_none(self):
        body = WorkbenchInductionRequest(
            datasource_ids=["ds-1"],
            ontology_uri_prefix=_PREFIX,
            strategy="unstructured_lexical_graph",
        )
        unstructured_body = _dispatch(body)
        assert unstructured_body.grounding_ontology_ids is None
        # Default mode still carried through (harmless when no ids).
        assert unstructured_body.grounding_mode == "ENHANCED"


@pytest.mark.unit
class TestWorkbenchRequestGroundingAliases:
    """#9: the induction request must bind grounding fields from BOTH the
    snake_case names (existing callers) and the Smithy contract's camelCase wire
    names (generated clients), or a camelCase request silently defaults."""

    def test_snake_case_binds(self):
        b = WorkbenchInductionRequest(
            ontology_uri_prefix="http://x/o#",
            grounding_mode="NONE",
            grounding_ontology_ids=["a"],
        )
        assert b.grounding_mode == "NONE"
        assert b.grounding_ontology_ids == ["a"]

    def test_camel_case_binds(self):
        b = WorkbenchInductionRequest.model_validate(
            {
                "ontology_uri_prefix": "http://x/o#",
                "groundingMode": "STANDARD",
                "groundingOntologyIds": ["b"],
            }
        )
        assert b.grounding_mode == "STANDARD"
        assert b.grounding_ontology_ids == ["b"]

    def test_default_when_omitted(self):
        b = WorkbenchInductionRequest(ontology_uri_prefix="http://x/o#")
        assert b.grounding_mode == "ENHANCED"
        assert b.grounding_ontology_ids is None
