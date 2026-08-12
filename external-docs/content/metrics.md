# Metrics

Metrics define reusable business calculations with SQL expressions. Once defined, metrics are resolved by the query engine when users ask business questions — ensuring consistent, validated answers across all consumers.

!!! tip "Full request/response schemas"
    For the complete request/response schema for every Metrics endpoint, see
    the **[API Reference](#/api-reference)** (Control Plane API → Metric
    service) — it's generated directly from the API contract and always
    current.

## What is a Metric?

A metric is a named business calculation that includes:

- **Name**: human-readable identifier (e.g. `total_revenue`, `monthly_active_users`)
- **Description**: what the metric measures and any business context
- **Expression**: SQL formula in one or more SQL dialects
- **Data Source**: which database source provides the underlying data
- **Source Table**: the primary table the metric aggregates

## Creating Metrics

### Via the Web App

1. Navigate to your namespace → **Metrics** → **Create Metric**
2. Fill in:
   - **Name**: unique within the namespace
   - **Description**: explain what this metric measures
   - **Data Source**: select an approved source
   - **Source Table**: the table containing the data
   - **Expression**: SQL aggregation formula (e.g. `SUM(orders.total_amount)`)
   - **Dialect**: which SQL engine the expression targets (Trino, PostgreSQL, etc.)
3. Click **Validate** to check syntax and schema references before saving
4. Click **Create**

### Via the API

`POST /namespaces/{namespaceId}/metrics` with `name`, `description`,
`expression.dialects`, `dataSourceId`, and `sourceTable` — see **CreateMetric**
in the [API Reference](#/api-reference) for the full request/response schema.

## Metric Validation

Before saving, metrics are validated through multiple checks. Validation is
split into **hard** checks (reject the request with `400`) and **soft** checks
(publish the metric and return a warning). The guiding rule: a check is hard
only when the metric would be provably broken or unsafe; anything that the
query engine can independently guard at serve time stays soft so onboarding a
metric is never blocked by a false positive.

| Check | What it Verifies | Outcome |
|-------|-----------------|---------|
| Data source exists | `dataSourceId` resolves to a source in the namespace, in an `APPROVED`/`COMPLETED` status | **Hard — `400`** |
| Table existence | `sourceTable` is present in the source's catalog | **Hard — `400`** when absence is provable (see below) |
| DML/DDL in expression | Expression contains data-modifying or administrative SQL (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `GRANT`, `COPY`, `CALL`, …) | **Hard — `400`** (security) |
| SQL syntax | `SELECT`-shaped expression parses without errors (via sqlglot) | **Soft — WARNING** |
| Column existence | Referenced columns exist in the table | **Soft — INFO** |

### SQL Expression: Soft vs. Hard

The SQL expression is checked for **safety** (hard) and **shape** (soft):

- **DML/DDL is hard-blocked (`400`).** Any data-modifying or administrative
  statement is rejected and never persisted, whether it is standalone, stacked
  (`SELECT 1; TRUNCATE x`), CTE-nested, or an unrecognized verb. Metrics are
  read-only by definition.
- **Non-`SELECT` fragments publish with a warning.** An expression like
  `COUNT(*)` is a legal aggregation fragment, not a full statement — it is
  accepted and flagged as a soft warning rather than rejected.
- **Parse errors publish with a warning.** An expression sqlglot cannot parse
  is accepted with a soft warning instead of a `400`.

Fragments and unparseable expressions are soft because the **serve-time SQL
firewall** independently re-validates every expression before execution and
rejects anything unsafe or unparseable (fail-closed). Blocking at create time
too would only reject valid-but-unusual expressions without adding safety —
so create stays permissive and serve stays strict (defense-in-depth).

### Source Table Existence: Provable Absence Only

`sourceTable` is hard-validated, but only when its absence can be **proven**:

- **`400` (provable absence)** — the source's catalog was read successfully,
  it enumerates at least one table for the source, and the declared
  `sourceTable` is not among them. The web app only offers catalog tables, so
  the API enforces the same constraint for direct/bulk callers.
- **`503` (catalog unavailable)** — the catalog lookup was configured but its
  read failed. Enforcement is impossible on a source that should be readable,
  so the request fails closed rather than silently accepting.
- **Soft warning (unprovable absence)** — the namespace has no provisioned
  catalog lookup, or the catalog is readable but empty for the source (e.g. a
  `COMPLETED` source whose assets are not yet steward-approved). Absence
  cannot be proven, so the metric publishes with an `INFO` warning
  (pre-existing behavior).

### Validate Without Saving

`POST /namespaces/{namespaceId}/metrics/validate` accepts the same body as
**CreateMetric** without persisting anything — see **ValidateMetric** in the
[API Reference](#/api-reference).

Response:
```json
{
  "warnings": [
    {"field": "column_reference", "message": "Column 'total_amount' not found", "severity": "INFO"}
  ]
}
```

## Multi-Dialect Expressions

Metrics support multiple SQL dialects so the same business metric works across different engines:

```json
{
  "expression": {
    "dialects": [
      {"dialect": "TRINO", "expression": "SUM(orders.total_amount)"},
      {"dialect": "POSTGRESQL", "expression": "SUM(orders.total_amount)"},
      {"dialect": "REDSHIFT", "expression": "SUM(orders.total_amount::DECIMAL)"}
    ]
  }
}
```

The query engine selects the appropriate dialect based on the underlying data source engine.

## Bulk Import (OSI Format)

For teams with many metrics, import in bulk using the OSI v1.0 format — the
schema originally published as **Open Semantic Interchange (OSI)**, now
developed at the Apache Software Foundation as
[**Apache Ossie (incubating)**](https://github.com/apache/ossie). The
vendor-agnostic metric/semantic-model spec is the same lineage; Ontology
Accelerator's importer/exporter currently targets OSI v1.0, predating the
Ossie rename:

1. Navigate to **Metrics** → **Import**
2. Upload a YAML/JSON file conforming to the OSI schema
3. Context Ontology Accelerator validates and creates all metrics in batch

## How Metrics Are Used in Queries

When a user asks a question like *"What was total revenue last quarter?"*, the query engine:

1. **Tier 1 (Metric Resolution)**: Matches the question to the `total_revenue` metric via semantic similarity
2. Retrieves the metric's SQL expression and source table
3. Generates a full query with the appropriate time filter
4. Executes through the SQL Firewall (enforcing table/column access controls)

## Managing Metrics

| Operation | API | Description |
|-----------|-----|-------------|
| List | `GET /namespaces/{ns}/metrics` | All metrics in the namespace |
| Get | `GET /namespaces/{ns}/metrics/{name}` | Single metric detail |
| Update | `PUT /namespaces/{ns}/metrics/{name}` | Modify expression, description |
| Delete | `DELETE /namespaces/{ns}/metrics/{name}` | Remove a metric |
| Validate | `POST /namespaces/{ns}/metrics/validate` | Check without saving |

## Best Practices

- **Descriptive names**: use `snake_case` names that clearly state what's measured
- **Rich descriptions**: include units, time granularity, and business context — these help the AI match questions to metrics
- **Validate first**: always validate before creating to catch schema issues early
- **One metric per calculation**: avoid combining multiple business concepts in a single metric expression
