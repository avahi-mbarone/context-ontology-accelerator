# Demo dataset plan — American Century asset-management ontology

A compact dataset built from American Century Investments' own public SEC filings, shaped so
COA's graph-based ontology mapping produces real relationships and a real class hierarchy.

Companion to [HANDOFF.md](HANDOFF.md). Every file/line reference below was verified against
this working tree; every row count was measured from the real source files.

---

## 1. Context

`coa-dev` is deployed on account `<ACCOUNT_ID>` — all 16 stacks `CREATE_COMPLETE`, per
HANDOFF.md. Scan → Model → Serve works against the staged synthetic sample
(`products.csv`, `inventory_snapshots.csv`). What underperforms is the **graph-based
ontology mapping**, and after reading the induction engine that's a predictable consequence
of the sample data rather than a bug.

Goal: a small, uncomplicated dataset drawn from
[American Century Investments'](https://www.americancentury.com/home/) own **public SEC
filings**, shaped so the induced ontology has real relationships, a real class hierarchy,
and clean FIBO grounding.

Three HANDOFF.md post-deploy steps are still outstanding and this plan depends on all of
them: **first sign-in has not happened, no namespace exists, and no source has been
loaded.** Steps 0–2 in §8 cover them.

---

## 2. Why the current sample can't produce a graph

Three hard constraints in the code, in order of impact:

1. **Object properties come *only* from declared FK constraints.**
   `packages/ontology-engine/src/coa_ontology/inducer/strategies/table_to_ontology.py:420`
   gates the entire FK branch on `if table.tableConstraints and …`. No FK → the column
   becomes an `owl:DatatypeProperty`. There is no join inference inside ontology-engine.
2. **The Glue connector never populates PK/FK.**
   `packages/sources/src/coa_sources/database/connectors/glue_catalog.py:275-378` builds
   `Table(...)` without ever setting `primary_key` or `foreign_keys` (Glue has no constraint
   metadata). Only the JDBC path reads them from `information_schema`
   (`connectors/jdbc.py:478-503`). On a Glue source, relationships can come only from the
   LLM Pass-2 inferrer or a steward.
3. **Class hierarchy has exactly two sources**, and the sample has neither:
   - **Grounding** against foundational ontologies — an empty `groundingOntologyIds` pool is
     an explicit "no grounding scope" signal (`induce_catalog.py:800-820`), making the run
     all-novel and flat.
   - **PK-sharing subtype detection** — `inducer/services/subtype_detection.py:78-131` emits
     `rdfs:subClassOf` + `coa:subClassProvenance "PK_SHARING"` when a child's
     *single-column* PK is also a single-column FK to the parent's PK, and needs
     `MULTI_CHILD_THRESHOLD = 2` children on one parent to auto-fire.

Two tables can produce at most one AI-inferred object property and zero `subClassOf` axioms.
The Tier-2 OntoQA validator (`packages/ontology-engine/src/coa_ontology/validation/validators/tier2.py:40-101`)
flags exactly that: `LOW_RELATIONSHIP_RICHNESS`, "ontology is mostly taxonomic."

One more fact drives the whole schema design: the Pass-2 FK prompt
(`packages/sources/src/coa_sources/database/enrichment/relationship_inferrer.py:18-43`,
payload built at `:76-78`) sees **only column names and SQL types** — no descriptions, no
sampled values — and is instructed to match `customer_id -> customers.id`.

---

## 3. Why "small" is right, not a compromise

The demo surfaces are themselves capped:

| Cap | Value | Where |
|---|---|---|
| Proposal graph preview hard-disabled above | 100 classes | `packages/web-app/src/pages/ontology/induce/ProposalDetail.tsx:698` |
| Explorer opens on a sample: roots / descendants / properties | 3 / 50 / none | `packages/ontology-engine/src/coa_ontology/stores/neptune_db_graph.py:120-121` |
| Graph search nodes / hops | 60 / 1 | `packages/web-app/src/pages/ontology/GraphSearch.tsx:53-57` |
| `_fetch_object_properties` | `LIMIT 200` | `packages/context-manager/src/coa_serve/tier2/ontop/tbox_context.py` |

Target: **18 tables, ~55k rows, well under 20 MB of Parquet.** At 18 classes the proposal
graph renders and the Explorer sample is effectively the whole graph.

---

## 4. Sources

American Century's own public filings, plus the open LEI registry. Volumes measured from the
real files (2026Q2), not estimated.

| Source | What it gives | Volume |
|---|---|---|
| [SEC Investment Company Series & Class](https://www.sec.gov/files/investment/data/other/investment-company-series-and-class-information/investment_company_series_class.csv) (8 MB CSV) | Fund + share-class spine with tickers | 15 registrants, 129 series, 515 classes |
| [SEC Form N-CEN](https://www.sec.gov/data-research/sec-markets-data/form-n-cen-data-sets) `2026q2_ncen.zip` (8 MB) | Adviser, sub-adviser, custodian, transfer agent, auditor, underwriter, authorized participant — with LEI and CRD | ~150 providers, ~500 engagements |
| [SEC Form N-PORT](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets) `2026q2_nport.zip` (440 MB) | Holdings, issuers, instrument subtypes, fund flows, monthly returns | 78 fund reports, 17,371 holdings, 4,178 issuers, 2,418 issuer LEIs |
| [GLEIF golden copy](https://goldencopy.gleif.org/api/v2/golden-copies/publishes?format=csv) — `rr` file (23 MB) + `lei-records` API | Legal entity + direct/ultimate parent hierarchy | ~2,600 entities, ~800 relationships |

Instrument subtypes present for American Century in one quarter — measured:

| Subtype | AC rows |
|---|---|
| `DEBT_SECURITY` | 10,008 |
| `FWD_FOREIGNCUR_CONTRACT_SWAP` | 1,057 |
| `NONFOREIGN_EXCHANGE_SWAP` | 95 |
| `REPURCHASE_AGREEMENT` | 34 |
| `SWAPTION_OPTION_WARNT_DERIV` | 8 |

Five disjoint subtypes, comfortably over `MULTI_CHILD_THRESHOLD = 2`.

**Licensing:** SEC and GLEIF data are public / open. FIBO is MIT
(`github.com/edmcouncil/fibo`, release `master_2026Q2`).

**Scope:** American Century only. Adding peer families later (T. Rowe, Fidelity, iShares) is
a one-line change to the CIK constant — deliberately deferred to keep the demo small.

American Century CIKs (verified against the series/class file):

```
100334   AMERICAN CENTURY MUTUAL FUNDS, INC.              14 series /  64 classes
717316   AMERICAN CENTURY CALIFORNIA TAX FREE & MUNI       4 series /  13 classes
746458   AMERICAN CENTURY MUNICIPAL TRUST                  4 series /  13 classes
757928   AMERICAN CENTURY TARGET MATURITIES TRUST          2 series /   4 classes
773674   AMERICAN CENTURY GOVERNMENT INCOME TRUST          5 series /  21 classes
814680   AMERICAN CENTURY VARIABLE PORTFOLIOS INC          9 series /  18 classes
827060   AMERICAN CENTURY QUANTITATIVE EQUITY FUNDS       17 series /  67 classes
872825   AMERICAN CENTURY WORLD MUTUAL FUNDS INC          13 series /  62 classes
880268   AMERICAN CENTURY INTERNATIONAL BOND FUNDS         3 series /  18 classes
908186   AMERICAN CENTURY CAPITAL PORTFOLIOS INC          14 series /  72 classes
908406   AMERICAN CENTURY INVESTMENT TRUST                 10 series /  48 classes
924211   AMERICAN CENTURY STRATEGIC ASSET ALLOCATIONS       5 series /  29 classes
1124155  AMERICAN CENTURY VARIABLE PORTFOLIOS II INC        1 series /   2 classes
1293210  AMERICAN CENTURY ASSET ALLOCATION PORTFOLIOS      25 series /  70 classes
1353176  AMERICAN CENTURY GROWTH FUNDS, INC.               3 series /  14 classes
```

---

## 5. The conformed schema — 18 tables

The reshaping is the substance of this plan. Raw SEC keys are composite
(`ACCESSION_NUMBER` + `HOLDING_ID`) and table names don't match their key stems, which
breaks both subtype detection (single-column PKs only) and the Pass-2 FK prompt. So we
conform to one rule:

> **Every table's name is its PK column's stem** — making `holding_id → holding.holding_id`
> the exact pattern the inferrer is prompted for.

Glue database `coa_dev_asset_mgmt`, Parquet under
`s3://coa-dev-sources-data-<ACCOUNT_ID>/american-century/<table>/`.

### Fund spine

| Table | PK | FKs |
|---|---|---|
| `registrant` | `registrant_id` (CIK) | — |
| `fund` | `fund_id` (SERIES_ID) | `registrant_id` |
| `share_class` | `share_class_id` (CLASS_ID) | `fund_id` |
| `fund_period_report` | `fund_period_report_id` | `fund_id` |
| `monthly_return` | `monthly_return_id` | `fund_period_report_id` |

### Service providers — from N-CEN

| Table | PK | FKs |
|---|---|---|
| `service_provider` | `service_provider_id` | `legal_entity_id` |
| `fund_adviser` | `fund_adviser_id` | `fund_id`, `service_provider_id` |
| `fund_service_engagement` | `fund_service_engagement_id` | `fund_id`, `service_provider_id` |

### Holdings + instrument subtypes — from N-PORT

| Table | PK | FKs |
|---|---|---|
| `issuer` | `issuer_id` | `legal_entity_id` |
| `security` | `security_id` | `issuer_id` |
| `holding` | `holding_id` | `fund_period_report_id`, `security_id` |
| `debt_holding` | `holding_id` | `holding_id` → `holding` |
| `repurchase_agreement_holding` | `holding_id` | `holding_id` → `holding` |
| `forward_currency_holding` | `holding_id` | `holding_id` → `holding` |
| `swap_holding` | `holding_id` | `holding_id` → `holding` |
| `option_warrant_holding` | `holding_id` | `holding_id` → `holding` |

### Legal entity graph — from GLEIF

| Table | PK | FKs |
|---|---|---|
| `legal_entity` | `legal_entity_id` (LEI) | — |
| `legal_entity_relationship` | `legal_entity_relationship_id` | `legal_entity_id`, `parent_legal_entity_id` → both `legal_entity` |

### Design decisions, each tied to the constraint it satisfies

- **Single-column surrogate PKs everywhere.** Composite PKs are explicitly out of scope for
  subtype detection (`subtype_detection.py:17-19`), and composite FKs pin the relationship to
  the first column and degrade the rest to literals
  (`packages/ontology-engine/docs/ontology-data-model.md:263-271`).
- **Five PK-sharing children on `holding`** → five confirmed `rdfs:subClassOf` axioms. This
  is the only structural hierarchy signal available, and the reason N-PORT is worth the
  440 MB download.
- **Securities-lending fields folded into `holding`, not a subtype table.** It has a row for
  every holding (17,371 of 17,371), so PK-sharing would fire and assert that *every* holding
  is a `SecuritiesLendingHolding` — structurally valid, semantically wrong. Exactly the "1:1
  attached record" case `subtype_detection.py:73-75` warns about.
- **`legal_entity_relationship` carries two FKs to `legal_entity`** — a self-referencing
  hierarchy, and the `parent_id -> same_table.id` case the Pass-2 prompt names explicitly.
- **`issuer.legal_entity_id` / `service_provider.legal_entity_id`** rather than `issuer_lei`
  — the SEC↔GLEIF join becomes a namable object property, the cross-source link worth
  demoing.
- **Every bare table name unique.** An FK target name shared by two in-run tables is
  silently degraded to a literal in *both* artifacts and is **not surfaced in the review
  UI** (`ontology-data-model.md:477-491`).
- **Low-cardinality columns typed `string`**: `asset_category`, `issuer_type`,
  `payoff_profile`, `adviser_role`, `service_type`, `relationship_type`, `entity_status`,
  `fund_type`. Glue *does* sample enums, via Athena (`glue_catalog.py:223-227` →
  `connectors/athena_sampler.py:206-225`), gated on `distinct ≤ 25 AND total ≥ 3 × distinct`,
  string types only. These become `coa:distinctValues` NL→SQL hints.
- **A `Comment` on every table and column.** Glue comments are authoritative: surfaced as
  the description, tagged `DETERMINISTIC`, `review_status=APPROVED`, `confidence=1.0`, and
  protected from AI overwrite (`glue_catalog.py:285-308`,
  `enrichment/table_enricher.py:71-78`). They also feed the grounding embedding text
  (`inducer/services/pipeline.py:146-151`) and the rerank prompt
  (`inducer/services/grounding.py:705-728`) — the single biggest lever on grounding hit
  rate. Source them from the `dc:description` fields in each zip's `ncen_metadata.json` /
  `nport_metadata.json`.

### Expected ontology shape

~18 classes, ~16 object properties, 5 `PK_SHARING` subClassOf axioms, ~85 datatype
properties. Against `validation/validators/tier2.py` that's relationship richness ≈ 0.76
(warn threshold 0.1) and attribute richness ≈ 4.7 (warn threshold 0.5).

---

## 6. Grounding ontologies

Without these the induction is all-novel and flat. Four FIBO modules are already curated
(`packages/ontology-engine/src/coa_ontology/catalog/routers/foundational.py:126-161`):
`fibo-agreements`, `fibo-contracts`, `fibo-clients-accounts`, `fibo-financial-products`.

Add these by URL via `POST /ontologies/{id}/fetch`. All verified to return Turtle at
`https://spec.edmcouncil.org/fibo/ontology/master/latest/<path>.ttl`:

| Module path | Size | Why |
|---|---|---|
| `SEC/Funds/Funds` | 38 KB | Fund, fund manager |
| `SEC/Funds/CollectiveInvestmentVehicles` | 107 KB | Mutual fund, ETF, CIV, share class |
| `FBC/FinancialInstruments/FinancialInstruments` | 51 KB | Instrument supertypes |
| `SEC/Debt/DebtInstruments` | — | `debt_holding` grounding |
| `SEC/Equities/EquityInstruments` | — | equity holdings |
| `SEC/Securities/SecuritiesIssuance` | 42 KB | issuer ↔ security |
| `BE/LegalEntities/LEIEntities` | 34 KB | aligns directly with the GLEIF tables |
| `FND/Parties/Parties` | — | party roles behind service providers |
| `FBC/FunctionalEntities/FinancialServicesEntities` | — | advisers, custodians |

> Note `SEC/Securities/Securities` and `SEC/CollectiveInvestmentVehicles/…` both 404 — use
> the paths in the table above.

Induce with `groundingMode=ENHANCED` and `confidenceThreshold=0.65`. **Not 0.80** — the demo
config records that at 0.80, `schema:identifier` vs `catastropheIdentifier` scored ~0.62 and
every ID/date column came back novel
(`packages/ontology-engine/demo/config-example.yaml:20-28`).

---

## 7. What Glue-side machinery COA needs (and doesn't)

**No Glue crawler and no Glue ETL job.** Grepping all of `infra/` for `CfnCrawler`, `CfnJob`,
`CfnTrigger`, `StartCrawler`, `StartJobRun`, `aws_glue`, `glue-alpha` returns one unrelated
hit (`emr-serverless:StartJobRun`, `namespace-stack.ts:283`). No `aws-cdk-lib/aws-glue`
import exists anywhere. The connector says so — `glue_catalog.py:6-7`:

> Reads tables and columns directly from the Glue Data Catalog via GetTables paginator.
> **No Glue Crawler provisioning needed.**

The only precondition (`external-docs/content/sources.md:38`) is that the tables are already
queryable in Athena. So `create-database` + `create-table` *is* the whole Glue job, and it's
ours — the same pattern HANDOFF.md:373-378 uses, but Parquet instead of CSV.

Things COA does itself, which are easy to mistake for a crawler:

- **Registration sets the Athena target.** `POST /sources` copies
  `glueConfiguration.databaseName` into the source item's `athenaDatabase`
  (`packages/sources/src/coa_sources/api/database_routes.py:197`).
- **Federation is a deliberate no-op.** `pipeline/federation_handler.py:200-230`
  short-circuits `GLUE_DATABASE` to `{"provisioned": false, "reason": "glue-native"}`, doing
  only a Lake Formation `GrantPermissions` (DESCRIBE on the database, SELECT+DESCRIBE on
  `TableWildcard`) for the serve runtime role — needed only in strict-LF accounts. It also
  overwrites `queryable` with the grant result.
- **Lake Formation needs nothing from us.** Nothing registers an S3 location with LF, which
  is correct: an unregistered location is governed by IAM only, and `serve-stack.ts:714-722`
  grants `s3:GetObject/ListBucket` on `arn:aws:s3:::coa-*`, which covers
  `coa-dev-sources-data-<ACCOUNT_ID>`. `sources-stack.ts:644-666` (sid
  `GlueNativeDatabaseRead`) and `:667-681` (`LakeFormationFederation`) exist for exactly this
  path, and the deploy registers the federation role as an LF data-lake admin
  (`infra/lib/constructs/lakeformation-admin.ts`). In default IAM mode, zero LF work is
  required.
- **Enum sampling runs in the `primary` workgroup, not the namespace one.**
  `ATHENA_WORKGROUP` is never set on the discovery Lambda; only `ATHENA_SPILL_BUCKET` is
  (`sources-stack.ts:452`). So `AthenaSampler` derives
  `s3://coa-dev-athena-spill-<ACCOUNT_ID>/enum-sampling/` and omits `WorkGroup` entirely
  (`athena_sampler.py:227-238`). **The `primary` workgroup must still exist** or sampling
  silently yields nothing — every failure is swallowed (`athena_sampler.py:189-204`), so the
  only signal is the CloudWatch line `athena_sample_column_failed`.
- **The real gate is COA's own review, not Glue.** Scan writes DataZone assets via
  `datazone:CreateAsset`; induction reads them back with `searchScope: "ASSET"` (project
  inventory, not published listings — `metadata_store/smus.py:365-372`), so **no DataZone
  data-source run and no publish workflow.** But
  `libs/common/src/coa_common/metadata_store/catalog_reader.py:65-78` skips any source whose
  `status != APPROVED` and filters tables to `review_status == APPROVED`. Induction reads
  DataZone in every deployed env — `CATALOG_SOURCE: "smus"` is hardcoded at
  `infra/lib/stacks/services/ontology-stack.ts:237`.

### Constraints to respect

- **Glue database name** must match `^[A-Za-z0-9_\-]{1,128}$` — enforced on the LF grant path
  (`glue_connection_provisioner.py:104`, applied at `:532`). A dot or space skips the grant
  and leaves `queryable = False`. `coa_dev_asset_mgmt` is fine.
- **`catalogId`** must be the bare 12-digit account id; nested catalogs get the grant on the
  wrong catalog.
- **No partitioning.** Declaring partition keys without registering partitions makes the
  sampler's `COUNT(*)` return 0 and silently yields no `distinctValues`. Use flat prefixes.
- **Region** must be `us-east-1` — all Glue ARNs in the IAM policies are `${this.region}`.
- **Parquet vs CSV makes no difference at any COA layer** (`glue_catalog.py:335-341` only
  records `classification`); it matters solely to Athena, via the `SerdeInfo`/`InputFormat` we
  write ourselves.
- `sources.addDependency(serve)` already exists (`infra/bin/app.ts:382`), so the
  `/coa/serve/runtime-role-arn` SSM param the LF grant reads will be present — no ordering
  risk.

---

## 8. Implementation

New directory `scripts/demo-data/`, local only — this repo is a read-only upstream mirror,
so don't plan on upstreaming it.

| File | Responsibility |
|---|---|
| `fetch_sources.py` | Download + cache the four sources |
| `schema.py` | Single source of truth: 18 tables, columns, types, comments |
| `build_dataset.py` | Filter to AC, conform, mint surrogate keys, write Parquet |
| `glue_tables.py` | Emit one Glue `create-table` input JSON per table from `schema.py` |
| `load.sh` | `aws s3 sync` + `create-database` + `create-table` per table |

Notes for each:

1. **`fetch_sources.py`**
   - SEC requires a descriptive `User-Agent`; plain fetches get `403`.
   - GLEIF LEI attributes via the batch API — `filter[lei]=<comma-separated>` with
     `page[size]=200`, unauthenticated (verified). ~2,600 LEIs is ~13 requests. Do **not**
     download the 476 MB `lei2` full file.
   - GLEIF `rr` relationship file: resolve the URL from
     `https://goldencopy.gleif.org/api/v2/golden-copies/publishes?format=csv` → `rr.full_file.csv.url`.
2. **`build_dataset.py`** — keep the CIK list a module-level constant (see §4).
3. **`glue_tables.py`** — same shape as `products-table.json` but Parquet:
   `ParquetHiveSerDe` / `MapredParquetInputFormat` / `MapredParquetOutputFormat`,
   `classification: "parquet"`, no `skip.header.line.count`.

---

## 9. Sequence and verification

Steps 0–2 are the outstanding HANDOFF.md post-deploy work; nothing after them can run first.

**Credentials are currently expired.** Start with:

```bash
aws sso login --profile AWSAdministratorAccess-<ACCOUNT_ID>
```

then `source .env`.

**0. First sign-in** (HANDOFF.md:313-333). Check `<ADMIN_EMAIL>` for the Cognito
temp-password email, open https://<CLOUDFRONT_DOMAIN>.cloudfront.net, sign in through the Hosted
UI, reset the password. Then confirm on the Permissions page that the pre-seeded `Admin`
group actually maps to `platform-admin` rather than assuming it.

**1. API token** — dev allows password auth (HANDOFF.md:336-347), client id
`<COGNITO_WEB_CLIENT_ID>`. `GET /namespaces` returning `200` with an empty list confirms
API Gateway → authorizer → backend.

**2. Create the first namespace** — web UI (Administration → Namespaces → Create) or
`POST /namespaces`. HANDOFF.md:351-356 correctly calls this the deepest "does it work" check:
it drives DataZone project creation, Athena workgroup provisioning
(`packages/control-plane/src/coa_control_plane/namespace/service.py:141-200`), and role
grants across storage/authnz/namespace. Keep the `namespaceId`.

**Skip HANDOFF.md:358-405** — the `products.csv`/`inventory_snapshots.csv` load. Loading it
into this namespace would add two FK-less flat classes and drag the OntoQA metrics down. If
you want it for comparison, put it in a separate namespace.

**3. Build and load the dataset**, then verify in Athena: `SELECT COUNT(*)` per table, and
one join proving referential integrity end to end —
`holding → security → issuer → legal_entity → legal_entity_relationship` returns rows.

**4. Register the source** — `POST /namespaces/{namespaceId}/sources` with the shape at
HANDOFF.md:386-398, `databaseName: "coa_dev_asset_mgmt"`. Poll
`GET /namespaces/{ns}/sources/{sourceId}` through
`REGISTERED → SCANNING → ENRICHING → PENDING_REVIEW`.

**5. Check FK inference before approving** — the make-or-break step. Every FK will be
`AI_INFERRED` (Glue has no constraints), so read the inferred relationships in the review UI
and confirm all 16 landed, especially the five `holding_id` subtype edges and both
`legal_entity` edges. Fix misses as steward — `STEWARD_SPECIFIED` outranks `AI_INFERRED`
(`relationship_inferrer.py:223-233`). Then **approve every table and column**, and confirm
the source itself reaches `status = APPROVED`; an unapproved FK *target* silently drops from
the run and leaves its referrers pointing at an undeclared dangling class. Also confirm
`queryable: true`.

**6. Load the grounding ontologies**, then induce with `ENHANCED` / `0.65`.

**7. Assert on the proposal**: ≥15 `owl:ObjectProperty`, exactly 5
`coa:subClassProvenance "PK_SHARING"`, Tier-2 metrics clear of `LOW_RELATIONSHIP_RICHNESS`
and `LOW_ATTRIBUTE_RICHNESS`, and the graph preview actually renders on the proposal page
(18 < 100).

**8. Accept, then check the canary** — ingest logs `mapped_class_count` and escalates to a
warning when R2RML was supplied yet zero classes came out mapped. Confirm `coa:isMapped` on
all 18 classes. `WORKBENCH_BACKEND` is already `opensearch_neptune`
(`ontology-stack.ts:218`), the only backend that writes the marker — `na_only` would leave
Tier-2 dark.

**9. Demo queries** through the Playground, each crossing ≥3 object properties:

- "Which American Century funds hold debt issued by entities ultimately owned by JPMorgan Chase?"
- "Which sub-advisers manage funds holding repurchase agreements?"
- "Total net assets by fund for funds whose custodian is State Street."
- "Which share classes belong to funds with forward currency exposure?"

---

## 10. Two operational warnings

- **Re-scan is not implemented.** `external-docs/content/sources.md:292-298` — re-scan is
  permitted only from `SCAN_FAILED` and returns `409 Conflict` otherwise. Get the schema
  right before registering; changing it later means delete-and-recreate the source.
- **Tier-3 doesn't traverse this graph by default.** `serve-stack.ts:483-500` sets
  `TIER3_STRATEGY="lexical-baseline"`, so the RDF ontology graph serves Tier 2 and the
  Explorer while Tier 3 hits the separate graphrag property graph. Demo the ontology through
  Tier-2 structured queries and the Explorer, not Tier-3 retrieval.

---

## Appendix A — source column mapping

Verified headers from the real files. `→` marks the conformed column name.

### `registrant` ← N-CEN `REGISTRANT` + `SUBMISSION`

`CIK → registrant_id` · `REGISTRANT_NAME → registrant_name` · `LEI → legal_entity_id` ·
`CITY → city` · `STATE → state` · `COUNTRY → country` · `INVESTMENT_COMPANY_TYPE →
investment_company_type` · `TOTAL_SERIES → total_series` · `FAMILY_INVESTMENT_COMPANY_NAME →
fund_family_name`

### `fund` ← series/class CSV + N-CEN `FUND_REPORTED_INFO`

`series_id → fund_id` · `series_name → fund_name` · `CIK → registrant_id` ·
`LEI → legal_entity_id` · plus `fund_type` derived from N-CEN's `IS_ETF` / `IS_INDEX` /
`IS_TARGET_DATE` / `IS_MONEY_MARKET` / `IS_FUND_OF_FUND` booleans, and
`MANAGEMENT_FEE → management_fee`, `NET_OPERATING_EXPENSES → net_operating_expenses`,
`NAV_PER_SHARE → nav_per_share`, `MONTHLY_AVG_NET_ASSETS → monthly_avg_net_assets`

> N-CEN's `FUND_ID` is composite — `accession_number_CIK_seriesId`, e.g.
> `0001099263-26-004477_0001795351_S000095886`. Split on `_` and take the third part to get
> `SERIES_ID`. This is why the provider tables need a join helper rather than a direct FK.

### `share_class` ← series/class CSV

`class_id → share_class_id` · `class_name → class_name` ·
`class_ticker_symbol → ticker_symbol` · `series_id → fund_id`

### `fund_period_report` ← N-PORT `SUBMISSION` + `REGISTRANT` + `FUND_REPORTED_INFO`

`ACCESSION_NUMBER → fund_period_report_id` · `SERIES_ID → fund_id` ·
`REPORT_ENDING_PERIOD → period_end_date` · `FILING_DATE → filing_date` ·
`TOTAL_ASSETS → total_assets` · `TOTAL_LIABILITIES → total_liabilities` ·
`NET_ASSETS → net_assets` · `SALES_FLOW_MON3 → sales_flow` ·
`REDEMPTION_FLOW_MON3 → redemption_flow` · `REINVESTMENT_FLOW_MON3 → reinvestment_flow` ·
`CREDIT_SPREAD_5YR_INVEST → credit_spread_5yr_investment_grade`

### `monthly_return` ← N-PORT `MONTHLY_TOTAL_RETURN`

`ACCESSION_NUMBER + MONTHLY_TOTAL_RETURN_ID → monthly_return_id` (surrogate) ·
`ACCESSION_NUMBER → fund_period_report_id` · `CLASS_ID → share_class_id` ·
`MONTHLY_TOTAL_RETURN1..3 → return_month_1..3`

### `service_provider` ← union of N-CEN `ADVISER`, `CUSTODIAN`, `TRANSFER_AGENT`, `PRINCIPAL_UNDERWRITER`, `PUBLIC_ACCOUNTANT`, `AUTHORIZED_PARTICIPANT`

Deduplicate on LEI (falling back to normalized name) to mint `service_provider_id`.
`*_NAME → provider_name` · `*_LEI → legal_entity_id` · `CRD_NUM → crd_number` ·
`FILE_NUM → sec_file_number` · `PCAOB_NUM → pcaob_number` · `STATE → state` ·
`COUNTRY → country`

### `fund_adviser` ← N-CEN `ADVISER`

`FUND_ID → fund_id` (split, see above) · resolved `service_provider_id` ·
`ADVISER_TYPE → adviser_role` (Adviser / Subadviser / Terminated Adviser / Terminated
Subadviser — a 4-value enum, samples cleanly) · `IS_AFFILIATED → is_affiliated` ·
`ADVISOR_START_DATE → start_date` · `ADVISOR_TERMINATED_DATE → terminated_date`

### `fund_service_engagement` ← N-CEN `CUSTODIAN`, `TRANSFER_AGENT`, `PRINCIPAL_UNDERWRITER`, `PUBLIC_ACCOUNTANT`, `AUTHORIZED_PARTICIPANT`

`FUND_ID`/`ACCESSION_NUMBER → fund_id` · resolved `service_provider_id` ·
`service_type` = literal per source table (`Custodian`, `Transfer Agent`,
`Principal Underwriter`, `Public Accountant`, `Authorized Participant` — a 5-value enum) ·
`IS_AFFILIATED → is_affiliated` · `CUSTODY_TYPE → custody_type`

### `issuer` ← N-PORT `FUND_REPORTED_HOLDING`, deduplicated

Dedup on `ISSUER_LEI` then `ISSUER_NAME`. `→ issuer_id` (surrogate) ·
`ISSUER_NAME → issuer_name` · `ISSUER_LEI → legal_entity_id` ·
`ISSUER_TYPE → issuer_type` · `INVESTMENT_COUNTRY → country`

### `security` ← N-PORT `FUND_REPORTED_HOLDING` + `IDENTIFIERS`, deduplicated

Dedup on `ISSUER_CUSIP` / ISIN. `→ security_id` (surrogate) · resolved `issuer_id` ·
`ISSUER_TITLE → security_title` · `ISSUER_CUSIP → cusip` ·
`IDENTIFIER_ISIN → isin` · `IDENTIFIER_TICKER → ticker_symbol` ·
`ASSET_CAT → asset_category` · `IS_RESTRICTED_SECURITY → is_restricted`

### `holding` ← N-PORT `FUND_REPORTED_HOLDING` + `SECURITIES_LENDING`

`HOLDING_ID → holding_id` · `ACCESSION_NUMBER → fund_period_report_id` ·
resolved `security_id` · `BALANCE → balance` · `UNIT → balance_unit` ·
`CURRENCY_CODE → currency_code` · `CURRENCY_VALUE → market_value` ·
`EXCHANGE_RATE → exchange_rate` · `PERCENTAGE → pct_of_net_assets` ·
`PAYOFF_PROFILE → payoff_profile` · `FAIR_VALUE_LEVEL → fair_value_level` ·
`DERIVATIVE_CAT → derivative_category` · and from `SECURITIES_LENDING`:
`IS_LOAN_BY_FUND → is_on_loan`, `LOAN_VALUE → loan_value`,
`IS_CASH_COLLATERAL → has_cash_collateral`

### `debt_holding` ← N-PORT `DEBT_SECURITY`

`HOLDING_ID → holding_id` (PK **and** FK) · `MATURITY_DATE → maturity_date` ·
`COUPON_TYPE → coupon_type` · `ANNUALIZED_RATE → annualized_rate` ·
`IS_DEFAULT → is_in_default` · `IS_CONVTIBLE_MANDATORY → is_mandatory_convertible`

### `repurchase_agreement_holding` ← N-PORT `REPURCHASE_AGREEMENT`

`HOLDING_ID → holding_id` · `TRANSACTION_TYPE → transaction_type` ·
`IS_CLEARED → is_cleared` · `CENTRAL_COUNTER_PARTY → central_counterparty` ·
`IS_TRIPARTY → is_triparty` · `REPURCHASE_RATE → repurchase_rate` ·
`MATURITY_DATE → maturity_date`

### `forward_currency_holding` ← N-PORT `FWD_FOREIGNCUR_CONTRACT_SWAP`

`HOLDING_ID → holding_id` · `DESC_CURRENCY_SOLD → currency_sold` ·
`CURRENCY_SOLD_AMOUNT → currency_sold_amount` ·
`DESC_CURRENCY_PURCHASED → currency_purchased` ·
`CURRENCY_PURCHASED_AMOUNT → currency_purchased_amount` ·
`SETTLEMENT_DATE → settlement_date` ·
`UNREALIZED_APPRECIATION → unrealized_appreciation`

### `swap_holding` ← N-PORT `NONFOREIGN_EXCHANGE_SWAP`

`HOLDING_ID → holding_id` · `SWAP_FLAG → swap_type` ·
`TERMINATION_DATE → termination_date` · `NOTIONAL_AMOUNT → notional_amount` ·
`UPFRONT_PAYMENT → upfront_payment` · `UPFRONT_RECEIPT → upfront_receipt` ·
`FIXED_OR_FLOATING_RECEIPT → receipt_rate_type` ·
`FIXED_OR_FLOATING_PAYMENT → payment_rate_type` ·
`UNREALIZED_APPRECIATION → unrealized_appreciation`

### `option_warrant_holding` ← N-PORT `SWAPTION_OPTION_WARNT_DERIV`

`HOLDING_ID → holding_id` · `PUT_OR_CALL → option_type` ·
`WRITTEN_OR_PURCHASED → position_type` · `SHARES_CNT → share_count` ·
`PRINCIPAL_AMOUNT → principal_amount` · `EXERCISE_PRICE → exercise_price` ·
`EXPIRATION_DATE → expiration_date` ·
`UNREALIZED_APPRECIATION → unrealized_appreciation`

### `legal_entity` ← GLEIF `lei-records` API

`id → legal_entity_id` · `entity.legalName.name → legal_name` ·
`entity.jurisdiction → jurisdiction` · `entity.category → entity_category` ·
`entity.status → entity_status` · `entity.legalAddress.country → country` ·
`entity.legalAddress.city → city`

### `legal_entity_relationship` ← GLEIF `rr` golden-copy CSV

Surrogate `legal_entity_relationship_id` · `Relationship.StartNode.NodeID → legal_entity_id`
· `Relationship.EndNode.NodeID → parent_legal_entity_id` ·
`Relationship.RelationshipType → relationship_type`
(`IS_DIRECTLY_CONSOLIDATED_BY` / `IS_ULTIMATELY_CONSOLIDATED_BY` — a clean 2-value enum) ·
`Relationship.RelationshipStatus → relationship_status`

Filter to rows where **either** node is in the `legal_entity` set, then add any missing
parent LEIs back to `legal_entity` via the batch API so no FK dangles.
