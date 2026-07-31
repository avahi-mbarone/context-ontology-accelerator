# Step Functions State Machines

This directory contains ASL (Amazon States Language) definitions for
Step Functions workflows used in the Context Ontology Accelerator.

## Implemented State Machines

### Scan Pipeline (`{prefix}-{env}-scan-pipeline`)

Orchestrates structured datasource discovery and AI-powered metadata enrichment.

**States:**

1. `UpdateStatusDiscovering` — Sets scan job status to `DISCOVERING` in DynamoDB
2. `Discovery` — Invokes Connector Service Lambda to crawl Glue catalog metadata (3 retries, exponential backoff)
3. `UpdateStatusEnriching` — Sets scan job status to `ENRICHING`
4. `Enrichment` — Runs ECS Fargate task for Bedrock-powered metadata enrichment (retries on ECS service exceptions)
5. `UpdateStatusCompleted` — Sets scan job status to `COMPLETED`

**Error handling:** Any step failure catches to `UpdateStatusFailed` → `ScanFailed` (Fail state). The error cause is persisted in the `errorMessage` attribute.

**Timeout:** 1 hour

**Input schema:**

```json
{
  "datasourceId": "DS#<id>",
  "scanJobId": "SCAN#<jobId>",
  "namespaceId": "<namespace>",
  "scanType": "full|incremental"
}
```

## Planned State Machines

- **Ontology Build**: Coordinates ontology construction from enriched metadata
- **Query Execution**: Manages VKG query planning and execution

> Additional state machine definitions will be added as services are implemented.
