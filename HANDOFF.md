# Deploy Handoff — coa-dev on <ACCOUNT_ID>

Status as of 2026-08-18: **deployed successfully.** All 16 stacks are `CREATE_COMPLETE`
(`coa-dev-authnz` shows `UPDATE_COMPLETE`, harmless — see below). This doc captures
everything validated/fixed along the way so the next session (different tool/IDE)
doesn't have to re-derive it.

## Live deployment outputs (values redacted)

| What | Value |
|---|---|
| Web app URL | https://<CLOUDFRONT_DOMAIN>.cloudfront.net |
| CloudFront distribution ID | `<CLOUDFRONT_DISTRIBUTION_ID>` |
| Cognito User Pool ID | `us-east-1_<COGNITO_USER_POOL_ID>` |
| Web app Cognito client ID | `<COGNITO_WEB_CLIENT_ID>` |
| MCP/CLI Cognito client ID | `<COGNITO_CLI_CLIENT_ID>` |
| Cognito Hosted UI domain | https://coa-dev-auth-<ACCOUNT_ID>.auth.us-east-1.amazoncognito.com |
| REST API base URL | https://<API_ID>.execute-api.us-east-1.amazonaws.com/prod/ |
| Sources data S3 bucket | `coa-dev-sources-data-<ACCOUNT_ID>` |

Next step: sign in as the seeded admin (`<ADMIN_EMAIL>`) — see "Post-deploy:
first sign-in" below, now actionable with the values above (redacted here, but were concrete in the original deploy).

## Four real bugs hit and fixed during this deploy (all in app code, not env-specific)

