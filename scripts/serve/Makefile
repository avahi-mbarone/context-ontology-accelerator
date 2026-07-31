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
# Run BIRD mini-dev benchmark against deployed serve layer.
#
# Usage:
#   make benchmark                                    # default strategy+model, all 500 questions
#   make benchmark BENCH_STRATEGY=ontop BENCH_MODEL=us.anthropic.claude-opus-4-6-v1
#   make benchmark BENCH_CATEGORY=aggregation BENCH_QUESTIONS=0-49
#   make benchmark-strategies                         # compare all 5 strategies
#   make benchmark-models                             # compare 3 models
#   make benchmark-matrix                             # full cartesian (strategies × models)
#   make benchmark-report                             # generate comparison table

BENCH_NS         ?= $(NS)
BENCH_MODEL      ?=
BENCH_STRATEGY   ?=
BENCH_CATEGORY   ?=
BENCH_QUESTIONS  ?= all
BENCH_PARALLEL   ?= 4
BENCH_TIER       ?= 2
BENCH_SKIP_GOLD  ?=
BENCH_NO_CACHE   ?=
BENCH_MODELS     ?= us.anthropic.claude-sonnet-4-6,us.anthropic.claude-opus-4-6-v1,us.anthropic.claude-opus-4-8
BENCH_STRATEGIES ?= nl_to_sql_first,ontop_first,nl_to_sql,ontop,best

comma := ,
space := $(subst ,, )

benchmark: ## Run benchmark — single strategy+model
	@python3 benchmark/runner.py \
		--namespace $(BENCH_NS) \
		--tier $(BENCH_TIER) \
		--parallel $(BENCH_PARALLEL) \
		--questions "$(BENCH_QUESTIONS)" \
		$(if $(BENCH_MODEL),--model $(BENCH_MODEL)) \
		$(if $(BENCH_STRATEGY),--strategy $(BENCH_STRATEGY)) \
		$(if $(BENCH_CATEGORY),--category $(BENCH_CATEGORY)) \
		$(if $(BENCH_SKIP_GOLD),--skip-gold) \
		$(if $(BENCH_NO_CACHE),--no-cache)

benchmark-strategies: ## Compare all strategies (same model)
	@echo ""
	@echo "════════════════════════════════════════════════════════════"
	@echo "  Benchmark: ALL STRATEGIES"
	@echo "  Strategies: $(BENCH_STRATEGIES)"
	@echo "  Model:      $(or $(BENCH_MODEL),(default))"
	@echo "  Questions:  $(BENCH_QUESTIONS)"
	@echo "  Runs:       $(words $(subst $(comma),$(space),$(BENCH_STRATEGIES)))"
	@echo "  Est. time:  ~$(shell echo $$(($(words $(subst $(comma),$(space),$(BENCH_STRATEGIES))) * 35))) min"
	@echo "════════════════════════════════════════════════════════════"
	@read -p "  Proceed? [Y/n] " confirm; confirm=$${confirm:-y}; case "$$confirm" in [yY]|[yY][eE][sS]) ;; *) echo "  Aborted."; exit 1 ;; esac
	@for s in $(subst $(comma),$(space),$(BENCH_STRATEGIES)); do \
		echo "" ; \
		echo "═══ Strategy: $$s ═══" ; \
		python3 benchmark/runner.py -y \
			--namespace $(BENCH_NS) --tier $(BENCH_TIER) \
			--parallel $(BENCH_PARALLEL) --questions "$(BENCH_QUESTIONS)" \
			--strategy $$s \
			$(if $(BENCH_MODEL),--model $(BENCH_MODEL)) \
			$(if $(BENCH_CATEGORY),--category $(BENCH_CATEGORY)) ; \
	done
	@python3 benchmark/report.py --all

