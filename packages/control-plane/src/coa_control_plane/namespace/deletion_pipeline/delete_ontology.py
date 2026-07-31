# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deletion pipeline step: delete all ontology data + S3 artifacts.

Reuses the existing ontology-engine HTTP teardown and S3 sweep from
``cleanup.py`` — this step just runs them as their own Step Functions task
so the ontology-engine's slow, best-effort HTTP call (up to 120s) has its
own retry policy separate from the rest of the pipeline.
"""

from __future__ import annotations

from typing import Any

import structlog

from coa_control_plane.namespace.cleanup import (
    delete_all_ontologies,
    delete_ontology_artifacts,
)

logger = structlog.get_logger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions task: delete all ontology data for the namespace.

    Input: {"namespaceId": str}
    Output: {"namespaceId": str}

    Both underlying calls are already best-effort (log + swallow) since they
    call external services (ontology-engine HTTP, S3) that this pipeline
    does not own the retry semantics of at a finer grain than "retry the
    whole step". Errors inside are logged, not raised, matching the
    non-critical/continue-on-failure classification for this step.
    """
    namespace_id = event["namespaceId"]
    delete_all_ontologies(namespace_id)
    delete_ontology_artifacts(namespace_id)
    return {"namespaceId": namespace_id}
