# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Job-runner chain test: an AOSS transport fault at ``match_concepts`` must
propagate through the REAL strategy all the way up to ``_run_induction``, which
then marks the job FAILED and persists NO proposal.

The unit tests (``test_column_match_correctness.py``,
``test_inducer.py``) prove each link re-raises in isolation. This closes the
seam at the top: it drives the real ``_run_induction`` with the real
``TableToOntologyStrategy`` (``get_strategy`` is NOT mocked), injecting the raise
only at the fake pipeline's ``match_concepts`` seam. The anti-corruption half is
``create_proposal.assert_not_called()`` — a swallowed error would silently
persist an all-novel (corrupt) proposal instead.

Mirrors the drive pattern in ``test_induce_catalog_cost_metrics.py`` and the
transport/non-transport parametrization in ``test_column_match_correctness.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import coa_ontology.inducer.schemas as schemas_mod
import pytest
from coa_ontology.inducer.services.data_catalog import CatalogTable
from coa_ontology.inducer.services.pipeline import InductionPipeline
from opensearchpy.exceptions import ConnectionError as OSConnectionError
from opensearchpy.exceptions import SerializationError, TransportError

pytestmark = pytest.mark.unit


def _make_fake_pipeline(match_error: Exception):
    """A pipeline that runs the real concept extraction/embedding but injects a
    raise at the ``match_concepts`` seam — the exact AOSS failure point.

    ``_run_induction`` assigns ``pipeline.oc`` and reads ``getattr(pipeline,
    "eg", None)``; a plain instance tolerates the assignment and returns None for
    the missing attribute (so no cost-tracker wiring fires)."""

    class _FakePipeline:
        def extract_concepts(self, tables):
            return InductionPipeline(None, None, None).extract_concepts(tables)

        def embed_concepts(self, concepts, backend=None):
            return concepts, "model-x"

        def match_concepts(self, *args, **kwargs):
            raise match_error

    return _FakePipeline()


def _one_table_catalog() -> tuple[dict, list[dict]]:
    """A minimal SMUS catalog + the one-table dict ``_catalog_to_tables`` yields."""
    catalog = {"databases": [{"name": "db"}], "sourceType": "POSTGRES"}
    tables = [
        {
            "id": "t-orders",
            "name": "orders",
            "fullyQualifiedName": "db.orders",
            "columns": [
                {"name": "order_id", "dataType": "INT", "constraint": "PRIMARY_KEY"},
                {"name": "total", "dataType": "DECIMAL"},
            ],
        }
    ]
    return catalog, tables


@pytest.mark.parametrize(
    ("exc", "expected_error_name"),
    [
        (TransportError(429, "throttle"), "TransportError"),
        (OSConnectionError("N/A", "refused", Exception()), "ConnectionError"),
        (SerializationError("truncated body"), "SerializationError"),
    ],
    ids=["transport_429", "connection_error", "serialization_error"],
)
def test_transport_fault_fails_job_loud_and_persists_no_proposal(exc: Exception, expected_error_name: str) -> None:
    """A transport fault at ``match_concepts`` propagates through the real strategy
    to ``_run_induction``, which marks the job FAILED and creates NO proposal."""
    from coa_ontology.induce_catalog import (
        WorkbenchInductionRequest,
        _jobs,
        _run_induction,
    )
    from coa_ontology.inducer.schemas import JobResponse, JobStatus

    job_id = "job-transport-fault"
    _jobs[job_id] = JobResponse(job_id=job_id, status=JobStatus.PENDING, created_at="2026-01-01T00:00:00Z")
    job = _jobs[job_id]

    catalog, table_dicts = _one_table_catalog()
    # grounding_ontology_ids defaults to None (empty grounding scope) — the seam
    # under test is grounding-independent, so no pool is configured.
    body = WorkbenchInductionRequest(
        datasource_ids=["ds-1"],
        ontology_uri_prefix="http://test.org/ontology/induced#",
    )

    try:
        with (
            patch("coa_ontology.induce_catalog._fetch_catalog_from_smus", return_value=catalog),
            patch("coa_ontology.induce_catalog._catalog_to_tables", return_value=table_dicts),
            patch("coa_ontology.stores.build_stores", return_value=(MagicMock(), MagicMock())),
            patch("coa_ontology.stores.adapters.StoreOntologyCatalogAdapter", return_value=MagicMock()),
            patch("coa_ontology.induce_catalog.dynamo_store") as mock_dynamo,
            patch("coa_ontology.induce_catalog.emit_induction_job_metrics"),
        ):
            mock_dynamo.list_proposals.return_value = []

            _run_induction(
                job_id=job_id,
                body=body,
                namespace="fault-ns",
                config={"catalog_source": "smus"},
                build_pipeline_fn=lambda _config: _make_fake_pipeline(exc),
                schemas_mod=schemas_mod,
                catalog_table_cls=CatalogTable,
            )

        # Fail-loud: the job is FAILED and the "failed" status was persisted.
        assert job.status == JobStatus.FAILED
        failed_calls = [c for c in mock_dynamo.update_job_status.call_args_list if "failed" in c.args]
        assert failed_calls, "expected an update_job_status(..., 'failed', ...) call"
        assert job.error is not None and expected_error_name in job.error

        # Anti-corruption: NO proposal persisted (a swallow would emit all-novel).
        mock_dynamo.create_proposal.assert_not_called()
    finally:
        _jobs.pop(job_id, None)