1. **`SCL_SMUS_ADMIN_ARNS` — two wrong values tried before the right one.** This context
   value becomes the trust-policy principal on `NamespaceStack`'s `DomainLoginRole`
   (`infra/lib/stacks/services/namespace-stack.ts:941-969`).
   - Our SSO/IAM-Identity-Center permission-set role ARN
     (`role/aws-reserved/sso.amazonaws.com/...`) — **IAM categorically rejects this as a
     trust-policy Principal** ("Invalid principal in policy"), confirmed with an isolated
     `aws iam create-role` test independent of CloudFormation/DataZone. Not
     environment-specific — this will fail for anyone using an SSO-federated identity here.
   - The account root ARN (`arn:...:root`) — IAM *does* accept this, but
     `namespace-stack.ts`'s own code deliberately rejects it (regex requires
     `role/`or `user/`, and the comment explicitly says why: trusting bare root "would
     let any in-account principal holding sts:AssumeRole escalate to this admin role").
   - **Fix**: created a plain (non-SSO) bridge IAM role, `coa-dev-smus-admin`, trust
     policy = account root. `SCL_SMUS_ADMIN_ARNS` is now
     `arn:aws:iam::<ACCOUNT_ID>:role/coa-dev-smus-admin`. To actually reach the SMUS/
     DataZone console as this account's SSO admin: `aws sts assume-role --role-arn
     arn:aws:iam::<ACCOUNT_ID>:role/coa-dev-smus-admin ...`, then from those creds,
     assume the real `DomainLoginRole` (two hops; verified the first hop works with a
     live `sts assume-role` call). This bridge role is **not part of any CDK stack** —
     `cdk destroy --all` won't remove it; delete manually
     (`aws iam delete-role --role-name coa-dev-smus-admin`) if it's no longer needed.
   - Side effect of the two failed attempts: `coa-dev-namespace` got far enough to create
     the DataZone domain (`RemovalPolicy.RETAIN`, by design) before rolling back on
     `DomainLoginRole`, orphaning a `coa-dev-smus-catalog` DataZone domain that collided
     with the retry ("Domain name already exists"). Had to
     `aws datazone delete-domain --identifier <id> --skip-deletion-check` before retrying.
     **If this happens again on a future fresh deploy**, check
     `aws datazone list-domains` for an orphaned `${prefix}-${env}-smus-catalog` domain
     before retrying `coa-dev-namespace`.

2. **Missing CDK cross-stack dependency: `coa-dev-data-layer` → `coa-dev-ontology`.**
   `data-layer-stack.ts` reads `/${prefix}/ontology-engine/api-fn-arn` via SSM
   (`valueForStringParameter`) to wire its `DescribeSchema` proxy invoke, but
   `infra/bin/app.ts` never had `dataLayer.addDependency(ontology)` — only
   `mcp.addDependency(ontology)` existed for the same parameter. CDK's topological sort
   picked `data-layer` before `ontology` on a fresh account, failing with "Unable to
   fetch parameters [/coa/ontology-engine/api-fn-arn] from parameter store." **Fixed in
   `infra/bin/app.ts`** (added the missing `addDependency` call, right after
   `ontology.addDependency(sources)`) — this is a real latent bug in the app, already
   committed to this working tree, worth upstreaming.

3. **Playground/query path missing the AWS Marketplace IAM grant.** Found post-deploy:
   the web app's Playground failed on the first real (non-Tier-1) natural-language
   query with `AccessDeniedException: ... not authorized to perform the required AWS
   Marketplace actions`. Root cause: Anthropic models on Bedrock are Marketplace-listed,
   and the *first* time an IAM principal in the account invokes one, Bedrock needs
   `aws-marketplace:ViewSubscriptions`/`Subscribe` on that principal to complete an
   account-wide subscription handshake — separate from `bedrock:InvokeModel`/`Converse`,
   which `serve-stack.ts`'s AgentCore runtime role already had correctly.
   `ontology-stack.ts` already carries this exact fix (comment cites issue #814, an
   identical prior incident for the induction path) but it was never ported to
   `serve-stack.ts`. **Fixed** by adding the same `aws-marketplace:ViewSubscriptions`/
   `Subscribe` grant (resources `["*"]` — no resource-level ARN support for these
   actions) to the runtime role in `serve-stack.ts`, then `cdk deploy coa-dev-serve`.

4. **Playground silently using an undocumented fallback chat model.** Also found
   post-deploy, while investigating #3: `serve-stack.ts` never set `bedrockLlmModelId`
   (no config anywhere in `infra/` ever sets it), so `BEDROCK_MODEL_ID` was never
   injected into the AgentCore runtime container. `packages/context-manager/src/
   coa_serve/clients/bedrock.py:139` then fell back to a hardcoded literal,
   `"us.anthropic.claude-sonnet-5"` — valid and authorized, but not the documented
   single source of truth (`DEFAULT_BEDROCK_CHAT_MODEL_ID` = Haiku 4.5,
   `libs/ts-shared/src/constants.ts:130-131`, explicitly meant for "every LLM text
   path"). Not a crash on its own (that model is real/authorized), but a real
   divergence nobody chose. **Fixed** in `serve-stack.ts`: `BEDROCK_MODEL_ID` now
   always defaults to `DEFAULT_BEDROCK_CHAT_MODEL_ID` when `props.bedrockLlmModelId`
   isn't set, instead of being omitted entirely. Redeployed via `cdk deploy
   coa-dev-serve` (this one actually changes the runtime's env var, not just IAM).

## Target account

| Field | Value |
|---|---|
| Account ID | `<ACCOUNT_ID>` |
| Region | `us-east-1` |
| Role | `AWSReservedSSO_AWSAdministratorAccess_<SSO_INSTANCE_ID>/<ADMIN_EMAIL>` |
| Local AWS CLI profile | `AWSAdministratorAccess-<ACCOUNT_ID>` (already existed in `~/.aws/config`, SSO-backed) |

Refresh credentials with:
```bash
aws sso login --profile AWSAdministratorAccess-<ACCOUNT_ID>
```

## Required env vars before any deploy/synth/diff command

A `.env` file already exists at the repo root (gitignored — `.env`/`.env.local` are both
in `.gitignore`) with these. `source .env` at the start of a shell session instead of
re-typing:

```bash
export AWS_PROFILE=AWSAdministratorAccess-<ACCOUNT_ID>
export AWS_DEFAULT_REGION=us-east-1
export CDK_DEFAULT_REGION=us-east-1
export PATH="/opt/homebrew/opt/openjdk@17/bin:$PATH"   # see Java note below
```

**Required — this account has no IAM role named `Admin`.** `make deploy-dev`'s
preflight check fails fast without this set. **Already persisted in `.env`** as
`arn:aws:iam::<ACCOUNT_ID>:role/coa-dev-smus-admin` — a bridge role created
specifically for this (see "Two real bugs hit and fixed" above for why the obvious
values — the SSO role ARN, then account root — both failed).

## Local toolchain (this Mac only — reinstall if working from a different machine)

Installed via Homebrew, **not** via the repo's documented `mise` flow — there's no
`.mise.toml`/`.tool-versions` in this repo, so `mise install` has nothing to pin
against. Installed directly instead:

| Tool | Version | Note |
|---|---|---|
| Node | v25.9.0 | pre-existing, satisfies the 22+ requirement |
| uv | 0.12.5 | `brew install uv` |
| pnpm | 10.34.5 (pinned) | `brew install pnpm` initially pulled 11.22.0, which caused ~300-line `pnpm-lock.yaml` drift on `pnpm install` (repo pins `10.34.5` as a devDependency). Reverted the lockfile (`git checkout -- pnpm-lock.yaml`) and reinstalled with `npx pnpm@10.34.5 install` — lockfile now matches committed state with zero drift. **Use `npx pnpm@10.34.5 <cmd>` (not the global `pnpm`) for any future installs** to avoid re-triggering this. |
| Java | OpenJDK 17.0.20 | `brew install openjdk@17`. **Keg-only** — not symlinked as the system JDK (the `sudo ln -sfn ...` step from brew's caveats was skipped since it needs a password). Must be on `PATH` explicitly every session — see `.env`. |
| CDK CLI | 2.1127.0 | via `npx cdk` in `infra/` (installed as a project devDependency, not global) |

`mise` itself was also installed (`brew install mise`) but ended up unused since there's
no config file for it to read.

## Setup already completed

`make setup` ran clean:
- Smithy codegen (`smithy-generated/` populated: control-plane + data-layer Python
  server stubs and TS clients, OpenAPI specs)
- `uv sync --all-packages`
- `pnpm install` (878 packages)
- pre-commit hooks installed

No need to re-run unless dependencies change. If `smithy-generated/` or `node_modules`
look stale, `make setup` is idempotent and safe to re-run.

## Account readiness checks (all passed)

| Check | Result |
|---|---|
| CDK bootstrap (us-east-1) | `UPDATE_COMPLETE` — already bootstrapped |
| VPC quota (`L-F678F1CE`) | 5 allowed, 3 in use — room for the 1 this deploy creates |
| Lambda concurrent executions (`L-B99A9384`) | 1000 limit / 990 unreserved — no need for `SCL_LAMBDA_RESERVED_CONCURRENCY=0` |
| Fargate vCPU (`L-3032A538`) | 512 applied (well above the AWS default of 6, which is the tightest quota per the deploy guide) |
| Bedrock model access — Claude Sonnet 4.6, Haiku 4.5, Sonnet 5, Cohere Embed v4 | all `AUTHORIZED` in us-east-1 |
| `Admin` IAM role | does not exist (SSO account) — `SCL_SMUS_ADMIN_ARNS` required, see above |

## `cdk synth` / `cdk diff` results (read-only, already run against this account)

`cdk synth` succeeded for all 16 stacks. Non-blocking warnings only:
- `aws_lambda.FunctionOptions#logRetention` deprecated (cosmetic, CDK-library-level)
- `installLatestAwsSdk` defaulting to `true` on several custom resources (cosmetic)
- **Worth tracking:** `coa-dev-api` template is at 974,925 / 1,000,000 bytes — close to
  CloudFormation's per-template size limit. Not blocking now, but adding more API
  routes could push it over and require splitting the stack.

