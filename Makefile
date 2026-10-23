.PHONY: help setup fmt lint test up down logs migrate

UV ?= uv

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "%-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install locked Python 3.13 development dependencies (requires uv)
	$(UV) sync --locked

fmt: ## Format Python source and tests
	$(UV) run --locked ruff check --fix .
	$(UV) run --locked ruff format .

lint: ## Check Python lint and formatting
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .

test: ## Run deterministic CPU tests (no GPU or model API calls)
	$(UV) run --locked pytest

up: ## Build and start the local web service
	docker compose up --build -d --wait

down: ## Stop the web service, retaining its data volume
	docker compose down

logs: ## Follow web service logs
	docker compose logs -f web

migrate: ## Initialize or check the local SQLite schema
	$(UV) run --locked python -m quartermaster.db
