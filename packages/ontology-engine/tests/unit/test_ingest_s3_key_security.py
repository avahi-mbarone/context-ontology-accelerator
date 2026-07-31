# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Security: ingest-from-s3 must reject s3_keys outside the caller's namespace.

The ontology-artifacts bucket is multi-tenant. ``POST .../ingest-from-s3``
takes a caller-supplied ``s3_key``; without validation a user in namespace A
could pass another tenant's key (e.g. ``proposals/B/<id>/latest/ontology.ttl``)
and have its content read + ingested into A. The handler must enforce that the
key sits under ``ontology-uploads/{namespace}/`` and reject path traversal,
BEFORE any S3 access or job creation.
"""

from __future__ import annotations

import pytest
from coa_control_plane_server.models.ingest_ontology_from_s3_request_content import (
    IngestOntologyFromS3RequestContent as IngestFromS3Request,
)
from coa_ontology.catalog.routers.ontologies import (
    ingest_ontology_from_s3,
)
from fastapi import HTTPException

pytestmark = pytest.mark.unit


def _call(s3_key: str, namespace: str = "ns-a", monkeypatch=None):
    # Guard: if validation is bypassed, put_ingest_job firing proves the key
    # reached the persistence/ingest path — fail loudly.
    if monkeypatch is not None:
        import coa_ontology.dynamo_store as ds

        monkeypatch.setattr(
            ds,
            "put_ingest_job",
            lambda *a, **k: pytest.fail("rejected key must not reach put_ingest_job"),
        )
    return ingest_ontology_from_s3(
        ontology_id="https://example.org/o",
        body=IngestFromS3Request(s3_key=s3_key),
        namespace=namespace,
    )


@pytest.mark.parametrize(
    "bad_key",
    [
        "proposals/ns-b/p-1/latest/ontology.ttl",  # another tenant's artifact
        "ontology-uploads/ns-b/abc/x.ttl",  # another namespace's upload prefix
        "ontology-uploads/ns-a/../ns-b/abc/x.ttl",  # traversal out of the prefix
        "ontologies/ns-a/induced/x.ttl",  # wrong (non-upload) prefix
        "ontology-uploads/ns-a-evil/abc/x.ttl",  # prefix-confusion (ns-a is a substring)
        "",  # empty
    ],
)
def test_rejects_keys_outside_namespace_prefix(bad_key, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _call(bad_key, namespace="ns-a", monkeypatch=monkeypatch)
    assert exc.value.status_code == 403


def test_accepts_valid_namespace_scoped_key(monkeypatch):
    import coa_ontology.catalog.routers.ontologies as mod

    created: dict = {}
    monkeypatch.setattr(
        mod.dynamo_store,
        "put_ingest_job",
        lambda job_id, ontology_id, status, namespace="default": created.update({"job_id": job_id, "ns": namespace}),
    )
    # No pre-existing registry row → the handler writes an "ingesting" stub so
    # the ontology shows in the list immediately. Mock both the lookup and the
    # stub write (they hit DynamoDB, absent in unit tests) and capture the stub.
    monkeypatch.setattr(mod.dynamo_store, "get_ontology_registry", lambda ns, oid: None)
    stub: dict = {}
    monkeypatch.setattr(
        mod.dynamo_store,
        "update_ontology_registry",
        lambda ns, oid, **fields: stub.update({"ns": ns, "oid": oid, **fields}),
    )
    # Don't actually run the background ingest.
    monkeypatch.setattr(mod, "Thread", None, raising=False)

    class _NoopThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr("threading.Thread", _NoopThread)

    out = ingest_ontology_from_s3(
        ontology_id="https://example.org/o",
        body=IngestFromS3Request(s3_key="ontology-uploads/ns-a/upload123/my.ttl"),
        namespace="ns-a",
    )
    # Typed IngestOntologyFromS3ResponseContent → result.status is the enum.
    assert out.result.status == "pending"
    assert created["ns"] == "ns-a"
    # The up-front stub row makes the upload visible immediately with a spinner.
    assert stub["status"] == mod.ONTOLOGY_STATUS_INGESTING
    assert stub["parse_status"] == "pending"
    assert stub["ns"] == "ns-a"