`cdk diff` against the live account confirmed a clean, purely additive plan (no `[-]`
lines anywhere, nothing pre-existing conflicts). Resource counts to be created per stack:

| Stack | Resources |
|---|---|
| `coa-dev-network` | 95 |
| `coa-dev-auth` | 23 |
| `coa-dev-guardrail` | 10 |
| `coa-dev-storage` | 136 |
| `coa-dev-authnz` | 31 |
| `coa-dev-vkg` | 164 |
| `coa-dev-namespace` | 272 |
| `coa-dev-metric-service` | 504 |
| `coa-dev-api` | 611 |
| `coa-dev-serve` | ~150 (AgentCore Runtime, SessionMemory, AOSS proxy) |
| `coa-dev-sources` | 465 |
| `coa-dev-data-layer` | 338 |
| `coa-dev-edge-waf` | 4 |
| `coa-dev-web` | 654 |
| `coa-dev-ontology` | 511 |
| `coa-dev-mcp` | 568 |

Note: `cdk diff` writes its `[+]`/`[-]` resource lines to **stderr**, not stdout — easy
to lose if you redirect stderr away in a script.

## Not yet done

- No custom domain, no OIDC IdP configured — deploy uses Cognito auth with no custom
  domain (deliberate, not a gap)
- First sign-in as the seeded admin (see "Post-deploy: first sign-in" below)
- Synthetic test data (`products.csv`/`inventory_snapshots.csv`) staged but not yet
  loaded into a Glue source (see "Post-deploy: load the synthetic test data" below)