def test_non_transport_error_falls_back_to_all_novel_and_completes() -> None:
    """Negative guard (narrowness): a non-transport ``RuntimeError`` at
    ``match_concepts`` must NOT fail the job — the strategy's all-novel fallback
    stays intact, the job COMPLETES, and a proposal IS persisted. Mirrors
    ``test_match_concepts_non_transport_failure_...`` one level up, proving the
    loud-fail path does not over-fire on programming bugs."""
    from coa_ontology.induce_catalog import (
        WorkbenchInductionRequest,
        _jobs,
        _run_induction,
    )
    from coa_ontology.inducer.schemas import JobResponse, JobStatus

    job_id = "job-runtime-bug"
    _jobs[job_id] = JobResponse(job_id=job_id, status=JobStatus.PENDING, created_at="2026-01-01T00:00:00Z")
    job = _jobs[job_id]

    catalog, table_dicts = _one_table_catalog()
    body = WorkbenchInductionRequest(
        datasource_ids=["ds-1"],
        ontology_uri_prefix="http://test.org/ontology/induced#",
    )

    fake_constraint = MagicMock()
    fake_constraint.model_dump.return_value = {}

    try:
        with (
            patch("coa_ontology.induce_catalog._fetch_catalog_from_smus", return_value=catalog),
            patch("coa_ontology.induce_catalog._catalog_to_tables", return_value=table_dicts),
            patch("coa_ontology.stores.build_stores", return_value=(MagicMock(), MagicMock())),
            patch("coa_ontology.stores.adapters.StoreOntologyCatalogAdapter", return_value=MagicMock()),
            patch(
                "coa_ontology.validation.shapes.config.generate_config_from_db",
                return_value=fake_constraint,
            ),
            patch("coa_ontology.induce_catalog.os.makedirs"),
            patch("builtins.open", MagicMock()),
            patch("coa_ontology.induce_catalog.dynamo_store") as mock_dynamo,
            patch("coa_ontology.induce_catalog.emit_induction_job_metrics"),
        ):
            mock_dynamo.list_proposals.return_value = []

            _run_induction(
                job_id=job_id,
                body=body,
                namespace="bug-ns",
                config={"catalog_source": "smus"},
                build_pipeline_fn=lambda _config: _make_fake_pipeline(RuntimeError("programming bug")),
                schemas_mod=schemas_mod,
                catalog_table_cls=CatalogTable,
            )

        # Did NOT fail loud — the all-novel fallback carried the job to completion.
        assert job.status == JobStatus.COMPLETED
        mock_dynamo.create_proposal.assert_called_once()
    finally:
        _jobs.pop(job_id, None)
