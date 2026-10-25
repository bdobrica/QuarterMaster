.PHONY: help setup fmt lint test test-gpu test-export model-setup up down logs migrate

UV ?= uv
GPU_MODE ?= nvidia
GPU_WORKFLOW ?= spike

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

test-gpu: ## Opt in to local LoRA (GPU_WORKFLOW=spike or training; GPU_MODE=nvidia or wsl)
ifeq ($(GPU_WORKFLOW),training)
	$(UV) run --locked python -m quartermaster.training_smoke --run-gpu --gpu-mode "$(GPU_MODE)"
else ifeq ($(GPU_WORKFLOW),spike)
	$(UV) run --locked python -m quartermaster.spike.run --run-gpu --gpu-mode "$(GPU_MODE)"
else
	$(error GPU_WORKFLOW must be spike or training)
endif

test-export: ## Check standalone export in fresh offline Compose (EXPORT=/absolute/adviser.tar)
	test -n "$(EXPORT)"
	$(UV) run --locked python -m quartermaster.export_smoke --archive "$(EXPORT)"

model-setup: ## Explicitly prepare the pinned local CPU base model (download/build if absent)
	$(UV) run --locked python -m quartermaster.setup_local

up: ## Build and start the local web service
	docker compose up --build -d --wait

down: ## Stop the web service, retaining its data volume
	docker compose down

logs: ## Follow web service logs
	docker compose logs -f web

migrate: ## Initialize or check the local SQLite schema
	$(UV) run --locked python -m quartermaster.db
