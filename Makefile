# CloudPulse AI — local gate.
#
# `make check` runs the same categories as the PR gate in .github/workflows/ci.yml
# (FR-009). A green run here should mean a green run there.
#
# Exceptions, stated rather than hidden: the secret scan, the OpenAPI contract diff,
# and the generated-client drift check need git history or a network fetch, so they
# run in CI only. `make check` covers the seven that run locally.

.PHONY: help check lint typecheck test test-integration frontend-lint frontend-build tf-validate deps-check boundary-check install

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install backend dev dependencies and frontend packages
	cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm ci

check: lint typecheck test frontend-lint frontend-build tf-validate deps-check boundary-check ## Run the full local gate

lint: ## ruff (FR-009)
	cd backend && ruff check . && ruff format --check .

typecheck: ## mypy strict (FR-009)
	cd backend && mypy .

test: ## pytest unit tests -- no AWS credentials, mocked cloud APIs (FR-010)
	cd backend && AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= AWS_PROFILE= \
		pytest tests/unit -m "not integration"

test-integration: ## pytest integration tests -- needs Docker (R-007)
	cd backend && pytest tests/integration -m integration

frontend-lint: ## eslint incl. accessibility rules (FR-047b)
	cd frontend && npm run lint

frontend-build: ## Angular production build (FR-009)
	cd frontend && npm run build

tf-validate: ## terraform fmt + validate for both environments (FR-009)
	terraform -chdir=infra/envs/dev init -backend=false && terraform -chdir=infra/envs/dev validate
	terraform -chdir=infra/envs/prod init -backend=false && terraform -chdir=infra/envs/prod validate
	terraform fmt -check -recursive infra/

deps-check: ## Fail if a non-AWS AI SDK entered a manifest (FR-013a, Principle II)
	python3 ops/scripts/check_dependencies.py

boundary-check: ## Fail if a provider SDK type leaked out of connectors/ (FR-054)
	python3 ops/scripts/check_connector_boundary.py
