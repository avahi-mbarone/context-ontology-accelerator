# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Induction job's ``datasources`` manifest must offload to S3, not write inline.

Regression guard for the DynamoDB 400 KB item-size class of bug: a 20k-table
induction job wrote the full per-datasource table-name manifest (~575 KB) INLINE
into the job STATUS item via ``update_job_status(..., datasources=...)``, blowing
the 400 KB hard cap with ``ValidationException: Item size ... exceeded``. The
manifest is write-only (nothing reads it back), so it is offloaded to S3 and only
a ``datasources_s3_key`` string lands on the item — a write-only audit blob
retrievable by key, never hydrated back onto the status item.

Mirrors the proposal-matches offload (``test_proposal_update_s3_offload.py``).
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit


class _FakeS3:
    """Captures put_object calls (the offload write path)."""

    def __init__(self) -> None:
        self.put_calls: list[dict] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)


class _FakeTable:
    def __init__(self, item: dict | None) -> None:
        self._item = item

    def get_item(self, Key):  # noqa: N803 — boto3 kwarg name
        return {"Item": self._item} if self._item is not None else {}


def test_put_job_datasources_s3_writes_json_and_returns_key(monkeypatch):
    from coa_ontology import dynamo_store

    fake = _FakeS3()
    monkeypatch.setattr(dynamo_store, "_get_s3", lambda: fake)

    manifest = [{"datasourceId": "db0", "tables": ["t1", "t2"]}]
    key = dynamo_store.put_job_datasources_s3("ns", "job1", manifest)

    assert key == "jobs/ns/job1/datasources.json"
    assert len(fake.put_calls) == 1
    call = fake.put_calls[0]
    assert call["Bucket"] == dynamo_store._S3_BUCKET
    assert call["Key"] == "jobs/ns/job1/datasources.json"
    assert call["ContentType"] == "application/json"
    assert json.loads(call["Body"].decode("utf-8")) == manifest


def test_get_job_without_s3_key_returns_item_unchanged(monkeypatch):
    from coa_ontology import dynamo_store

    item = {"PK": "ns#JOB#job1", "SK": "STATUS", "job_id": "job1", "status": "completed"}
    monkeypatch.setattr(dynamo_store, "_get_table", lambda: _FakeTable(item))

    def _no_s3():
        pytest.fail("S3 must not be touched when no datasources_s3_key is present")

    monkeypatch.setattr(dynamo_store, "_get_s3", _no_s3)

    result = dynamo_store.get_job("job1", namespace="ns")

    assert result == item
    assert "datasources" not in result


def test_offloaded_manifest_byte_premise():
    # Documents the bug premise only: at 20k tables the inline manifest alone
    # (2 datasources x 10000 names) blows the 400 KB DynamoDB item cap, while the
    # post-offload item carries only the S3 key + scalars.
    #
    # NB: this asserts on hand-built dicts, so it does NOT exercise the real write
    # path — the WRITE-SITE regression guard (re-adding an inline blob turns a
    # test RED) lives in ``test_job_item_size_guard.py``, which drives the real
    # ``_run_induction`` and inspects the actual update_job_status kwargs.
    datasource_details = [
        {"datasourceId": f"db{d}", "tables": [f"schema.table_{i:05d}" for i in range(10000)]} for d in range(2)
    ]

    manifest_bytes = len(json.dumps(datasource_details, default=str).encode("utf-8"))
    assert manifest_bytes > 400_000

    written_attrs = {
        "status": "fetching_metadata",
        "updated_at": "2026-07-25T00:00:00+00:00",
        "datasources_s3_key": "jobs/ns/job1/datasources.json",
        "tables_total": sum(len(d["tables"]) for d in datasource_details),
        "columns_total": 200000,
        "source_type": "STRUCTURED",
    }
    item_bytes = len(json.dumps(written_attrs, default=str).encode("utf-8"))
    assert item_bytes < 400_000
    assert item_bytes < 1_000  # the key-based item is tiny, not merely under cap
