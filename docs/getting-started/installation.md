# Installation

AAP Bridge supports two workflows:

| Mode | What you manage | Best for |
| --- | --- | --- |
| **Local host install** | Python environment + PostgreSQL | Default day-to-day development and direct host usage |
| **Container CLI** | Podman images and compose services | Isolated CLI workflow with PostgreSQL included |
| **Web UI** | Podman images, compose services, and a browser | Browser-based connection management and migration runs |

The containerized workflow is optional. The original local host setup remains fully supported.

## Prerequisites

- **Python 3.12** or higher (local host install)
- **PostgreSQL** database for state management (local host install; bundled in
  container workflows)
- **uv** package manager (recommended) or pip (local host install)
- Network access to source and target AAP instances, and to the state database
- **API tokens**: read-only scope for the source AAP (with permission to read
  all resources being migrated); read/write scope with admin-level access for
  the target AAP. See [Configuration](configuration.md#api-token-permissions).
- **HashiCorp Vault** (optional but recommended): for migrating encrypted
  credentials securely
- **Instance groups**: any instance groups referenced by RBAC role assignments
  or assigned as capacity to organizations, inventories, or job templates on
  the source must already exist on the target with the same name. Instance
  group objects are not migrated; they are resolved by name on the target.

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

The tool requires a PostgreSQL database to track migration state. Create it
before the first run; tables are created automatically on first use.

If PostgreSQL is not already installed (RHEL / Fedora example):

```bash
sudo yum install postgresql-server
sudo postgresql-setup --initdb

# If you use Kerberos or need password auth over TCP, set the IPv4/IPv6
# local connection METHOD (for example scram-sha-256) in pg_hba.conf:
#   sudo vi /var/lib/pgsql/data/pg_hba.conf
#   host    all    all    127.0.0.1/32    scram-sha-256
#   host    all    all    ::1/128         scram-sha-256

sudo systemctl enable postgresql --now
```

Create the database and user (as the `postgres` OS user, or via `sudo -u postgres`):

```bash
psql -c "CREATE DATABASE aap_migration;"
# If you changed password encryption, set it before assigning the password:
# psql -c "SET password_encryption = 'scram-sha-256';"
psql -c "CREATE USER aap_migration_user WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE aap_migration TO aap_migration_user;"

# For PostgreSQL 15+, grant schema permissions
psql -d aap_migration -c "GRANT ALL ON SCHEMA public TO aap_migration_user;"
```

Test connectivity as a normal user:

```bash
psql -h localhost -U aap_migration_user -W aap_migration
```

### Configure `.env`

`make setup` creates `.env` from `.env.example` if one does not already exist.
The local and containerized workflows share the same `.env` file and
`config/config.yaml`. Edit `.env` and fill in your AAP details.

At minimum, set host-only URLs and versions (see
[Configuration](configuration.md)):

```bash
SOURCE__URL=https://source-aap.example.com
SOURCE__VERSION=2.4
SOURCE__TOKEN=your_source_read_token

TARGET__URL=https://target-aap.example.com
TARGET__VERSION=2.6
TARGET__TOKEN=your_target_write_token

MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:your_secure_password@localhost:5432/aap_migration
```

!!! note
    The tool automatically creates the necessary tables on first run.

## Container CLI

Run the CLI inside a container while using a bundled PostgreSQL service from `registry.redhat.io`.
This mode keeps the same host-side `.env` and config files, but you do not need to provision
PostgreSQL yourself.

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
- The container workflow is intended for the CLI/TUI path; the browser workflow
  uses the same `.env` from `make init-env` with the dedicated engine and UI
  services described below.

## Web UI

Run the browser-based interface with a FastAPI engine and nginx-served frontend.
This workflow builds on the same local/container foundation as the CLI flow, but
adds API and UI services on top of the bundled PostgreSQL database.

There are two distinct paths:

| Path | What you run | Best for |
| --- | --- | --- |
| **Container deployment** | `make build-all` then `make up` | Running the full UI at port `8080` |
| **Local frontend development** | `make web-install` / `make web-dev` plus `aap-bridge serve` | Hot-reload Vite UI at port `5173` |

For pages, connections, and API details, see the [Web UI](../user-guide/web-ui.md) guide.

### Requirements

- **podman** with compose support (container deployment)
- **make**
- Access to `registry.redhat.io` to pull the Red Hat PostgreSQL image (container deployment)
- **Node.js / npm** (local frontend development only; not required for `make build-all`)

### Container deployment

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

Open [http://localhost:8080](http://localhost:8080) in your browser.

- `make up` uses the same self-preparing PostgreSQL container setup as the CLI workflow.
- The UI proxies `/api` and `/ws` traffic to the FastAPI engine running on port `8000`.

### Local frontend development

For host-side API plus Vite hot-reload (not a substitute for `make build-all`):

```bash
# Terminal 1: Start the API server
make init-env   # Or reuse an existing .env from make setup
pip install -e '.[api]'
aap-bridge serve --reload

# Terminal 2: Start the Vite dev server
make web-install
make web-dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

Run `make web-install` once (or again after `web/package-lock.json` changes) before
`make web-dev`.

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
| `make build-all` | Build the API and UI container images for the browser workflow (`make up`) |
| `make up` | Start the PostgreSQL + engine + UI services |
| `make up-dev` | Start the PostgreSQL + bridge containers |
| `make shell` | Open a shell in the running bridge container |
| `make c-test` | Quick unit-test smoke check inside the bridge container |
| `make c-test-all` | Full unit test suite inside the bridge container |
| `make c-check` | Run lint, typecheck, and tests inside the bridge container |
| `make shell-engine` | Open a shell in the engine container |
| `make web-install` | Install frontend npm dependencies (`web/`; for local Vite, not `build-all`) |
| `make web-dev` | Start the Vite frontend dev server on port `5173` |
| `make logs` | Tail compose service logs |
| `make down` | Stop the db + bridge compose stack |
| `make down-all` | Stop compose stack and all running AAP test/build containers |

## Next Steps

- [Quick Start](quickstart.md) - Get up and running in 5 minutes
- [Configuration](configuration.md) - Configure your environment
- [Testing with Ephemeral AAP Instances](../developer-guide/testing.md) - Build golden
  images and run migration test pairs (podman + make; no local Python/AAP required)
