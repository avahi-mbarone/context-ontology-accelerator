# COA Invoke — E2E testing for the serve layer
#
# Default: `make` or `make serve` — production behavior (full cascade)
#
# Usage:
#   make serve NS=<namespace-id> Q="How many customers are there?"
#   make ontop NS=<namespace-id> Q="What are all customer names?"
#   make doctor NS=<namespace-id>
#
# Routing behavior:
#
#   Input              Tier 1   Tier 2             Tier 3     On Failure
#   ─────────────────  ──────   ────────────────   ────────   ─────────────────────
#   (default)          runs     DEFAULT_STRATEGY   fallback   Tier 3 answers
#   tierOverride=1     runs     skip               skip       ValueError (pinned)
#   tierOverride=2     skip     DEFAULT_STRATEGY   skip       ValueError (pinned)
#   tierOverride=3     skip     skip               runs       Tier 3 answers
#   startTier=2        skip     DEFAULT_STRATEGY   fallback   Tier 3 answers
#   startTier=3        skip     skip               runs       Tier 3 answers
#   strategy="ontop"   runs     Ontop only         fallback   Tier 3 answers
#   strategy="best"    runs     Parallel both      fallback   Tier 3 answers
#
#   tierOverride = pinned (fail if that tier can't answer, no fallback to other tiers)
#   startTier    = skip earlier tiers, still falls through on failure
#   strategy     = controls Tier 2 behavior only, always falls to Tier 3 on failure

SHELL := /bin/bash
INVOKE := python3 invoke.py
NS ?=
Q ?= How many customers are there?

.DEFAULT_GOAL := serve

# ── Production default ─────────────────────────────────────────────────

serve: ## Full cascade — production behavior, same as a user hit UI 
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)"}'

# ── Tier 2: Structured Query strategies ────────────────────────────────

ontop: ## Strategy: Ontop only (NL→SPARQL→VKG→SQL)
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"strategy":"ontop"}}'

nl_to_sql: ## Strategy: NL-to-SQL only (retrieval + LLM SQL generation)
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"strategy":"nl_to_sql"}}'

best: ## Strategy: run both in parallel, return highest confidence
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"strategy":"best"}}'

ontop_first: ## Strategy: Ontop → NL-to-SQL fallback
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"strategy":"ontop_first"}}'

nl_to_sql_first: ## Strategy: NL-to-SQL → Ontop fallback
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"strategy":"nl_to_sql_first"}}'

# ── Tier overrides (maps to strategies internally) ─────────────────────

tier1: ## tierOverride=1 — Metric match only
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"tierOverride":1}}'

tier2: ## tierOverride=2 — Structured query only (default Tier2 strategy, no Tier 3 fallback)
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"tierOverride":2}}'

tier3: ## tierOverride=3 — Synthesis only (skip structured query)
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"tierOverride":3}}'

# ── Start tier (skip earlier tiers, run from specified tier onward) ────

start_tier2: ## startTier=2 — skip metric match, start at structured query
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"startTier":2}}'

start_tier3: ## startTier=3 — skip structured query, go to synthesis
	@$(INVOKE) '{"query":"$(Q)","namespace":"$(NS)","options":{"startTier":3}}'

# ── Diagnostics ───────────────────────────────────────────────────────

doctor: ## Health check — verify namespace has Neptune, OSS, VKG, auth all ready
	@python3 doctor.py $(NS)

# ── Benchmark ─────────────────────────────────────────────────────────
#
# The BIRD benchmark moved to the top-level multi-benchmark harness under
# `benchmarks/` (shared common/ invoker + gold executor + partial-credit
# scoring, plus per-benchmark evaluate.py and setup). Run it from there:
#
#   uv pip install -r benchmarks/requirements.txt
#   PYTHONPATH=. uv run python benchmarks/bird-benchmark/setup/provision_ns.py   # -> NAMESPACE_ID=...
#   uv run python benchmarks/bird-benchmark/evaluation/evaluate.py --namespace <NS> --prefix <PREFIX>
#
# GoldExecutor auto-starts the SSM tunnel (benchmarks/common/tunnel.sh) on
# connect. The mainline CI `benchmark` job (ci/mainline.yml) drives the same path.

# ── Help ──────────────────────────────────────────────────────────────

help: ## Show targets
	@grep -E '^[a-zA-Z_0-9-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

.PHONY: serve ontop nl_to_sql best ontop_first nl_to_sql_first tier1 tier2 tier3 start_tier2 start_tier3 doctor help
