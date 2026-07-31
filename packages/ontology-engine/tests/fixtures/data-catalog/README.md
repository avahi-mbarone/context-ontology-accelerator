# Data Catalog — Test Fixture

Mock data-catalog service with an OpenMetadata-compatible REST API. Used
by this package's integration tests as a local stand-in for a production
catalog (OpenMetadata, AWS Glue, Unity Catalog, Snowflake, Collibra).

**Port:** `8003`
**Content:** 2 databases, 3 schemas, 8 tables with columns, FK constraints,
PII tags, and cross-schema references. Fixtures live in `app/fixtures/*.json`
and can be extended via `seeds/` scripts.

## Running

From the package root:

```bash
cd tests/fixtures/data-catalog
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8003
```

Then set `DATA_CATALOG_URL=http://localhost:8003` in your shell or `.env`
before running induction scripts or tests.

## Seeding a custom schema

See `../../../demo/parse_ddl_to_config.py` and `../../../demo/stage_fixtures.py`
for the pattern used to stage the OMG P&C Insurance benchmark schema into
this catalog programmatically.

## API

OpenMetadata-compatible subset:

```
GET  /api/v1/catalogs
GET  /api/v1/databases/
GET  /api/v1/databases/{id}
GET  /api/v1/databaseSchemas/
GET  /api/v1/databaseSchemas/{id}
GET  /api/v1/tables/
GET  /api/v1/tables/{id}
GET  /health
```

Interactive docs available at `http://localhost:8003/docs` when running.
