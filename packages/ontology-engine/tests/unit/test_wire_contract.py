# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Wire-contract tests for the async-upload request/response models.

The upload/ingest endpoints use the **Smithy-generated** control-plane models
(``coa_control_plane_server.models.*``) so the wire form matches
the generated TypeScript client the web app uses: camelCase aliases
(``uploadUrl``, ``s3Key``, ``contentType``) with ``populate_by_name`` so
snake_case input still works for ad-hoc curl / integ tests.

Ordinary unit tests don't catch wire-name drift: Python tests assert Python
field names, and web-app tests mock ``client.send``. These tests pin the
camelCase wire form so a regression fails here instead of silently in the
browser. See ``scripts/audit_wire_contract.py`` for the repo-wide audit.
"""

from __future__ import annotations

import pytest
from coa_control_plane_server.models.get_ontology_upload_url_request_content import (
    GetOntologyUploadUrlRequestContent,
)
from coa_control_plane_server.models.get_ontology_upload_url_response_content import (
    GetOntologyUploadUrlResponseContent,
)
from coa_control_plane_server.models.ingest_ontology_from_s3_request_content import (
    IngestOntologyFromS3RequestContent,
)
from fastapi.encoders import jsonable_encoder

pytestmark = pytest.mark.unit


class TestUploadUrlResponseWireForm:
    """``GetOntologyUploadUrl`` output members: uploadUrl, s3Key, ontologyId."""

    def test_serializes_camelcase_via_fastapi_encoder(self):
        resp = GetOntologyUploadUrlResponseContent(
            upload_url="https://s3/x",
            s3_key="ontology-uploads/ns/abc/x.ttl",
            ontology_id="https://example.org/o",
        )
        # jsonable_encoder is what FastAPI uses to serialize a returned model;
        # by_alias=True emits the camelCase wire names.
        wire = jsonable_encoder(resp, by_alias=True)
        assert set(wire.keys()) == {"uploadUrl", "s3Key", "ontologyId"}
        assert "upload_url" not in wire
        assert "s3_key" not in wire


class TestUploadUrlRequestWireForm:
    """``GetOntologyUploadUrl`` input: client sends camelCase; snake also OK."""

    def test_accepts_camelcase_input_from_smithy_client(self):
        req = GetOntologyUploadUrlRequestContent.model_validate(
            {
                "filename": "x.ttl",
                "contentType": "text/turtle",
                "ontologyId": "https://example.org/o",
                "title": "T",
            }
        )
        assert req.content_type == "text/turtle"
        assert req.ontology_id == "https://example.org/o"

    def test_still_accepts_snakecase_input(self):
        # populate_by_name keeps snake_case input working alongside the alias.
        req = GetOntologyUploadUrlRequestContent.model_validate(
            {
                "filename": "x.ttl",
                "content_type": "application/rdf+xml",
                "ontology_id": "https://example.org/o",
            }
        )
        assert req.content_type == "application/rdf+xml"
        assert req.ontology_id == "https://example.org/o"


class TestIngestFromS3RequestWireForm:
    """``IngestOntologyFromS3`` input: s3Key is @required — must accept camel."""

    def test_accepts_required_s3key_camelcase(self):
        req = IngestOntologyFromS3RequestContent.model_validate(
            {"s3Key": "ontology-uploads/ns/abc/x.ttl", "title": "T"}
        )
        assert req.s3_key == "ontology-uploads/ns/abc/x.ttl"

    def test_ontology_type_camel_alias(self):
        req = IngestOntologyFromS3RequestContent.model_validate({"s3Key": "k", "ontologyType": "user_created"})
        assert req.ontology_type == "user_created"
