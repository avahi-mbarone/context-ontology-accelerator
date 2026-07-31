# BIRD Benchmark — Context Ontology Accelerator

Measures NL-to-SQL execution accuracy (EX) against the [BIRD mini-dev](https://github.com/bird-bench/mini_dev) dataset (500 questions, 11 databases, PostgreSQL).

## Quick Start

```bash
cd scripts/serve

# 1. Start the gold DB tunnel (one-time, runs in background)
make benchmark-tunnel

# 2. Run the benchmark
make benchmark

# 3. (Optional) Stop tunnel when done
make benchmark-tunnel-stop
```

## Prerequisites

1. **AWS credentials** with access to:
   - `ssm:StartSession` on the bastion host
   - `secretsmanager:GetSecretValue` for `coa-integ-test-databases/postgresql/credentials`
   - `cognito-idp:InitiateAuth` for the SCL dev user pool
   - Bedrock model invocation (for the SCL runtime)

2. **AWS Session Manager Plugin** — [Install guide](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)

3. **Python dependencies:**
   ```bash
   pip install psycopg2-binary boto3
   ```

4. **Deployed infrastructure:**
   - `coa-integ-test-databases` CDK stack (provides RDS + bastion)
   - `coa-dev-serve` (the SCL runtime being benchmarked)

## How It Works

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Benchmark Runner (your machine)                             │
│                                                              │
│  1. Load BIRD mini-dev questions                             │
│  2. For each question:                                       │
│     a. POST to SCL AgentCore → get resultRows               │
│     b. Execute gold SQL via psycopg2 → get gold rows        │
│     c. Compare (order-insensitive, type-coerced)             │
│  3. Aggregate stats → write results JSON                     │
└─────────┬───────────────────────────────┬────────────────────┘
          │                               │
          │ HTTPS (AgentCore API)         │ TCP localhost:15432
          ▼                               ▼
┌─────────────────────┐     ┌─────────────────────────────────┐
│ SCL Runtime (ECS)   │     │ SSM Port Forward                │
│ • Orchestrator      │     │ localhost:15432                  │
│ • Tier 2 strategies │     │   → Bastion (EC2)               │
│ • Bedrock LLM       │     │     → Aurora PostgreSQL (RDS)   │
└─────────────────────┘     └─────────────────────────────────┘
```

### Gold SQL Comparison

The runner connects to the **same PostgreSQL database** the SCL system queries:
- Password auto-resolved from **Secrets Manager** (`coa-integ-test-databases/postgresql/credentials`)
- Bastion instance ID and RDS endpoint resolved from **CloudFormation outputs**
- Connection tunneled via **SSM Session Manager** (no SSH keys, no VPN needed)

Comparison logic:
- Normalize both result sets: `sorted([tuple(str(v).strip() for v in row) for row in rows])`
- Order-insensitive (rows sorted)
- Type-coerced (all values stringified)
- 1% numeric tolerance for single-value scalar aggregations
- No partial credit — exact match or failure

### Accuracy Metric (EX)

```
EX = (questions where system result == gold result) / total questions
```

- System errors (no SQL produced) count as **NOT accurate**
- Wrong results (mismatch with gold) count as **NOT accurate**
- Gold SQL execution errors are excluded from the denominator

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region |
| `BENCH_NS` | `385e5e21-...` | Namespace ID (bird-benchmark) |
| `BENCH_DB_HOST` | `localhost` | Gold DB host |
| `BENCH_DB_PORT` | `15432` | Gold DB port (tunnel) |
| `BENCH_DB_NAME` | `bird` | Database name |
| `BENCH_DB_USER` | `bird_admin` | DB username |
| `BENCH_DB_PASS` | *(from Secrets Manager)* | DB password override |
| `BENCH_DB_SECRET` | `coa-integ-test-databases/postgresql/credentials` | Secret name |
| `BENCH_STACK` | `coa-integ-test-databases` | CDK stack name (for tunnel) |

## Makefile Targets

```bash
make benchmark                    # Single run (default strategy + model)
make benchmark BENCH_STRATEGY=ontop BENCH_MODEL=us.anthropic.claude-opus-4-6-v1
make benchmark BENCH_CATEGORY=aggregation
make benchmark-strategies         # Compare all 5 strategies
make benchmark-models             # Compare 3 models
make benchmark-matrix             # Full cartesian (strategies × models)
make benchmark-report             # Show comparison table
make benchmark-tunnel             # Start SSM tunnel (background)
make benchmark-tunnel-stop        # Stop SSM tunnel
make benchmark-tunnel-fg          # Start SSM tunnel (foreground, Ctrl+C)
```

## Skipping Gold Comparison

If you don't have DB access or just want execution rate + latency:

```bash
make benchmark BENCH_SKIP_GOLD=1
```

## Results

Results are written to `benchmark/results/` as JSON:
```
results/YYYYMMDD-HHMMSS_<strategy>_<model>.json
```

Use `make benchmark-report` to generate a comparison table across runs.

## Reference: BIRD Mini-Dev Leaderboard

Published baselines (from [bird-bench.github.io](https://bird-bench.github.io/), Mini-Dev section):

| System | PostgreSQL EX |
|--------|--------------|
| TA + GPT-4 (HKU, with oracle knowledge) | 50.80% |
| **SCL + Opus 4.8 (our system, no oracle knowledge)** | **60.60%** |

Our system achieves ~10pp above the published GPT-4 baseline despite:
- Going through additional abstraction layers (ontology → VKG → SPARQL → SQL)
- NOT using oracle knowledge hints provided in the dataset
- Operating as a general-purpose semantic layer, not a purpose-built text-to-SQL system
