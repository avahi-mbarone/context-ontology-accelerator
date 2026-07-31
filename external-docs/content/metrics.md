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

Before saving, metrics are validated through multiple checks:

| Check | What it Verifies | Severity |
|-------|-----------------|----------|
| SQL Syntax | Expression parses without errors (via sqlglot) | WARNING |
| Table Existence | `sourceTable` exists in the data source catalog | INFO |
| Column Existence | Referenced columns exist in the table | INFO |

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
