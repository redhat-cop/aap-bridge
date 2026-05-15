.PHONY: help install install-dev clean format lint typecheck test test-unit test-integration \
       test-performance test-cov check docs docs-serve \
       init-env setup version venv install-editable all \
       build build-api build-ui build-all up up-dev down shell shell-engine logs \
       ensure-bridge-dev-image ensure-api-ui-images web-install web-dev web-build serve

.DEFAULT_GOAL := help

# ===========================================================================
#  Local development (runs on host, no containers needed)
# ===========================================================================

VENV := .venv
PYTHON3 := python3
PYTHON312 := $(shell command -v python3.12 2>/dev/null)
PYTHON := $(VENV)/bin/python

# Prefer uv when installed; override with: make setup USE_UV=0
USE_UV ?= $(shell command -v uv >/dev/null 2>&1 && echo 1 || echo 0)
ifeq ($(USE_UV),1)
  PIP := uv pip
else
  PIP := $(VENV)/bin/pip
endif

PYTEST := $(PYTHON) -m pytest
BLACK := $(PYTHON) -m black
ISORT := $(PYTHON) -m isort
RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy

SRC_DIR := src
TESTS_DIR := tests
DOCS_DIR := docs

define require_venv
	@test -x "$(PYTHON)" || { \
		echo "Missing $(VENV). Run 'make setup' first."; \
		exit 1; \
	}
endef

help: ## Show this help message
	@echo "AAP Bridge - Development Commands"
	@echo ""
	@echo "  Local development (no containers):"
	@echo "    make setup                         # Complete dev setup (uv or pip)"
	@echo "    make setup USE_UV=0                # Force stdlib venv + pip"
	@echo "    make test                          # Run all tests"
	@echo "    make check                         # Format + lint + typecheck + test"
	@echo "    make docs-serve                    # Serve docs locally"
	@echo ""
	@echo "  Container CLI workflow (optional):"
	@echo "    podman login registry.redhat.io    # One-time Red Hat registry login"
	@echo "    make init-env                      # Create .env for shared config"
	@echo "    make build                         # Build the CLI container images"
	@echo "    make up-dev                        # Start db + bridge container"
	@echo "    make shell                         # Open a shell in the bridge container"
	@echo "    make down                          # Stop the running containers"
	@echo ""
	@echo "  Web UI workflow (optional):"
	@echo "    make build-all                     # Build API + UI images"
	@echo "    make up                            # Start db + engine + ui"
	@echo "    make shell-engine                  # Open a shell in the engine container"
	@echo "    make web-dev                       # Start the Vite dev server"
	@echo ""
	@echo "  All targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-28s\033[0m %s\n", $$1, $$2}'

venv: ## Create virtual environment in .venv
ifeq ($(USE_UV),1)
	uv venv --seed --python 3.12 --allow-existing
else
	@if [ ! -d "$(VENV)" ]; then \
		if [ -n "$(PYTHON312)" ]; then \
			"$(PYTHON312)" -m venv "$(VENV)"; \
		elif $(PYTHON3) -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'; then \
			$(PYTHON3) -m venv "$(VENV)"; \
		else \
			echo "Python 3.12 is required for the pip-based setup path."; \
			echo "Install python3.12 (or the python3.12-venv package on Debian/Ubuntu),"; \
			echo "or install uv and re-run: make setup"; \
			exit 1; \
		fi; \
	fi
endif

install: venv ## Install production dependencies
	$(require_venv)
	$(PIP) install -r requirements.txt

install-dev: venv ## Install development dependencies
	$(require_venv)
	$(PIP) install -r requirements-dev.txt
	$(PYTHON) -m pre_commit install

install-editable: venv ## Install package in editable mode
	$(require_venv)
	$(PIP) install -e .

clean: ## Clean up generated files
	find . -type f -name '*.py[co]' -delete
	find . -type d -name '__pycache__' -delete
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf build dist .eggs htmlcov .coverage coverage.xml .pytest_cache .mypy_cache .ruff_cache
	rm -f migration_state.db*

format: venv ## Format code with black and isort
	$(require_venv)
	$(BLACK) $(SRC_DIR) $(TESTS_DIR)
	$(ISORT) $(SRC_DIR) $(TESTS_DIR)

lint: venv ## Run linters (ruff)
	$(require_venv)
	$(RUFF) check $(SRC_DIR) $(TESTS_DIR)

typecheck: venv ## Run type checking with mypy
	$(require_venv)
	$(MYPY) $(SRC_DIR)

test: venv ## Run all tests
	$(require_venv)
	$(PYTEST) $(TESTS_DIR)

test-unit: venv ## Run only unit tests
	$(require_venv)
	$(PYTEST) $(TESTS_DIR)/unit -v

test-integration: venv ## Run only integration tests
	$(require_venv)
	$(PYTEST) $(TESTS_DIR)/integration -v -m integration

test-performance: venv ## Run only performance tests
	$(require_venv)
	$(PYTEST) $(TESTS_DIR)/performance -v -m performance

