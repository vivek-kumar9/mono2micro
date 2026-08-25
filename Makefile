# mono2micro - monolith to microservice migration assistant
# All targets run offline in mock mode (no API key). For real LLM mode:
#   export LLM_MODE=real ANTHROPIC_API_KEY=sk-... ANTHROPIC_MODEL=claude-sonnet-5

PYTHON ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.DEFAULT_GOAL := help
.PHONY: help install analyze decompose eval contracts review approve generate demo test clean pipeline all

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install dependencies
	python3 -m venv .venv
	./.venv/bin/python -m pip install -q --upgrade pip
	./.venv/bin/python -m pip install -q -r requirements.txt
	@echo "Installed. Activate with: source .venv/bin/activate"

analyze: ## Static analysis -> context packs + dependency graph
	$(PYTHON) -m agents.orchestrator analyze

decompose: ## Clustering + LLM refine + full evaluation harness
	$(PYTHON) -m agents.orchestrator decompose

eval: decompose ## (Re)run evaluation and print the report
	@echo "" && cat eval/report.md

contracts: ## Generate + validate OpenAPI 3.1 contracts per service
	$(PYTHON) -m agents.orchestrator contracts

review: ## Launch the Streamlit HITL review app (interactive gate)
	$(PYTHON) -m streamlit run review_ui/app.py

approve: ## Non-interactive approval (mirrors the Streamlit gate)
	$(PYTHON) -m agents.orchestrator approve

generate: ## Codegen service + strangler gateway + contract tests (needs approval)
	$(PYTHON) -m agents.orchestrator generate

demo: ## Run the strangler topology (docker if available, else in-process)
	./scripts/demo.sh

verify-runtime: ## Prove the exact container CMDs work over real HTTP (Docker-free)
	./scripts/verify_runtime.sh

test: ## Run the whole test suite (tooling + generated contract + strangler)
	$(PYTHON) -m pytest

pipeline: analyze decompose contracts ## Analysis through contracts (no approval)

all: analyze decompose contracts approve generate ## Full non-interactive pipeline including codegen

clean: ## Remove generated artifacts (keeps ground truth + source)
	rm -rf generated/services generated/gateway generated/tests generated/contracts
	rm -f generated/*.json generated/*.jsonl eval/metrics.json eval/report.md eval/approved_decomposition.json
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."
