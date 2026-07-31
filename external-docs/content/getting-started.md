# Getting Started

## Prerequisites

- Python 3.12 (pinned via `.python-version` — uv will use this automatically)
- Node.js 22+ (for CDK CLI and web-app)
- [pnpm](https://pnpm.io/) (Node package manager — installed via `mise` or `npm install -g pnpm`)
- Docker (for local dev services and container image builds)
- Java 17+ and Gradle (for Smithy codegen)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- AWS CLI v2 (for deployments and ECR auth)

## Initial Setup

```bash
# Clone the repository
git clone <repo-url>
cd ontology-accelerator

# Install uv, sync all packages, set up pre-commit hooks
make setup
```

## Development Workflow

### Format, lint, and test

```bash
# Auto-format code (fixes lint errors + formatting)
make format

# Run linting (ruff + mypy + TypeScript type-check + prettier)
make lint

# Run unit tests (Python pytest + CDK Jest)
make test

# Run integration tests (requires deployed dev stack)
make test-integ
```

### CDK (infrastructure)

```bash
# Build all TS packages and validate CDK stacks
pnpm nx run-many -t build
pnpm --filter coa-infra exec cdk synth

# Deploy to dev environment
make deploy-dev
```

> **CDK CLI:** If you see a version mismatch error, update: `npm install -g aws-cdk@latest`

#### CDK context variables

All stacks use context-driven configuration via `CoaStack` base class:

| Variable                   | Default            | Description                                                    |
|----------------------------|--------------------|----------------------------------------------------------------|
| `resource_prefix`          | `coa`              | Prefix for all resource names                                  |
| `env`                      | `dev`              | Deployment environment                                         |
| `project_tag`              | `semantic-context` | AWS `Project` tag value                                        |
| `vpc_id`                   | (none)             | Import an existing VPC instead of creating one                 |
| `aoss_max_ocu`             | `96`               | Max OCU capacity for OpenSearch Serverless (indexing + search) |
| `aoss_min_ocu`             | `0`                | Min OCU capacity for OpenSearch Serverless (indexing + search) |
| `api_throttle_rate_limit`  | `50`               | API Gateway stage requests-per-second rate limit               |
| `api_throttle_burst_limit` | `100`              | API Gateway stage burst capacity                               |

Resource naming follows `{prefix}-{env}-{name}` (e.g. `coa-dev-neptune`).

#### First-time deployment

Deploying for the first time to a new AWS account requires bootstrapping CDK
and authenticating to ECR Public — see
[Deploying Context Ontology Accelerator](deploying.md) for those one-time steps (both
are also handled automatically by `make deploy-dev`'s preflight checks).

#### Lake Formation bootstrap (required for JDBC data sources)

JDBC sources are provisioned as Lake Formation–governed Glue federated catalogs.
Creating those catalogs requires the federation provisioner's Lambda role to be a
Lake Formation **data-lake admin**. The `LakeFormationAdmin` custom resource
registers it automatically and non-destructively (it appends to the existing
admin list rather than overwriting it).

There is a one-time bootstrap caveat: `PutDataLakeSettings` can only be called by
an existing LF admin once an account already has any admins. So:

- **Greenfield accounts** (no LF admins yet) self-bootstrap — no action needed.
- **Accounts that already have LF admins:** register the custom resource's Lambda
  role as an LF admin once, out-of-band, **before the first deploy**. Otherwise
  JDBC scans fail at `CreateCatalog` with an access-denied error.

See `infra/README.md` (Lake Formation bootstrap) for the exact registration
commands and troubleshooting.

#### Customizing deployments

Pass context overrides via environment variables:

```bash
# Custom prefix
SCL_PREFIX=myproj make deploy-dev

# Import existing VPC
SCL_VPC_ID=vpc-0abc123 make deploy-dev

# Multiple overrides
SCL_PREFIX=acme SCL_VPC_ID=vpc-xyz make deploy-dev
```

#### Deployment architecture

See [Deploying Context Ontology Accelerator](deploying.md) for the full stack list
(16 stacks total), dependency order, and per-stack purpose — CDK resolves
ordering automatically from the dependency graph in `bin/app.ts`.

> **Cost warning:** Neptune + OpenSearch Serverless cost ~$930/mo when idle.
> Destroy stacks when not actively testing — see
> [Deploying Context Ontology Accelerator: Tearing Down](deploying.md) for the
> recommended `make destroy-dev` command.

### Smithy codegen

Requires Java 17+ and Gradle. Generates OpenAPI specs, Python server stubs, and TypeScript client from `.smithy` models.

```bash
make generate
```

If you don't edit `.smithy` files, you don't need to run this.

### Web app (landing page)

```bash
cd packages/web-app
cp public/runtime-config.example.json public/runtime-config.json
# Edit runtime-config.json with your OIDC provider details (authority, clientId)
pnpm install
pnpm dev        # opens at http://localhost:5173
```

> **Authentication required:** The web app uses OIDC authentication. See
> `packages/web-app/README.md` in the repository for full
> configuration and identity provider setup.

## Available Make Targets

| Target             | Description                                                                      |
| ------------------ | -------------------------------------------------------------------------------- |
| `make setup`       | Install uv + pnpm, sync packages, set up pre-commit                              |
| `make generate`    | Run Smithy codegen → populate `smithy-generated/`                                |
| `make format`      | Auto-format Python (ruff) + TypeScript (prettier) via Nx                         |
| `make lint`        | Lint + type-check all packages via Nx                                            |
| `make test`        | Run unit tests via Nx                                                            |
| `make test-integ`  | Run integration tests                                                            |
| `make build`       | Build all packages via Nx                                                        |
| `make deploy-dev`  | Deploy to dev environment via CDK (supports `SCL_PREFIX`, `SCL_VPC_ID` env vars) |
| `make destroy-dev` | Tear down all dev stacks (AgentCore Runtimes, VKG ECS services, DataZone domain, then `cdk destroy --all`) — see the [Deploying guide](deploying.md), "Tearing Down" section |
| `make docs`        | Serve docs site locally (MkDocs)                                                 |

## Next Steps

- See the **[API Reference](#/api-reference)** for the full Control Plane and Data Layer API contracts (sources, metrics, ontologies, namespaces, grants, and the Serve/query endpoints).
- See the [Package Guide](package-guide.md) for how to add or implement a package.
- See `CONTRIBUTING.md` for coding standards and PR process.