benchmark-models: ## Compare multiple models (same strategy)
	@echo ""
	@echo "════════════════════════════════════════════════════════════"
	@echo "  Benchmark: ALL MODELS"
	@echo "  Models:     $(BENCH_MODELS)"
	@echo "  Strategy:   $(or $(BENCH_STRATEGY),(default))"
	@echo "  Questions:  $(BENCH_QUESTIONS)"
	@echo "  Runs:       $(words $(subst $(comma),$(space),$(BENCH_MODELS)))"
	@echo "  Est. time:  ~$(shell echo $$(($(words $(subst $(comma),$(space),$(BENCH_MODELS))) * 35))) min"
	@echo "════════════════════════════════════════════════════════════"
	@read -p "  Proceed? [Y/n] " confirm; confirm=$${confirm:-y}; case "$$confirm" in [yY]|[yY][eE][sS]) ;; *) echo "  Aborted."; exit 1 ;; esac
	@for m in $(subst $(comma),$(space),$(BENCH_MODELS)); do \
		echo "" ; \
		echo "═══ Model: $$m ═══" ; \
		python3 benchmark/runner.py -y \
			--namespace $(BENCH_NS) --tier $(BENCH_TIER) \
			--parallel $(BENCH_PARALLEL) --questions "$(BENCH_QUESTIONS)" \
			--model $$m \
			$(if $(BENCH_STRATEGY),--strategy $(BENCH_STRATEGY)) \
			$(if $(BENCH_CATEGORY),--category $(BENCH_CATEGORY)) ; \
	done
	@python3 benchmark/report.py --all

benchmark-matrix: ## Full cartesian: all strategies × all models
	@echo ""
	@echo "════════════════════════════════════════════════════════════"
	@echo "  Benchmark: FULL MATRIX"
	@echo "  Strategies: $(BENCH_STRATEGIES)"
	@echo "  Models:     $(BENCH_MODELS)"
	@echo "  Questions:  $(BENCH_QUESTIONS)"
	@echo "  Runs:       $(shell echo $$(($(words $(subst $(comma),$(space),$(BENCH_STRATEGIES))) * $(words $(subst $(comma),$(space),$(BENCH_MODELS))))))"
	@echo "  Est. time:  ~$(shell echo $$(($(words $(subst $(comma),$(space),$(BENCH_STRATEGIES))) * $(words $(subst $(comma),$(space),$(BENCH_MODELS))) * 35))) min"
	@echo "════════════════════════════════════════════════════════════"
	@read -p "  Proceed? [Y/n] " confirm; confirm=$${confirm:-y}; case "$$confirm" in [yY]|[yY][eE][sS]) ;; *) echo "  Aborted."; exit 1 ;; esac
	@for m in $(subst $(comma),$(space),$(BENCH_MODELS)); do \
		for s in $(subst $(comma),$(space),$(BENCH_STRATEGIES)); do \
			echo "" ; \
			echo "═══ $$m / $$s ═══" ; \
			python3 benchmark/runner.py -y \
				--namespace $(BENCH_NS) --tier $(BENCH_TIER) \
				--parallel $(BENCH_PARALLEL) --questions "$(BENCH_QUESTIONS)" \
				--model $$m --strategy $$s \
				$(if $(BENCH_CATEGORY),--category $(BENCH_CATEGORY)) ; \
		done ; \
	done
	@python3 benchmark/report.py --all

benchmark-report: ## Show comparison table from saved results
	@python3 benchmark/report.py --all

benchmark-tunnel: ## Start SSM port-forward tunnel to gold DB (required for accuracy)
	@bash benchmark/tunnel.sh --background

benchmark-tunnel-stop: ## Stop the SSM tunnel
	@if [ -f benchmark/.tunnel.pid ]; then \
		kill $$(cat benchmark/.tunnel.pid) 2>/dev/null && echo "✅ Tunnel stopped" || echo "⚠️  Tunnel already stopped"; \
		rm -f benchmark/.tunnel.pid; \
	else \
		echo "No tunnel PID file found."; \
	fi

benchmark-tunnel-fg: ## Start SSM tunnel in foreground (Ctrl+C to stop)
	@bash benchmark/tunnel.sh

# ── Help ──────────────────────────────────────────────────────────────

help: ## Show targets
	@grep -E '^[a-zA-Z_0-9-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

.PHONY: serve ontop nl_to_sql best ontop_first nl_to_sql_first tier1 tier2 tier3 start_tier2 start_tier3 doctor help
.PHONY: benchmark benchmark-strategies benchmark-models benchmark-matrix benchmark-report benchmark-tunnel benchmark-tunnel-stop benchmark-tunnel-fg
