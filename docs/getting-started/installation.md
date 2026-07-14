# Installation

AAP Bridge supports two workflows:

| Mode | What you manage | Best for |
| --- | --- | --- |
| **Local host install** | Python environment + PostgreSQL | Default day-to-day development and direct host usage |
| **Container CLI** | Podman images and compose services | Isolated CLI workflow with PostgreSQL included |
| **Web UI** | Podman images, compose services, and a browser | Browser-based connection management and migration runs |

The containerized workflow is optional. The original local host setup remains fully supported.

## Prerequisites
- **Python 3.12** or higher
- **PostgreSQL** database (for state management)
- **uv** package manager (recommended) or pip
- Network access to source and target AAP instances
- **API tokens**: read-only scope for the source AAP (with permission to read
  all resources being migrated); read/write scope with admin-level access for
  the target AAP

### Software

| Package | Used by | Notes |
| --- | --- | --- |
| **make** | Both workflows | Convenience wrapper for setup, testing, and container commands |
| **uv** or **pip** | Local host install | `make setup` uses **uv** when installed, otherwise **stdlib venv + pip** |
| **podman-compose** | Container CLI | Provides `podman compose` for the bundled PostgreSQL + bridge stack |

### Hardware Requirements

| Migration Size | RAM | Notes |
| --- | --- | --- |
| < 10,000 hosts | 4GB | Minimal setup |
| 10,000 - 50,000 hosts | 8GB | Recommended |
| 50,000+ hosts | 16GB+ | Large-scale migrations |

## Local Host Install

Run AAP Bridge directly on the host with your own Python environment and PostgreSQL instance.

### Requirements

- **Python 3.12** (required; the pip fallback uses `python3.12` when present)
- **PostgreSQL** database for state management
- **uv** (recommended) or **pip** for installing Python dependencies
- Network access to source and target AAP instances

On systems where `python3` is newer than 3.12 (for example 3.13 or 3.14), install the
`python3.12` package before using the pip path. **uv** handles this automatically.

### Setup

`make setup` creates `.venv`, installs dependencies, installs the CLI in editable mode,
and seeds `.env`. It uses **uv** automatically when available; otherwise it falls back
to the standard library `venv` module and `pip`.

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Create .venv, install dependencies, install the CLI, and seed .env
make setup

# Force the pip-based path even when uv is installed
# make setup USE_UV=0

# Activate the environment for interactive CLI usage
source .venv/bin/activate
```

All other `make` targets (`test`, `lint`, `docs-serve`, etc.) run tools from
`.venv/bin` and do not require activation.

### Database Setup

Create a PostgreSQL database for migration state:

```bash
psql -c "CREATE DATABASE aap_migration;"
psql -c "CREATE USER aap_migration_user WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE aap_migration TO aap_migration_user;"

# For PostgreSQL 15+, grant schema permissions
psql -d aap_migration -c "GRANT ALL ON SCHEMA public TO aap_migration_user;"
```

### Configure `.env`

`make setup` creates `.env` from `.env.example` if one does not already exist.
The local and containerized workflows share the same `.env` file and `config/config.yaml`.
Edit `.env` and fill in your AAP details.

At minimum, set:

```bash
SOURCE__URL=https://source-aap.example.com/api/v2
SOURCE__TOKEN=your_source_token
TARGET__URL=https://target-aap.example.com/api/controller/v2
TARGET__TOKEN=your_target_token
MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:your_secure_password@localhost:5432/aap_migration
```

!!! note
    The tool automatically creates the necessary tables on first run.

## Container CLI

Run the CLI inside a container while using a bundled PostgreSQL service from `registry.redhat.io`.
This mode keeps the same host-side `.env` and config files, but you do not need to provision PostgreSQL yourself.

### Requirements

- **podman** with compose support (see [Software](#software) prerequisites)
- Access to `registry.redhat.io` to pull the Red Hat PostgreSQL image

### Setup

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Create .env if you do not already have one
make init-env

# Authenticate once so compose can pull the Red Hat PostgreSQL image
podman login registry.redhat.io

# Build the runtime and dev images
make build

# Start the db + bridge services
podman compose up -d db bridge

# Run unit tests inside the bridge container (optional)
make c-test

# Open a shell in the running bridge container
make shell
```

### Notes

- `compose.yml` uses `registry.redhat.io/rhel9/postgresql-15` for the bundled database service.
- `make up-dev` creates `./exports`, `./xformed`, `./reports`, `./logs`, and `./schemas` on the
  host and starts the db + bridge services.
- The bridge container bind-mounts those directories (and `./src`, `./tests/unit`) so migration
  artifacts and your working tree are visible on the host without rebuilding the image.
- The container workflow is intended for the CLI/TUI path; the browser workflow uses the same `.env` from `make init-env` with the dedicated engine and UI services described below.

## Web UI

Run the browser-based interface with a FastAPI engine and nginx-served frontend.
This workflow builds on the same local/container foundation as the CLI flow, but
adds API and UI services on top of the bundled PostgreSQL database.

### Requirements

- **podman** with compose support
- **make**
- Access to `registry.redhat.io` to pull the Red Hat PostgreSQL image

### Setup

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Create .env if you do not already have one
make init-env

# Authenticate once so compose can pull the Red Hat PostgreSQL image
podman login registry.redhat.io

# Build the engine and UI images
make build-all

# Start db + engine + ui
make up
```

### Verify

Open [http://localhost:8080](http://localhost:8080) in your browser.

### Notes

- `make up` uses the same self-preparing PostgreSQL container setup as the CLI workflow.
- The UI proxies `/api` and `/ws` traffic to the FastAPI engine running on port `8000`.
- For frontend-only development, run `aap-bridge serve --reload` in one terminal and `make web-dev` in another.

## Verify Installation

### Local host install

```bash
aap-bridge --version
aap-bridge --help
```

### Container CLI

`make c-test` runs a quick smoke check (no coverage report, no optional fixture-data
tests). From the host:

```bash
make c-test
```

Inside the container opened with `make shell`:

```bash
aap-bridge --version
aap-bridge --help
```

## Useful Commands

| Command | Description |
| --- | --- |
| `make setup` | Complete local host setup (auto-detects uv or pip) |
| `make setup USE_UV=0` | Local host setup using stdlib venv + pip |
| `make build` | Build the container images used by the CLI workflow |
| `make build-all` | Build the API and UI images for the browser workflow |
| `make up` | Start the PostgreSQL + engine + UI services |
| `make up-dev` | Start the PostgreSQL + bridge containers |
| `make shell` | Open a shell in the running bridge container |
| `make c-test` | Quick unit-test smoke check inside the bridge container |
| `make c-test-all` | Full unit test suite inside the bridge container |
| `make c-check` | Run lint, typecheck, and tests inside the bridge container |
| `make shell-engine` | Open a shell in the engine container |
| `make web-dev` | Start the Vite frontend dev server |
| `make logs` | Tail compose service logs |
| `make down` | Stop the db + bridge compose stack |
| `make down-all` | Stop compose stack and all running AAP test/build containers |

## Next Steps

- [Quick Start](quickstart.md) - Get up and running in 5 minutes
- [Configuration](configuration.md) - Configure your environment
- [Testing with Ephemeral AAP Instances](../developer-guide/testing.md) - Build golden
  images and run migration test pairs (podman + make; no local Python/AAP required)
