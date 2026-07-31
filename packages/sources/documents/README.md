# Documents

Document ingestion pipeline for the Context Ontology Accelerator. Copied from `unstructured-data-ingestion` and refactored into the `coa_sources.documents` submodule.

## Package Structure

```text
packages/sources/documents/       ← deployment unit artifacts (Dockerfiles, requirements)
├── preprocessing/                 # Dockerfile + requirements for preprocessing Lambda
├── kg-build/                      # Dockerfile + requirements for KG Build ECS task
├── deletion/                      # requirements for deletion Lambda
└── trigger/                       # requirements for trigger Lambda

packages/sources/src/
└── coa_sources/
    └── documents/                 ← Python source (importable package)
        ├── api/                   # Doc source CRUD Lambda handler
        ├── preprocessing/         # PDF/DOCX → text conversion
        ├── kg_build/              # GraphRAG KG build + cleanup
        ├── deletion/              # S3 cleanup
        └── trigger/               # SQS → Step Functions trigger
```

## Relationship to unstructured-data-ingestion

This is a copy of `packages/unstructured-data-ingestion` with the business logic moved into `src/coa_sources/documents/` following the standard `src/` package layout used by `structured-data-ingestion` and `context-manager`. The original package remains unchanged and continues to serve the existing `/doc-sources` API.
