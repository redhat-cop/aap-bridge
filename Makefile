.PHONY: help install install-dev clean format lint typecheck test test-unit test-integration \
       test-performance test-cov check docs docs-serve \
       init-env setup version venv install-editable all \
<<<<<<< HEAD
       build build-api build-ui build-all up up-dev down shell shell-engine logs \
       ensure-bridge-dev-image ensure-api-ui-images web-install web-dev web-build serve
=======
       build build-api build-ui build-all prepare-pgdata up up-dev down shell shell-engine logs \
       ensure-bridge-dev-image ensure-api-ui-images \
       c-test c-lint c-format c-typecheck c-check \
       web-install web-dev web-build serve \
       build-builder build-aap-bases build-aap build-aap-all \
       push-aap pull-aap list-golden \
       run-pair stop-pair reset-pair destroy-pair destroy-all \
       test-bridge test-all status shell-src shell-tgt
>>>>>>> ff01ed7 (feat(testing): add container-first AAP integration infrastructure)

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
	@echo "    make c-check                       # Run checks inside the bridge container"
	@echo "    make down                          # Stop the running containers"
	@echo ""
	@echo "  Web UI workflow (optional):"
	@echo "    make build-all                     # Build API + UI images"
	@echo "    make up                            # Start db + engine + ui"
	@echo "    make shell-engine                  # Open a shell in the engine container"
	@echo "    make web-dev                       # Start the Vite dev server"
	@echo ""
	@echo "  Integration testing:"
	@echo "    make build-builder                 # Build ansible runner (once)"
	@echo "    make build-aap-bases               # Build UBI base images (once)"
	@echo "    make build-aap VERSION=2.4         # Build AAP golden image (~45 min)"
	@echo "    make run-pair SOURCE=2.4 TARGET=2.6"
	@echo "    make test-bridge SOURCE=2.4 TARGET=2.6"
	@echo "    make test-all                      # Test all versions -> 2.6"
	@echo "    make reset-pair SOURCE=2.4 TARGET=2.6   # Reset instantly"
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
PROJECT_DIR      := $(shell pwd)
TESTING_DIR      := $(PROJECT_DIR)/tests/integration

define run-bridge
	$(COMPOSE) exec $(BRIDGE_SVC)
endef

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

c-test: ## Run unit tests inside bridge container
	$(run-bridge) python3.12 -m pytest tests/unit/ -v

c-lint: ## Run ruff linter inside bridge container
	$(run-bridge) python3.12 -m ruff check src/ tests/unit/

c-format: ## Run black + isort inside bridge container
	$(run-bridge) python3.12 -m black src/ tests/unit/
	$(run-bridge) python3.12 -m isort src/ tests/unit/

c-typecheck: ## Run mypy inside bridge container
	$(run-bridge) python3.12 -m mypy src/

c-check: c-lint c-typecheck c-test ## Run all checks inside bridge container

web-install: ## Install frontend dependencies
	cd web && npm ci

web-dev: ## Start Vite dev server (proxies API to localhost:8000)
	cd web && npm run dev

web-build: ## Build frontend for production
	cd web && npm run build

serve: ## Start FastAPI API server (requires pip install '.[api]')
	aap-bridge serve --host 0.0.0.0 --port 8000

# ===========================================================================
#  Integration testing - AAP golden images and test pairs (requires podman)
# ===========================================================================

BUILDER_IMAGE   := localhost/aap-bridge-builder:latest

# Auto-detect active pair from generated state; fall back to 2.4 -> 2.6
_PAIRS := $(wildcard tests/integration/generated/pairs/*-to-*)
ifeq ($(words $(_PAIRS)),1)
  _PAIR_NAME := $(notdir $(_PAIRS))
  SOURCE ?= $(shell echo '$(_PAIR_NAME)' | sed 's/\(.\)\(.*\)-to-.*/\1.\2/')
  TARGET ?= $(shell echo '$(_PAIR_NAME)' | sed 's/.*-to-\(.\)\(.*\)/\1.\2/')
else
  SOURCE ?= 2.4
  TARGET ?= 2.6
endif
VERSION  ?= 2.4
REGISTRY ?= localhost
V        ?= 0
DEBUG    ?= 0

VERBOSITY := $(if $(filter 1,$(V)),-v,$(if $(filter 2,$(V)),-vv,$(if $(filter 3,$(V)),-vvv,$(if $(filter 4,$(V)),-vvvv,))))
DEBUG_ARGS := $(if $(filter 1,$(DEBUG)),-e secure_logging=false,)

PODMAN_SOCK := $(shell echo $${XDG_RUNTIME_DIR}/podman/podman.sock)
VAULT_PASS_FILE := $(TESTING_DIR)/.vault_pass
VAULT_VARS_FILE := $(TESTING_DIR)/inventory/group_vars/vault.yml

ifneq (,$(wildcard $(VAULT_PASS_FILE)))
  VAULT_ARGS := --vault-password-file $(VAULT_PASS_FILE)
  ifneq (,$(wildcard $(VAULT_VARS_FILE)))
    VAULT_ARGS += -e @$(VAULT_VARS_FILE)
  endif
endif

define run-builder
	podman run --rm \
		-v $(PODMAN_SOCK):/run/podman/podman.sock \
		-v $(TESTING_DIR):$(TESTING_DIR) \
		-w $(TESTING_DIR) \
		--network host \
		--security-opt label=disable \
		$(if $(RHSM_USER),-e RHSM_USER=$(RHSM_USER)) \
		$(if $(RHSM_PASS),-e RHSM_PASS) \
		$(if $(RH_TOKEN),-e RH_TOKEN) \
		$(BUILDER_IMAGE) $(VERBOSITY) $(DEBUG_ARGS) $(VAULT_ARGS)
endef

build-builder: ## Build the ansible builder image
	podman build \
		-t $(BUILDER_IMAGE) \
		-f tests/integration/Containerfile.builder \
		tests/integration/

build-aap-bases: ## Build UBI base images for AAP containers
	$(run-builder) playbooks/build-base-images.yml

build-aap: ## Build AAP golden image (VERSION=2.4)
	@sudo sysctl -w kernel.keys.maxkeys=5000 2>/dev/null || true
	$(run-builder) playbooks/build-instance.yml \
		-e aap_version=$(VERSION)

build-aap-all: ## Build golden images for ALL versions
	@for v in 1.0 1.1 1.2 2.0 2.1 2.2 2.3 2.4 2.5 2.6; do \
		echo "=== Building AAP $$v ==="; \
		$(MAKE) build-aap VERSION=$$v || echo "WARN: AAP $$v build failed (may be best-effort)"; \
	done

push-aap: ## Push golden image to registry (VERSION=2.4 REGISTRY=quay.io/myorg)
	$(run-builder) playbooks/push-image.yml \
		-e aap_version=$(VERSION) \
		-e image_registry=$(REGISTRY)

pull-aap: ## Pull golden image from registry (VERSION=2.4 REGISTRY=quay.io/myorg)
	$(run-builder) playbooks/pull-image.yml \
		-e aap_version=$(VERSION) \
		-e image_registry=$(REGISTRY)

list-golden: ## List all golden images
	@podman images --filter 'reference=*aap-golden-*' \
		--format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.Created}}'

