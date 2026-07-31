# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Neptune Analytics graph client for openCypher queries."""

import json
import os
import subprocess
import urllib.parse
import urllib.request
from urllib.parse import urlparse


class NeptuneAnalyticsClient:
    """Executes openCypher queries against a Neptune Analytics endpoint."""

    def __init__(self, endpoint: str | None = None):
        """Resolve and validate the Neptune Analytics endpoint URL.

        Args:
            endpoint: Endpoint URL; falls back to ``NEPTUNE_ANALYTICS_URL`` or localhost.

        Raises:
            ValueError: If the resolved endpoint is not an http(s) URL with a host.
        """
        ep = endpoint if endpoint else os.getenv("NEPTUNE_ANALYTICS_URL", "http://localhost:9200")
        parsed = urlparse(ep)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid Neptune endpoint {ep!r}: must be an http(s) URL with a host")
        self.endpoint = ep.rstrip("/")

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Run an openCypher query and return its result rows.

        If ``params`` is provided, the values are passed via the ``parameters``
        form field so that ``$name`` references in the query are bound safely
        without string interpolation. Falls back to ``curl`` when the URL-encoded
        request is rejected (e.g. for large queries).

        Args:
            cypher: The openCypher query text.
            params: Optional parameter bindings for ``$name`` references.

        Returns:
            The list of result rows, or an empty list on unparseable responses.
        """
        q = " ".join(cypher.split())
        form: dict = {"query": q}
        if params:
            form["parameters"] = json.dumps(params)
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(f"{self.endpoint}/openCypher", data=data)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("results", [])
        except urllib.error.HTTPError:
            # Fall back to curl for large queries (URL encoding limits)
            argv = [
                "curl",
                "-s",
                f"{self.endpoint}/openCypher",
                "--data-urlencode",
                f"query={q}",
            ]
            if params:
                argv += ["--data-urlencode", f"parameters={json.dumps(params)}"]
            r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            try:
                return json.loads(r.stdout).get("results", [])
            except (json.JSONDecodeError, AttributeError):
                return []

    def vector_upsert(self, node_id: str, vector: list[float]) -> bool:
        """Attach or replace an embedding vector on a graph node.

        Args:
            node_id: Internal id of the node to update (bound as a query parameter).
            vector: Embedding values to store on the node.

        Returns:
            True if the upsert reported success, otherwise False.
        """
        # Vector values are floats formatted with a fixed numeric format, so
        # they cannot contain Cypher-breaking characters. ``node_id`` is
        # user-controlled and MUST be passed as a bound parameter.
        vec_str = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
        q = (
            "MATCH (n) WHERE id(n) = $node_id "
            f"CALL neptune.algo.vectors.upsert(n, {vec_str}) "
            "YIELD success RETURN success"
        )
        results = self.query(q, params={"node_id": node_id})
        return bool(results and results[0].get("success"))

    def vector_search(self, node_id: str, top_k: int = 5) -> list[dict]:
        """Find the nearest neighbors of a node by embedding similarity.

        Args:
            node_id: Internal id of the query node (bound as a query parameter).
            top_k: Number of nearest neighbors to return.

        Returns:
            Neighbor rows with id, local name, labels, and similarity score;
            empty if no supported vector procedure returns results.
        """
        # ``proc`` is drawn from a fixed hardcoded allowlist; ``top_k`` is
        # coerced to an int before formatting; ``node_id`` is bound as a
        # parameter.
        top_k_int = int(top_k)
        for proc in ("neptune.algo.vectors.topK.byNode", "neptune.algo.vectors.topKByNode"):
            results = self.query(
                "MATCH (n) WHERE id(n) = $node_id "
                f"CALL {proc}(n, {{topK: {top_k_int}}}) YIELD node, score "
                "RETURN id(node) AS nid, node.localName AS name, "
                "labels(node) AS labels, score",
                params={"node_id": node_id},
            )
            if results:
                return results
        return []
