# Contributing to Context Ontology Accelerator 

Thank you for your interest in contributing!

## How to Add a New Package

1. Create a new directory under `packages/` with the standard layout:
   - `pyproject.toml` with the package metadata
   - `src/<python_package_name>/__init__.py`
   - `tests/unit/` and `tests/integ/` directories
2. Add the package path to the root `pyproject.toml` workspace members.
3. Run `uv sync` to update the workspace lockfile.
4. Add a corresponding CDK stack under `infra/lib/stacks/services/` (TypeScript, kebab-case filename).

## Coding Standards

- **Python**: Follow [ruff](https://docs.astral.sh/ruff/) linting rules defined in `ruff.toml`.
- **Line length**: 120 characters max.
- **Type hints**: Required for all public functions.
- **Logging**: Use `structlog` via `libs/common` — no raw `print()` in library code.
- **API contracts**: All service APIs are defined in Smithy models under `models/`. Do not hand-write OpenAPI specs.

## PR Process

1. Create a feature branch from `main`.
2. Ensure all checks pass: `make lint && make test`.
3. Update `CHANGELOG.md` under the `[Unreleased]` section.
4. Request review from at least one team member.
5. Squash-merge to `main`.
