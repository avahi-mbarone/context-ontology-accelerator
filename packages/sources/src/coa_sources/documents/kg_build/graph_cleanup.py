# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deletion Pipeline — Stage 2: Graph Cleanup ECS Task.

Invoked by the deletion Step Functions state machine via EcsRunTask.
Removes the document subgraph and vector embeddings for a specific doc source
from Neptune and OpenSearch.

Uses DeleteSources directly with a small batch_size to avoid Neptune's
per-query memory limit. The default batch_size=1000 causes MemoryLimitExceeded
on large documents because delete_statements() passes all 1000 IDs in one query.

Opens the vector store over the SAME ``EMBEDDING_INDEXES`` the build task writes,
which is why that constant is imported rather than re-derived here. Omitting
``index_names`` falls back to the toolkit's default set, which includes
``statement`` — an index the build path deliberately does not create (see the
constant's rationale in graph_build). Deletion then waits out a 70-second
"Unable to find documents for all ids in index" timeout per batch for documents
that were never indexed. A 36-source deletion burned 10 hours that way before the
Step Functions task timed out and left the source DELETE_FAILED. The two paths
must agree on the index set: any change to what is embedded has to reach this
task, or deletion hangs on whatever the build stopped writing.

Applies the same graphrag-toolkit monkey-patches as the build task. Deletion
reads the vector indexes (``delete_embeddings`` →
``_get_existing_doc_ids_for_ids`` → ``paginated_search``), so it hits the exact
AOSS failure modes the build path already patches around. Unpatched, a
``429 circuit_breaking_exception`` from the NEXTGEN heap breaker was neither
retried nor reported: the toolkit's own handler does ``except Exception as ee:
... raise e`` with ``e`` unbound, so it raised ``UnboundLocalError``, masked the
real 429, failed the ECS task, and left the Step Functions execution FAILED with
the namespace's embeddings orphaned half-deleted in AOSS (observed 2026-07-27 on
both SEC-10-Q namespaces). The patches must run BEFORE graphrag is imported —
``LexicalGraphIndex``/``VectorStoreFactory`` bind their own references to the
patched functions at import time — so the graphrag imports live inside main().
"""

from __future__ import annotations

import os

import structlog
from coa_common.logging import setup_logging

from .graph_build import (
    EMBEDDING_INDEXES,
    _patch_graphrag_bulk_ingest_retry,
    _patch_graphrag_paginated_search_retry,
    _patch_graphrag_toolkit_for_aoss_nextgen,
)

setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
logger = structlog.get_logger(__name__)

NAMESPACE_ID: str = os.environ.get("NAMESPACE_ID", "")
DOC_SOURCE_ID: str = os.environ.get("DOC_SOURCE_ID", "")
TENANT_ID: str = os.environ.get("TENANT_ID", "")
NEPTUNE_ENDPOINT: str = os.environ.get("NEPTUNE_ENDPOINT", "")
OPENSEARCH_ENDPOINT: str = os.environ.get("OPENSEARCH_ENDPOINT", "")

# Small batch size to avoid Neptune's per-query memory limit.
# The default is 1000 which causes MemoryLimitExceededException on large docs.
_BATCH_SIZE = 200


def main() -> None:
    """Run the graph-cleanup task (ECS Fargate entrypoint).

    Reads its inputs from environment variables (namespace, doc source, tenant,
    and the Neptune/OpenSearch endpoints), locates every graph source for the
    doc source, and deletes their subgraph and vector embeddings in small
    batches to stay under Neptune's per-query memory limit.

    Raises:
        RuntimeError: If any required environment variable is missing.
    """
    missing = [
        name
        for name, val in [
            ("NAMESPACE_ID", NAMESPACE_ID),
            ("DOC_SOURCE_ID", DOC_SOURCE_ID),
            ("TENANT_ID", TENANT_ID),
            ("NEPTUNE_ENDPOINT", NEPTUNE_ENDPOINT),
            ("OPENSEARCH_ENDPOINT", OPENSEARCH_ENDPOINT),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    # Patch BEFORE importing graphrag (see module docstring): the AOSS NEXTGEN
    # mapping fix must replace index_exists in the module namespace before
    # LexicalGraphIndex/VectorStoreFactory bind their own references, and the
    # paginated_search retry is what keeps a transient AOSS 429/5xx during deletion
    # from aborting the task with a masked UnboundLocalError.
    _patch_graphrag_toolkit_for_aoss_nextgen()
    _patch_graphrag_paginated_search_retry()
    _patch_graphrag_bulk_ingest_retry()

    from graphrag_toolkit.lexical_graph import LexicalGraphIndex
    from graphrag_toolkit.lexical_graph.indexing.build.delete_sources import DeleteSources
    from graphrag_toolkit.lexical_graph.storage import GraphStoreFactory, VectorStoreFactory

    neptune_host = NEPTUNE_ENDPOINT.replace("wss://", "").replace("https://", "").rstrip("/")
    opensearch_host = OPENSEARCH_ENDPOINT.replace("https://", "").replace("http://", "").rstrip("/")
    graph_store_uri = f"neptune-db://{neptune_host}:8182"
    vector_store_uri = f"aoss://{opensearch_host}:443"

    logger.info(
        "graph_cleanup_started",
        namespace_id=NAMESPACE_ID,
        doc_source_id=DOC_SOURCE_ID,
        tenant_id=TENANT_ID,
    )

    with (
        GraphStoreFactory.for_graph_store(graph_store_uri) as graph_store,
        VectorStoreFactory.for_vector_store(vector_store_uri, index_names=EMBEDDING_INDEXES) as vector_store,
    ):
        graph_index = LexicalGraphIndex(graph_store, vector_store, tenant_id=TENANT_ID)

        # Find source IDs for this doc source
        sources = graph_index.get_sources(filter={"doc_source_id": DOC_SOURCE_ID})
        if not sources:
            logger.info("no_sources_found", doc_source_id=DOC_SOURCE_ID)
        else:
            source_ids = [s["sourceId"] for s in sources]
            logger.info("sources_found", count=len(source_ids), doc_source_id=DOC_SOURCE_ID)

            # Pass a small batch_size to avoid Neptune's per-query memory limit.
            # Use num_workers=1 to serialize deletions — parallel workers cause
            # ConcurrentModificationException in Neptune when multiple transactions
            # modify the same nodes simultaneously.
            delete_sources = DeleteSources(
                graph_store=graph_index.graph_store,
                vector_store=graph_index.vector_store,
                batch_size=_BATCH_SIZE,
                num_workers=1,
            )
            deleted = delete_sources.delete_source_documents(source_ids)
            logger.info(
                "neptune_cleanup_complete",
                doc_source_id=DOC_SOURCE_ID,
                deleted_count=len(deleted),
            )

    logger.info(
        "graph_cleanup_complete",
        namespace_id=NAMESPACE_ID,
        doc_source_id=DOC_SOURCE_ID,
    )


if __name__ == "__main__":
    main()
