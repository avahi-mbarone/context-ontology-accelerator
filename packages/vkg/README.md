# Virtual Knowledge Graph (VKG)

Translation-only service wrapping Ontop 5.x. Translates SPARQL queries into SQL using ontology mappings, without connecting to a real database.

## Architecture

- **Ontop 5.x** — SPARQL-to-SQL translator (runs on port 8081 internally)
- **translate-server.py** — Python HTTP facade (port 8080) exposing `/translate` and `/health`
- **H2 in-memory** — schema-only database for Ontop's mapping parser (no real data)

At startup, the entrypoint downloads ontology + mappings from S3, loads the schema into H2, and starts both services.

## Production

The container is built from this Dockerfile and deployed to ECS. Ontology artifacts are fetched from S3 at runtime:

```
s3://{ONTOLOGY_BUCKET}/ontologies/{NAMESPACE}/{VERSION}/
  ├── ontology.ttl      # OWL ontology
  ├── mappings.obda     # Ontop OBDA mappings
  └── schema.sql        # H2 schema for mapping validation
```

To upload artifacts for a namespace:

```bash
aws s3 cp ./ontology.ttl s3://$ONTOLOGY_BUCKET/ontologies/insurance/latest/
aws s3 cp ./mappings.obda s3://$ONTOLOGY_BUCKET/ontologies/insurance/latest/
aws s3 cp ./schema.sql s3://$ONTOLOGY_BUCKET/ontologies/insurance/latest/
```

## Local Testing

Test fixtures are in `tests/fixtures/`. To run the VKG container locally with real S3 artifacts:

```bash
# Build the image
docker build -t coa-vkg:local packages/vkg/

# Run with real S3 artifacts (requires AWS credentials)
docker run -d --name coa-vkg -p 8090:8080 \
  -e ONTOLOGY_BUCKET=coa-dev-neptune-data-123456789012 \
  -e NAMESPACE=insurance \
  -e VERSION=latest \
  -e AWS_DEFAULT_REGION=us-east-1 \
  coa-vkg:local
```

### Test the translation endpoint

```bash
curl -s http://localhost:8090/sparql/translate \
  -H "Content-Type: application/json" \
  -d '{"sparql": "SELECT ?x WHERE { ?x a <http://example.org/insurance#Claim> }", "namespace": "insurance"}'
```

### Test fixtures

| File | Purpose |
|------|---------|
| `tests/fixtures/insurance.obda` | Sample OBDA mappings for the insurance namespace (Claim → claims table) |
| `tests/fixtures/schema.sql` | H2 schema mirroring Athena `insurance_lake.claims` for Ontop validation |

## Container Startup and Troubleshooting

### S3 download retry

At startup, the entrypoint downloads ontology artifacts from S3 with **3 attempts** and exponential backoff (2s, 4s, 8s delays). Expected log output during a transient failure:

```
[VKG] Downloading artifacts...
[VKG] WARN: S3 download attempt 1/3 failed — retrying in 2s
[VKG] WARN: S3 download attempt 2/3 failed — retrying in 4s
```

If all 3 attempts fail, the container enters **degraded mode** (503 on all `/sparql/translate` requests) and logs:

```
[VKG] WARN: Failed to download from S3 after 3 attempts — starting in degraded mode
```

**Common S3 issues:**
- Verify the S3 path exists: `aws s3 ls s3://$ONTOLOGY_BUCKET/ontologies/$NAMESPACE/$VERSION/`
- Check IAM permissions on the task role (needs `s3:GetObject` on `ontologies/*`)
- Confirm the bucket name matches the CDK-deployed bucket

**Recovery:** Fix the S3 artifacts, then restart the task. The health check will replace degraded containers automatically (see below).

## Health Check and Self-Healing

### /health endpoint

| Status | Meaning |
|--------|---------|
| `200` | Ontop loaded, ready to translate |
| `503` | Degraded mode (ontology not loaded) |

### Self-healing mechanism

The Docker/ECS health check calls `curl -sf http://localhost:8080/health`. Since `-f` fails on non-2xx responses, a container stuck in degraded mode (returning 503) will be marked **UNHEALTHY** by ECS after 5 consecutive failures (30s interval = ~2.5 min).

ECS then replaces the task automatically. The replacement container retries S3 download from scratch.

**Health check parameters:**
- Interval: 30s
- Timeout: 10s
- Start period: 180s (grace period for S3 download + Ontop initialization)
- Retries: 5

### Checking container health

```bash
# From inside the container
curl -sf http://localhost:8080/health

# From ECS (check task health status)
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN \
  --query 'tasks[0].containers[0].healthStatus'
```

### Expected lifecycle during reload failures

1. EventBridge triggers reload Lambda
2. Lambda force-deploys the ECS service (rolling update)
3. New task starts, retries S3 download (3 attempts)
4. If S3 fails: container enters degraded mode → health check fails after ~2.5 min → ECS replaces
5. Cycle repeats until S3 artifacts are available
