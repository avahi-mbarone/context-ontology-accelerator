# Demo Scripts

Interactive console walkthroughs for the Ontology Induction Platform.

## Prerequisites

```bash
pip install -r requirements-demo.txt
cp config-example.yaml config.yaml   # edit service URLs, induction defaults, and foundational ontologies
```

Then start the two services the demo talks to (see [Running services](#running-services) below).

## Scripts

| Script | Purpose |
|---|---|
| `setup.py` | Configure embedding backends and load foundational ontologies |
| `demo.py` | Run the full induction pipeline interactively |
| `parse_ddl_to_config.py` | Parse SQL DDL → YAML (used by the PC Insurance example) |
| `stage_fixtures.py` | YAML → data-catalog fixtures + datasource entry |

Run setup first, then demo:

```bash
python setup.py
python demo.py
```

## setup.py

Walks you through:

1. **Service health check** — verifies all services are reachable
2. **Embedding backend configuration** — shows configured backends, tests connectivity
3. **Foundational ontology loading** — register ontologies defined in `config.yaml` (Schema.org, Dublin Core, FOAF, etc.)
4. **Class embedding generation** — generate lexical embeddings for each loaded ontology's classes
5. **Property embedding generation** — extract properties from foundational ontology source files, generate multi-channel lexical embeddings (label 0.5, domain/range context 0.3, comment 0.2)
6. **Structural embedding generation** — generate RDF2Vec embeddings from random walks over the ontology graph (classes and properties in a shared embedding space)

You can re-run setup at any time to add more ontologies or test new backends.

## demo.py

Interactive induction walkthrough:

1. **Health check** — verifies all services are reachable
2. **Browse data catalog** — lists available datasources, you select one or more
3. **Browse ontology catalog** — shows loaded foundational ontologies, you choose grounding sources
4. **Induction** — configure URI prefix, namespace, confidence threshold, induction strategy (`table_to_ontology` or `rigor_ontology`), and scoring strategy (`lexical` or `structural_fusion`), then watch the pipeline run
5. **Results** — color-coded match table (exact / high confidence / ambiguous / novel), with optional top-K candidate breakdown showing lexical, structural, and fused scores
6. **Validation** — optional multi-tier validation: HermiT consistency, taxonomy cycles, connectivity, OntoQA structural metrics, OoPS! pitfall detection
7. **Export** — view the induced ontology as Turtle
8. **Timing summary** — wall-clock duration for every step

## Configuration

All demo defaults are in `config.yaml`:

- `services` — URLs for all platform services (shared by `setup.py` and `demo.py`)
- `induction_defaults` — default values for the demo prompts (URI prefix, label, confidence threshold, scoring strategy, structural weight)
- `foundational_ontologies` — cross-industry ontologies (Tier 1, below)
- `customer_ontologies` — the customer's own domain ontology (Tier 2, below)

## Customer-provided ontologies (three-tier grounding)

The induction pipeline grounds induced concepts against **three tiers** of prior knowledge:

| Tier | Source | Examples | Match value |
|---|---|---|---|
| **Tier 1: Foundational** | Cross-industry standards, shipped via `foundational_ontologies` | Schema.org, Dublin Core, FOAF, PROV-O, FIBO modules | generic — "this column is a date" |
| **Tier 2: Customer-provided** | The customer's own domain ontology, registered via `customer_ontologies` | ACORD for insurance, FHIR/HL7 for healthcare, an internal corporate data dictionary | high-value — "this column aligns with your `Claim` class" |
| **Tier 3: Novel** | Concepts neither tier covered | Fully domain-specific inventions the pipeline had to synthesize from the schema | to-review list |

The demo uses the [swigroup P&C Ontology](https://github.com/swigroup/P-C-Ontology) (Koutsomitropoulos 2017) as a stand-in for ACME's in-house insurance ontology. It's a published OWL ontology based on the same OMG P&C Data Model the demo DDL derives from.

### How the tiers surface in the output

- **`setup.py` Step 2** — prints tier headers (`FOUNDATIONAL TIER` / `CUSTOMER TIER`) as each ontology registers, plus a per-tier count in the final summary.
- **`demo.py` Step 2** — the "Grounding Ontologies" table has a `Tier` column so the distinction is visible before induction runs.
- **`demo.py` Step 4** — match summary splits `Grounded to customer` vs `Grounded to foundational` vs `Novel`, with guidance text on how to read each number.
- **Step 4b benchmark scorecard** — when a golden ontology is registered for the datasource, the F1 report includes grounded_customer / grounded_foundational counts so you can see how much of the accepted ontology came from each tier.

### Property extraction defaults

- **Customer ontologies**: `extract_all_properties` defaults to `true`. A customer brings their own ontology because it models their domain — we use the whole property set, not just properties touching the `sample_classes` they listed. Override with `extract_all_properties: false` on the entry if you want filter-by-class behavior.
- **Foundational ontologies**: `extract_all_properties` defaults to `false`. These are large cross-industry ontologies (Schema.org alone has ~1700 properties) — we use the `sample_classes` list as a curated filter to keep the Bedrock embedding cost bounded.

### What if the customer's ontology references classes from another ontology?

A customer ontology may use `rdfs:subClassOf`, `rdfs:domain`, or `rdfs:range` to reference classes defined elsewhere (for example, declaring `swigroup:Policy rdfs:subClassOf fibo:Contract`). Three cases:

1. **Both ontologies loaded** — recommended. Declare both as separate entries in `foundational_ontologies` / `customer_ontologies`. Each registers, embeds, and participates in grounding independently. The `rdfs:subClassOf` edge is preserved in the cached Turtle for any downstream tools that walk the chain.
2. **Reference to an unloaded namespace** — `/fetch` detects this and returns `unresolved_references` in its response. `setup.py` prints a yellow warning listing the dangling namespaces and sample IRIs. The fetch still succeeds; grounding to those specific classes just won't work until the missing ontology is also loaded.
3. **Reference to standard RDF/RDFS/OWL/XSD vocabulary** — always treated as known; no warning.

The engine does **not** auto-resolve `owl:imports` — customers explicitly list the ontologies they want loaded. This is intentional: transitive imports can cascade into large unexpected ingestions, and the warnings let the customer see exactly which declarations are needed.

## Tips

- Select `none` for grounding ontologies to see what happens when everything is induced as novel
- Lower the confidence threshold (e.g. `0.5`) to see more ambiguous matches
- Try `structural_fusion` strategy and compare candidate scores against `lexical`
- Run with a subset of tables first to keep output concise
- If you skip setup, the demo still works — it just treats all concepts as novel

## Running services

The ontology-engine is a consolidated FastAPI app — all ontology / embedding /
induction / validation / proposals routers live under one process. The demo
needs two services:

```bash
# Terminal 1: mock data-catalog (test fixture service) on :8003
cd packages/ontology-engine/tests/fixtures/data-catalog
uv run uvicorn app.main:app --port 8003

# Terminal 2: consolidated ontology-engine on :8001
cd packages/ontology-engine
# Point at your Neptune DB + OpenSearch Serverless + DynamoDB backends.
# All env vars read by the engine are documented as os.getenv() in
# packages/ontology-engine/src/coa_ontology/.
export WORKBENCH_BACKEND=opensearch_neptune
export NDB_ENDPOINT=...
export OSS_ENDPOINT=...
export DYNAMODB_TABLE=...
# (etc. — see the engine package's module-level config for the full list)
uv run uvicorn coa_ontology.main:app --port 8001
```

## Example: P&C Insurance benchmark

A 13-table, 65-column Property & Casualty insurance schema is bundled for
reproducible testing. It comes from the OMG P&C Data Model (dtc/13-04-15),
published as Appendix 9.1 of:

> Sequeda, J., Allemang, D., Jacob, B. (2023). *A Benchmark to Understand
> the Role of Knowledge Graphs on Large Language Model's Accuracy for
> Question Answering on Enterprise SQL Databases.* arXiv:2311.07509

Files in this directory:

- `pc-insurance-ddl.sql` — raw DDL, source of truth (hand-authored)
- `parse_ddl_to_config.py` — DDL → YAML via sqlglot (idempotent)
- `pc-insurance-tables.yaml` — parsed intermediate (committed as checkpoint)
- `stage_fixtures.py` — writes catalog fixtures so the schema is browsable
  as datasource `ds-pc-insurance`

**To use:**

```bash
# 1. Generate the catalog fixtures (re-run any time the DDL changes).
python demo/parse_ddl_to_config.py
python demo/stage_fixtures.py

# 2. Restart the data-catalog service so it reloads sample_data/*.json.

# 3. Run the demo — pick ds-pc-insurance at Step 1.
python demo/demo.py
```

The catalog service picks up the generated fixtures automatically. After
staging, you can verify via:

```bash
curl http://localhost:8003/api/v1/catalogs/ds-pc-insurance
```

**Expected run metrics** (reference only — varies with foundational ontologies loaded, LLM temperature, and Schema.org drift):

| Metric | Value |
|---|---|
| Tables processed | 13 / 13 |
| Columns processed | 65 / 65 |
| Matched count | ~68 |
| Novel classes created | ~3 |
| Wall-clock (`table_to_ontology` strategy) | ~15-30 seconds |

**Note on reproducibility:** foundational ontologies are downloaded at
runtime from public URLs (Schema.org, Dublin Core, PROV-O, etc.). These
can change, which may shift matching metrics across runs. If you need
fully-deterministic benchmarks, pin the `source_url` values in
`config.yaml` to dated snapshot URLs.