test-cov: venv ## Run tests with coverage report
	$(require_venv)
	$(PYTEST) $(TESTS_DIR) --cov=$(SRC_DIR) --cov-report=html --cov-report=term

.PHONY: test-watch
test-watch: venv ## Run tests in watch mode
	$(require_venv)
	$(PYTEST) $(TESTS_DIR) -f

check: format lint typecheck test ## Run all checks (format, lint, typecheck, test)

.PHONY: pre-commit
pre-commit: venv ## Run pre-commit hooks on all files
	$(require_venv)
	$(PYTHON) -m pre_commit run --all-files

docs: venv ## Build documentation
	$(require_venv)
	$(PIP) install -e ".[docs]"
	$(PYTHON) -m mkdocs build

docs-serve: venv ## Serve documentation locally
	$(require_venv)
	$(PIP) install -e ".[docs]"
	$(PYTHON) -m mkdocs serve -a localhost:8001

.PHONY: run-example
run-example: venv ## Run example migration (requires config)
	$(require_venv)
	$(PYTHON) -m aap_migration.cli migrate full --config config/config.yaml --dry-run

init-env: ## Initialize .env file from .env.example
	@if [ ! -f .env ]; then \
		db_password="$$( $(PYTHON3) -c 'import secrets; print(secrets.token_hex(16))' )"; \
		cp .env.example .env; \
		{ \
			echo ""; \
			echo "# Container CLI workflow credentials (generated by make init-env)"; \
			echo "POSTGRESQL_USER=aap_migration_user"; \
			echo "POSTGRESQL_PASSWORD=$$db_password"; \
			echo "POSTGRESQL_DATABASE=aap_migration"; \
			echo "POSTGRESQL_ADMIN_PASSWORD=$$db_password"; \
		} >> .env; \
		echo ".env file created from .env.example"; \
		echo "Generated PostgreSQL credentials for the container CLI workflow"; \
		echo "Please edit .env with your actual configuration"; \
	else \
		echo ".env file already exists"; \
	fi

setup: install-dev install-editable init-env ## Complete development setup

version: venv ## Show current version
	$(require_venv)
	@$(PYTHON) -c 'from importlib.metadata import version; print(f"AAP Bridge v{version(\"aap-bridge\")}")' 2>/dev/null || echo "Package not installed"

all: check docs ## Run all checks and build docs

# ===========================================================================
#  Optional container CLI workflow (requires podman)
# ===========================================================================

COMPOSE          := podman compose
BRIDGE_SVC       := bridge
BRIDGE_IMAGE     := localhost/aap-bridge:latest
BRIDGE_DEV_IMAGE := localhost/aap-bridge-dev:latest
BRIDGE_API_IMAGE := localhost/aap-bridge-api:latest
UI_IMAGE         := localhost/aap-bridge-ui:latest

build: ## Build aap-bridge container image (base + dev)
	podman build -t $(BRIDGE_IMAGE) --target base .
	podman build -t $(BRIDGE_DEV_IMAGE) -f Containerfile.dev .

build-api: ## Build engine+API container image
	podman build -t $(BRIDGE_API_IMAGE) --target api .

build-ui: ## Build UI container image
	podman build -t $(UI_IMAGE) -f Containerfile.ui .

build-all: build-api build-ui ## Build engine + UI container images

ensure-bridge-dev-image:
	@podman image exists $(BRIDGE_DEV_IMAGE) || { \
		echo "Missing $(BRIDGE_DEV_IMAGE). Run 'make build' first."; \
		exit 1; \
	}

ensure-api-ui-images:
	@podman image exists $(BRIDGE_API_IMAGE) || { \
		echo "Missing $(BRIDGE_API_IMAGE). Run 'make build-all' first."; \
		exit 1; \
	}
	@podman image exists $(UI_IMAGE) || { \
		echo "Missing $(UI_IMAGE). Run 'make build-all' first."; \
		exit 1; \
	}

up: ensure-api-ui-images ## Start db + engine + ui using prebuilt images
	$(COMPOSE) up -d --no-build db engine ui

up-dev: ensure-bridge-dev-image ## Start db + bridge using prebuilt images
	$(COMPOSE) up -d --no-build db bridge

down: ## Stop all containers
	$(COMPOSE) down

shell: ## Shell into bridge container
	$(COMPOSE) exec $(BRIDGE_SVC) /bin/bash

shell-engine: ## Shell into engine container
	$(COMPOSE) exec engine /bin/bash

logs: ## Tail all container logs
	$(COMPOSE) logs -f

web-install: ## Install frontend dependencies
	cd web && npm ci

web-dev: ## Start Vite dev server (proxies API to localhost:8000)
	cd web && npm run dev

web-build: ## Build frontend for production
	cd web && npm run build

serve: ## Start FastAPI API server (requires pip install '.[api]')
	aap-bridge serve --host 0.0.0.0 --port 8000