run-pair: ## Start AAP pair from golden images (SOURCE=2.4 TARGET=2.6)
	$(run-builder) playbooks/run-pair.yml \
		-e source_version=$(SOURCE) \
		-e target_version=$(TARGET)

stop-pair: ## Stop AAP pair containers (SOURCE=2.4 TARGET=2.6)
	-podman stop aap-$(subst .,,$(SOURCE))-src aap-$(subst .,,$(TARGET))-tgt

reset-pair: ## Reset pair to clean state (SOURCE=2.4 TARGET=2.6)
	$(run-builder) playbooks/reset-pair.yml \
		-e source_version=$(SOURCE) \
		-e target_version=$(TARGET)

destroy-pair: ## Remove pair containers and network (SOURCE=2.4 TARGET=2.6)
	$(run-builder) playbooks/destroy-pair.yml \
		-e source_version=$(SOURCE) \
		-e target_version=$(TARGET)

destroy-all: ## Remove ALL test containers, images, and networks
	$(run-builder) playbooks/destroy-all.yml

status: ## Show all test containers and golden images
	$(run-builder) playbooks/status.yml

test-bridge: up-dev ## Run aap-bridge against pair (dry-run) (SOURCE=2.4 TARGET=2.6)
	@PAIR_ID="$(subst .,,$(SOURCE))-to-$(subst .,,$(TARGET))"; \
	ENV_FILE_HOST="tests/integration/generated/pairs/$$PAIR_ID/.env"; \
	ENV_FILE_CONTAINER="/app/tests/integration/generated/pairs/$$PAIR_ID/.env"; \
	if [ ! -f "$$ENV_FILE_HOST" ]; then \
		echo "Error: No config at $$ENV_FILE_HOST. Run 'make run-pair' first."; \
		exit 1; \
	fi; \
	echo "Using config: $$ENV_FILE_HOST"; \
	$(run-bridge) bash -lc "set -a && source $$ENV_FILE_CONTAINER && set +a && aap-bridge migrate full --dry-run"

test-all: ## Run migration test for all source versions -> 2.6
	@PASS=""; FAIL=""; SKIP=""; \
	for v in 1.0 1.1 1.2 2.0 2.1 2.2 2.3 2.4 2.5; do \
		echo ""; \
		echo "============================================================"; \
		echo "  Testing migration: AAP $$v -> 2.6"; \
		echo "============================================================"; \
		if ! podman image exists localhost/aap-golden-$$v:latest 2>/dev/null; then \
			echo "SKIP: No golden image for AAP $$v"; \
			SKIP="$$SKIP $$v"; \
			continue; \
		fi; \
		$(MAKE) run-pair SOURCE=$$v TARGET=2.6 || { echo "FAIL: Could not start pair $$v -> 2.6"; FAIL="$$FAIL $$v"; continue; }; \
		if $(MAKE) test-bridge SOURCE=$$v TARGET=2.6; then \
			echo "PASS: AAP $$v -> 2.6"; \
			PASS="$$PASS $$v"; \
		else \
			echo "FAIL: AAP $$v -> 2.6"; \
			FAIL="$$FAIL $$v"; \
		fi; \
		$(MAKE) destroy-pair SOURCE=$$v TARGET=2.6; \
	done; \
	echo ""; \
	echo "============================================================"; \
	echo "  Results"; \
	echo "============================================================"; \
	echo "  PASS:$$PASS"; \
	echo "  FAIL:$$FAIL"; \
	echo "  SKIP:$$SKIP"; \
	echo "============================================================"; \
	[ -z "$$FAIL" ]

shell-src: ## Shell into source AAP container (SOURCE=2.4)
	podman exec -it aap-$(subst .,,$(SOURCE))-src /bin/bash

shell-tgt: ## Shell into target AAP container (TARGET=2.6)
	podman exec -it aap-$(subst .,,$(TARGET))-tgt /bin/bash
