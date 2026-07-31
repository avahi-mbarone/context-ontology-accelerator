# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Data Treehouse (chrontext) — potential alternative strategy for time-series queries.

TODO: Evaluate viability as a Tier 2 strategy.

Product: https://www.data-treehouse.com/
GitHub: https://github.com/DataTreehouse/chrontext

What it is:
- Rust-based hybrid query engine (chrontext + maplib)
- Combines SPARQL triplestore with pushdown to analytical DBs
- Targets time-series/IoT contextualization (not general SPARQL→SQL)
- Supports PostgreSQL, DuckDB, BigQuery, OPC UA
- Uses custom SQL templates (NOT R2RML)
- Has a SHACL engine and DataLog implementation

How it differs from Ontop:
- Not a general-purpose VKG — focused on federated time-series queries
- Does NOT consume R2RML mappings (uses its own template format)
- Pushes aggregations into backend DBs (similar concept, different mechanism)
- Rust (no JVM) — deployment advantage

Evaluation questions:
1. Can it handle general NL→SPARQL→SQL translation (not just time-series)?
2. Can it consume our R2RML mappings, or would we need a new mapping format?
3. Performance comparison vs Ontop on the BIRD benchmark?
4. Does the SHACL engine add value for pre-query validation?
5. Is the DataLog implementation relevant for complex query patterns?

If viable, implement as: StructuredQueryStrategy with name="data_treehouse"
"""
