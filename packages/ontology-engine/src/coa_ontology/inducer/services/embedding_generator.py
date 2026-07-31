# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Client for the embedding-generator service."""

import httpx


class EmbeddingGeneratorClient:
    """HTTP client for the embedding-generator service."""

    def __init__(self, base_url: str):
        """Store the base URL of the embedding-generator service.

        Args:
            base_url: Root URL of the embedding-generator HTTP API.
        """
        self.base_url = base_url

    def generate_lexical(
        self,
        ontology_id: str,
        classes: list[dict],
        backend: str | None = None,
        store: bool = True,
    ) -> tuple[list[dict], str]:
        """Request lexical embeddings for a batch of ontology classes.

        Args:
            ontology_id: Ontology the classes belong to (empty for ad-hoc embeddings).
            classes: Class payloads (URIs, labels, comments) to embed.
            backend: Optional embedding backend override; defaults to the service default.
            store: Whether the service should persist the generated vectors.

        Returns:
            The per-class embedding results and the backend id that produced them.
        """
        payload = {
            "ontology_id": ontology_id,
            "embedding_type": "lexical",
            "classes": classes,
            "run_async": False,
            "store": store,
        }
        if backend:
            payload["backend"] = backend
        with httpx.Client(timeout=120) as client:
            resp = client.post(f"{self.base_url}/generate/", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", []), data.get("backend", "default")
