# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build graphrag-toolkit GraphStore and VectorStore from config URIs.

Mirrors the connection pattern used by kg-build (graph_build.py:170-199)
so that retrieval targets the same stores that ingestion wrote to.

Connection lifecycle: stores are created once at startup and held for the
process lifetime (same pattern as other clients in clients/factory.py).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def build_graph_store(graph_store_uri: str):
    """Build a graphrag-toolkit GraphStore from a Neptune URI.

    Args:
        graph_store_uri: "neptune-db://<host>:8182" (matches kg-build)

    Note: the toolkit's ``create_config`` passes ``retries`` as an explicit Config
    kwarg, so it CANNOT be overridden via ``for_graph_store(config=...)`` (doing so
    raises ``Config() got multiple values for keyword argument 'retries'``). The
    transient ``ConnectionClosedError`` retry is therefore handled one layer up, at
    the strategy invocation (see ``baseline_retriever``), not here.
    """
    from graphrag_toolkit.lexical_graph.storage import GraphStoreFactory

    logger.info("building_graph_store", uri=graph_store_uri)
    return GraphStoreFactory.for_graph_store(graph_store_uri)


def build_vector_store(vector_store_uri: str, index_names: list[str] | None = None):
    """Build a graphrag-toolkit VectorStore from an OpenSearch Serverless URI.

    Args:
        vector_store_uri: "aoss://<endpoint>" (matches kg-build)
        index_names: Optional list of index names to scope queries.
    """
    from graphrag_toolkit.lexical_graph.storage import VectorStoreFactory

    kwargs = {}
    if index_names is not None:
        kwargs["index_names"] = index_names

    logger.info("building_vector_store", uri=vector_store_uri)
    return VectorStoreFactory.for_vector_store(vector_store_uri, **kwargs)