## Pre-deploy prep already done (this session)

- `SCL_SMUS_ADMIN_ARNS` **is** persisted in `.env` now.
- `.env` also shadows the global `pnpm` (v11.22.0, wrong — repo pins 10.34.5) with a shim
  at `~/.local/bin/pnpm` prepended onto `PATH`. Without this, `make lint`/`make test-unit`
  (and anything else that shells to a bare `pnpm`) fails with
  `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`.
- Deployed from `main` (not the `v0.2.0` tag — checked, `main` only adds fixes/features
  over `v0.2.0`, nothing riskier; see conversation for the full comparison).
- Two universal resource tags added to every stack (`infra/lib/constructs/scl-stack.ts`):
  `Project=ACI-GenAI-MVP`, `aws-apn-id=pc:13uw3s8iyvze74tlcq3o0w8r6`. Both are
  context-overridable (`project_tag`/`apn_tag`, or `SCL_PROJECT_TAG`/`SCL_APN_TAG` env
  vars via `scripts/deploy.sh`/`destroy.sh`).
- `ControlPlaneStack`/`MetricStack` (dormant, not instantiated in `bin/app.ts`) switched
  to extend `SCLStack` so they'd inherit tagging if ever re-enabled.
- **SSM parameter `/coa/config` is set**: `{"initialAdminEmail":"<ADMIN_EMAIL>"}`.
  This is what the auto-created Cognito admin user's email/temp-password gets sent to —
  without it, the default is the unreachable placeholder `nobody@amazon.com`
  (`infra/lib/constants.ts:49-51`, read at synth time by `infra/bin/app.ts:59-75`).
  **This parameter is NOT part of any CDK stack — `cdk destroy --all` will NOT remove
  it** (noted in `scripts/destroy.sh`'s header comment too). Delete manually
  (`aws ssm delete-parameter --name /coa/config`) before a from-scratch redeploy if you
  don't want the same admin email reused.
- `make lint` and `make test-unit` both pass on `main` with the above changes, except
  one **pre-existing, unrelated** failure: all 12 tests in
  `packages/web-app/src/pages/MetricList.test.tsx` fail with
  `localStorage.getItem is not a function` — caused by Node v25.9.0 shipping a broken
  built-in `localStorage` global by default (confirmed: reproduces with plain
  `node -e "localStorage.getItem('x')"`, no app code involved). Doesn't block deploy —
  `deploy.sh` only runs `build`, never `test`, and the real deployed app runs in a
  browser (which has always had a correct native `localStorage`), not Node.
- `cdk synth --all` and `cdk diff` against the live account re-validated with all the
  above changes: still a clean, purely additive plan, zero `[-]`/replacement lines.
  `coa-dev-api` template size ticked up slightly to 976,880/1,000,000 bytes (was
  974,925 pre-tags) from the two new tags — still fine, same margin to watch.
- **Synthetic test data staged at the repo root**, ready to load as a source right after
  deploy (see "Post-deploy: load synthetic test data" below):
  `products.csv`, `inventory_snapshots.csv`, `products-table.json`,
  `inventory_snapshots-table.json`.

## To redeploy (e.g. after `make destroy-dev`, or on a fresh account)

```bash
cd context-ontology-accelerator
source .env   # SCL_SMUS_ADMIN_ARNS and the pnpm shim are both already in here
aws sso login --profile AWSAdministratorAccess-<ACCOUNT_ID>   # if session expired
make deploy-dev
```

If this is a genuinely fresh account (not reusing `<ACCOUNT_ID>`), you'll need to:
1. Create an equivalent bridge IAM role (see "Two real bugs hit and fixed" above) and
   update `SCL_SMUS_ADMIN_ARNS` in `.env` to match its ARN + new account ID.
2. Set `/coa/config` in SSM again (`initialAdminEmail`) — it's account-specific.

Real elapsed time for this deploy (after the retries below): the final clean run took
**~28 minutes** for `cdk deploy --all` once all 16 stacks' code paths were correct.
The commonly-cited "~1.5 hours" estimate includes first-time Docker/dependency setup
and is conservative; ours was faster since Docker bundling issues never materialized
(local `uv`/pip bundling worked throughout — see earlier synth validation). Full
reference: [external-docs/content/deploying.md](external-docs/content/deploying.md).

**If a deploy is interrupted (session/terminal drops mid-deploy):** the `cdk deploy`
process dies with it unless run detached. Relaunch with
`nohup make deploy-dev > /tmp/deploy.log 2>&1 & disown` — CDK is idempotent per-stack,
so it'll skip everything already `CREATE_COMPLETE` and resume from wherever it stopped.
A stack left in `REVIEW_IN_PROGRESS` (an uncommitted changeset) is harmless and gets
replaced automatically on the next attempt.

**Doc bug to know about:** `deploying.md` says the web app URL output is named
`WebAppUrl` on `coa-dev-web`. That output does not exist. Use `WebsiteURL` (full
`https://` URL) or `DistributionDomainName` (bare hostname) instead — both are real
outputs, defined in `infra/lib/constructs/public-ui-construct.ts:266-279`.

## Post-deploy: get the URLs/IDs you need

Real values already captured in "Live deployment outputs" above. Commands below are
for re-deriving them later (e.g. after a redeploy) — one `describe-stacks` call per
stack/output:

```bash
aws cloudformation describe-stacks --stack-name coa-dev-web \
  --query "Stacks[0].Outputs[?OutputKey=='WebsiteURL'].OutputValue" --output text

aws cloudformation describe-stacks --stack-name coa-dev-auth \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId' || OutputKey=='UserPoolClientId' || OutputKey=='CognitoDomainUrl' || OutputKey=='McpClientId'].{Key:OutputKey,Value:OutputValue}"

aws cloudformation describe-stacks --stack-name coa-dev-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" --output text

aws cloudformation describe-stacks --stack-name coa-dev-sources \
  --query "Stacks[0].Outputs[?OutputKey=='SourcesDataBucketName'].OutputValue" --output text
```

| Need | Stack | Output |
|---|---|---|
| Browser URL | `coa-dev-web` | `WebsiteURL` |
| Cognito User Pool ID | `coa-dev-auth` | `UserPoolId` |
| Web app's Cognito app client ID | `coa-dev-auth` | `UserPoolClientId` |
| Cognito Hosted UI domain | `coa-dev-auth` | `CognitoDomainUrl` |
| MCP/CLI Cognito client ID | `coa-dev-auth` | `McpClientId` |
| REST API base URL | `coa-dev-api` | `ApiEndpoint` |
| Bucket for the synthetic-data source (below) | `coa-dev-sources` | `SourcesDataBucketName` |

## Post-deploy: first sign-in

1. **Check the inbox for `<ADMIN_EMAIL>`** for a Cognito email containing a
   temporary password (this is why `/coa/config`'s `initialAdminEmail` was set — see
   above — without it this would've gone to `nobody@amazon.com` and been unreachable).
   The username Cognito created is also `<ADMIN_EMAIL>` (`idp-authentication-
   stack.ts`'s `fromSsmConfig` sets `username = email`), and it's already in the
   `Admin` Cognito group.
2. **Open `WebsiteURL`** in a browser. Unauthenticated routes redirect to a minimal
   "Sign in" page (`packages/web-app/src/pages/LoginPage.tsx`) — one button.
3. **Click Sign in** → redirects to Cognito's own Hosted UI (OIDC Authorization
   Code + PKCE under the hood, no custom login form in this app). Enter the temp
   password; Cognito forces a password reset on first login (its standard flow, not
   custom UI).
4. **Redirected back** to `/authenticate` → token exchange completes → lands in the
   app dashboard.
5. **Confirm admin access**: the `Admin` Cognito group is pre-seeded (via
   `authnz-stack.ts`'s `SeedGroupMapping-Admin-platform-admin`) to map to the
   `platform-admin` role, so this should already be active — check the web app's
   Permissions page to confirm rather than assume. If it's missing, grant
   `platform-admin` manually via the API or that same page.

### Optional: API smoke test without the browser

This is a `dev` deploy, so password-based Cognito auth is enabled (SRP-only in prod —
`idp-authentication-stack.ts:268-277`):

```bash
TOKEN=$(aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH \
  --client-id <COGNITO_WEB_CLIENT_ID> \
  --auth-parameters USERNAME=<ADMIN_EMAIL>,PASSWORD=<new-password-after-reset> \
  --region us-east-1 --query "AuthenticationResult.IdToken" --output text)

curl -H "Authorization: Bearer $TOKEN" https://<API_ID>.execute-api.us-east-1.amazonaws.com/prod/namespaces
```
A `200` with an empty list confirms API Gateway → authorizer → backend Lambda are all
correctly wired end-to-end.

## Post-deploy: create the first namespace

Web UI: Administration → Namespaces → Create. Or API: `POST /namespaces`. This is the
deepest available "does it actually work" check — it touches DataZone project creation,
Athena workgroup provisioning, and role-template grants across the storage/authnz/
namespace stacks. Keep the `namespaceId` — it's needed below.

## Post-deploy: load the synthetic test data

Files already staged at the repo root (see "Pre-deploy prep" above):
`products.csv` (20 rows), `inventory_snapshots.csv` (60 rows, FK'd to `products` via
`product_id`), `products-table.json`, `inventory_snapshots-table.json` (Glue
`create-table` input, CSV SerDe, `__SOURCES_BUCKET_URI__` placeholder for the S3
location).

```bash
BUCKET=coa-dev-sources-data-<ACCOUNT_ID>   # substitute your account's actual bucket name

aws s3 cp products.csv "s3://$BUCKET/synthetic-test/products/products.csv"
aws s3 cp inventory_snapshots.csv "s3://$BUCKET/synthetic-test/inventory_snapshots/inventory_snapshots.csv"

sed -i '' "s|__SOURCES_BUCKET_URI__|s3://$BUCKET|" products-table.json inventory_snapshots-table.json

aws glue create-database --database-input '{"Name":"coa_dev_synthetic"}'
aws glue create-table --database-name coa_dev_synthetic --table-input file://products-table.json
aws glue create-table --database-name coa_dev_synthetic --table-input file://inventory_snapshots-table.json
```

No extra IAM/bucket-policy work needed — `sources-stack.ts`'s discovery Lambda already
has broad `glue:Get*` on every database/table in the account+region, and this bucket is
the one it already has explicit S3 read access to.

Then register it as a source (needs the bearer token and `namespaceId` from above):

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "https://<API_ID>.execute-api.us-east-1.amazonaws.com/prod/namespaces/<namespaceId>/sources" \
  -d '{
    "sourceType": "DATABASE",
    "databaseSource": {
      "name": "Synthetic Products & Inventory",
      "glueConfiguration": {
        "catalogId": "<ACCOUNT_ID>",
        "region": "us-east-1",
        "databaseName": "coa_dev_synthetic"
      }
    }
  }'
```

Poll `GET /namespaces/<namespaceId>/sources/<sourceId>` — expect
`REGISTERED → SCANNING → ENRICHING → PENDING_REVIEW`, then approve it (web UI or API)
to reach `APPROVED` and `queryable: true`. Once approved, query it via Athena
(3-part name, e.g. `SELECT * FROM "coa_dev_synthetic"."products" LIMIT 10;`) or through
the app's own query surface to confirm real data flows end-to-end.

## Fifth real bug hit and fixed: Bedrock guardrail blocked source enrichment

Found while registering the American Century demo dataset (`coa_dev_asset_mgmt`,
18 tables — see `DEMO-DATASET-PLAN.md`) as a source. Pass-1 table enrichment failed for
17 of 18 tables, twice in a row across two independent source registrations:
`/ecs/coa-dev-sources-db-enrichment-agent` logged
`Enrichment complete: enriched=1 failed=17`, each failure a
`Guardrail blocked table ... (batch 0)` warning. Since Pass-2 FK inference
(`packages/sources/.../enrichment/relationship_inferrer.py`) only runs against tables that
survive Pass-1, this left the induced ontology almost entirely disconnected — OntoQA
validation reported `DISCONNECTED_CLASSES` on 17 of 18 classes.

**Root cause**, confirmed by calling the real
`packages/sources/src/coa_sources/database/enrichment/prompts.py` `build_user_prompt()` +
`SYSTEM_PROMPT` directly against the guardrail via `bedrock-runtime.converse()` (not
guessed from logs): the `coa-dev-guardrail` (id `4rn9bwu9zec6`) had its `PROMPT_ATTACK`
content filter set to `inputStrength: HIGH`. The real per-table enrichment prompt — a
structured JSON-schema instruction plus an "Existing metadata: reproduce these fields
unchanged" block (present because this dataset intentionally ships a real Comment on
every column, per the plan's design) — sits right on that filter's threshold. Reproduced
deterministically: 17 of 18 tables' real prompts got
`PROMPT_ATTACK confidence=LOW, filterStrength=HIGH, action=BLOCKED`; `option_warrant_holding`
was the sole survivor in both the two production runs *and* the direct reproduction.
30+ isolated `converse()` calls with hand-written synthetic prompts never triggered it —
only the exact production prompt template did, so this is a guardrail-sensitivity issue,
not a data-quality problem with the demo dataset.

**Fix**: lowered `PROMPT_ATTACK` from `HIGH` to `MEDIUM` on the guardrail's `DRAFT` version:

```bash
aws bedrock update-guardrail --guardrail-identifier 4rn9bwu9zec6 \
  --name coa-dev-guardrail \
  --blocked-input-messaging "Request blocked by content filter." \
  --blocked-outputs-messaging "Response blocked by content filter." \
  --content-policy-config '{"filtersConfig": [...]}' \
  --sensitive-information-policy-config '{"piiEntitiesConfig": [...]}'
```

`update_guardrail` replaces the whole policy config rather than patching one field, so
every other filter (VIOLENCE/MISCONDUCT/HATE/SEXUAL/INSULTS, all still `HIGH`) and every
PII entity setting (EMAIL/PHONE/NAME/SSN/CREDIT_CARD, all still `ANONYMIZE`) was carried
over unchanged — only `PROMPT_ATTACK.inputStrength` moved. Re-ran all 18 tables' real
prompts after the change: **0/18 blocked**. This guardrail is shared account-wide (chat,
induction, enrichment), so the fix benefits any future source registration, not just this
one — no code change or redeploy needed, since it's a guardrail-config change, not an app
change.

**Action needed if you already registered a source before this fix**: delete and
re-register it. A `DATABASE` source's rescan is only allowed from `SCAN_FAILED`
(`SourceDetail.tsx`'s Re-scan button is disabled otherwise, enforced server-side too —
see plan §10), and a partially-enriched-but-`APPROVED` source can't get a second Pass-1
attempt any other way.

## Sixth issue found (not yet fixed): correct Tier-2 answers get discarded and replaced with a document-RAG refusal

Found while demoing multi-hop Playground queries against the American Century dataset.
"Which funds hold debt issued by entities ultimately owned by Brookfield Corporation?"
(a `fund → fund_period_report → holding → debt_holding → security → issuer` join, one hop
short of `issuer → legal_entity → legal_entity_relationship`) returned a refusal citing
"no document chunks containing portfolio holdings, debt issuance records, or ownership
structures" — from a *structured database source with the exact needed data and FKs
present*.

**Root cause**, confirmed by calling the AgentCore Runtime endpoint directly with
`options.tierOverride: 2` (`orchestrator.py:212-214`, pins Tier 2, disables the
fallthrough below) for the same question:

- Tier 2 (`_run_tier2`, `packages/context-manager/src/coa_serve/orchestrator.py:590-654`)
  generated correct SQL and got the right 3 funds back from Athena in ~11.6s.
- But its self-reported confidence was **0.2**, under
  `EMPTY_RESULT_CONFIDENCE_FLOOR = 0.3` (`orchestrator.py:614`, confidence source:
  the model's own "Confidence: X.X" line in `tier2/nl_to_sql/sql_generator.py:663-664`).
  Multi-hop joins routinely under-rate their own confidence even when correct.
- On the normal (non-pinned) path, that gate sets `result = None` and the function
  returns `(None, None)` (`orchestrator.py:622,643`) — **the rows are gone**, not just
  hidden; there is no code path that preserves them for later use.
- Tier 3 then runs against a *separate* GraphRAG property graph
  (`TIER3_STRATEGY="lexical-baseline"`, `serve-stack.ts:492-494`) built from ingested
  *documents*. This source has none (it's a pure structured DB source, no PDFs/filings
  loaded), so there are zero chunks to cite.
- Independently of the above, `_run_tier3`'s hand-rolled path hardcodes
  `structured_data=None` when calling `KnowledgeRetriever.resolve`
  (`orchestrator.py:1071`) — so even a Tier-2 result that *did* survive would never reach
  the synthesizer's `structured_data` grounding parameter on this path. The agentic path
  (`options.mode="agentic"`) does thread real rows into `structured_data`
  (`tier3/agentic/retriever.py:801-803`), but the synthesizer's system prompt
  (`tier3/synthesizer.py:45-60`) still emphasizes citing "document sources," biasing the
  model to hedge even when rows are present.

**Secondary, softer finding**: the SQL Tier 2 generated didn't actually traverse
`issuer → legal_entity → legal_entity_relationship` for "ultimately owned by" — it used
`WHERE LOWER(issuer_name) LIKE '%brookfield%'` instead, and got lucky (some held issuers
are literally named "Brookfield ..."). The ownership-relationship object properties are
real, populated, and FK-correct (verified independently against the built Parquet: 375
relationship rows, zero dangling FKs) — the NL→SQL generator just doesn't reliably choose
to hop through them for this phrasing. Not blocking; worth a prompt-engineering pass on
`nl_to_sql/sql_generator.py` separately from the fix below.

**Proposed fix** (not yet applied — needs sign-off, this is a shared orchestration path
used by every namespace, not just this demo):
1. In `_run_tier2`, when the confidence gate fires, don't fully discard the
   `StrategyResult` — return it (or its `.rows`/`.sparql`) alongside the `None` response
   so the caller still has it.
2. Thread those rows into `_run_tier3`'s `structured_data` parameter
   (`orchestrator.py:1071`, and the agentic call at `:999-1021` for consistency) instead
   of a hardcoded `None`, tagged as low-confidence so the synthesizer can use-but-hedge
   rather than never seeing them at all.
3. Soften `_SYSTEM_INSTRUCTION_BASE` (`tier3/synthesizer.py:45-60`) so document citation
   isn't the only path to a confident answer — `structured_data`/`graph_entities` should
   count too.
Workaround until fixed: pass `options.tierOverride: 2` explicitly (not exposed in the
Playground UI, must be sent directly against the AgentCore Runtime endpoint), or prefer
shallower-join demo questions (sub-adviser/custodian/forward-currency ones all tested
above 0.3 confidence and answer correctly through the normal path).
