#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Clean old P&C Insurance v1 artifacts from Neptune Analytics graph."""

import json

import boto3
from botocore.config import Config

GRAPH_ID = "g-6k170dxt85"
REGION = "us-east-1"
URI = "http://example.org/pc-insurance/"

client = boto3.client(
    "neptune-graph",
    region_name=REGION,
    config=Config(retries={"total_max_attempts": 1, "mode": "standard"}, read_timeout=None),
)


def oc(query, params=None):
    kw = {
        "graphIdentifier": GRAPH_ID,
        "queryString": " ".join(query.split()),
        "language": "OPEN_CYPHER",
    }
    if params:
        kw["parameters"] = params
    r = client.execute_query(**kw)
    return json.loads(r["payload"].read())


# Count before
for label in ("Class", "Property"):
    r = oc(
        f"MATCH (o:Ontology)-[:DEFINES]->(n:{label}) WHERE id(o) = $uri RETURN count(n) AS c",
        {"uri": URI},
    )
    print(f"  {label} count: {r['results'][0]['c']}")

r = oc("MATCH (e:Embedding) WHERE e.ontology_id = $uri RETURN count(e) AS c", {"uri": URI})
print(f"  Embedding count: {r['results'][0]['c']}")

# Delete embeddings linked via DEFINES->HAS_EMBEDDING
r = oc(
    "MATCH (o:Ontology)-[:DEFINES]->(e)-[:HAS_EMBEDDING]->(emb:Embedding) "
    "WHERE id(o) = $uri DETACH DELETE emb RETURN count(emb) AS c",
    {"uri": URI},
)
print(f"Deleted HAS_EMBEDDING embeddings: {r['results'][0]['c']}")

# Delete DEFINES children
r = oc(
    "MATCH (o:Ontology)-[:DEFINES]->(e) WHERE id(o) = $uri DETACH DELETE e RETURN count(e) AS c",
    {"uri": URI},
)
print(f"Deleted DEFINES entities: {r['results'][0]['c']}")

# Delete embeddings by ontology_id property
r = oc(
    "MATCH (emb:Embedding) WHERE emb.ontology_id = $uri DETACH DELETE emb RETURN count(emb) AS c",
    {"uri": URI},
)
print(f"Deleted ontology_id embeddings: {r['results'][0]['c']}")

# Delete ontology node
r = oc(
    "MATCH (o:Ontology) WHERE id(o) = $uri DETACH DELETE o RETURN count(o) AS c",
    {"uri": URI},
)
print(f"Deleted ontology node: {r['results'][0]['c']}")

# Verify
r = oc("MATCH (o:Ontology) WHERE id(o) STARTS WITH 'http://example.org/pc-insurance' RETURN count(o) AS c")
print(f"Remaining pc-insurance ontologies: {r['results'][0]['c']}")
print("Graph cleanup complete.")
