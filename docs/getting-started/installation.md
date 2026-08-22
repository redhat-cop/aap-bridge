# Installation

AAP Bridge supports three workflows:

| Mode                   | What you manage                                | Best for                                               |
|:-----------------------|:-----------------------------------------------|:-------------------------------------------------------|
| **Local host install** | Python environment + PostgreSQL                | Default day-to-day development and direct host usage   |
| **Container CLI**      | Podman images and compose services             | Isolated CLI workflow with PostgreSQL included         |
| **Web UI**             | Podman images, compose services, and a browser | Browser-based connection management and migration runs |

The containerized workflow is optional. The original local host setup remains fully supported.

## Quick install (recommended)

One command installs AAP Bridge and walks you through configuration. Neither
path keeps a source checkout on your machine.

```bash
curl -LsSf https://raw.githubusercontent.com/redhat-cop/aap-bridge/main/scripts/install.sh | sh
```

It starts by asking how you want to run AAP Bridge:

```text
AAP Bridge - Setup

AAP Bridge migrates automation content between Ansible Automation
Platform instances. There are two ways to run it.

  1. Command line
     Installs the aap-bridge command on this machine

  2. Containers
     Installs and runs the CLI, API engine, Web UI, and PostgreSQL
     with Podman

  q. Quit

Choose [1]:
```

To skip the question, pass `--cli` or `--containers` (`... | sh -s -- --cli`),
or set `AAP_BRIDGE_MODE=cli` / `AAP_BRIDGE_MODE=container`.

### Command line

Checks for git and uv (installing uv if absent), clones into a temporary
directory under `/tmp`, installs the `aap-bridge` command into an isolated
environment, removes the clone, then runs `aap-bridge init`.

### Containers (CLI + Web UI)

Checks podman and compose, makes sure every container image it needs is
reachable, builds the CLI, API, and UI images from a temporary checkout,
removes it, runs `aap-bridge init` in a container, then starts the stack and
verifies that each service answers.

The images come from `registry.redhat.io`. If you are not logged in, the
installer offers to run `podman login registry.redhat.io` for you before it
builds anything - your credentials go to Podman, not to AAP Bridge. Declining
stops setup with nothing built.

Build output goes to `<workspace>/logs/install.log` rather than the screen. If
a build fails, the installer says which images were built, keeps them and your
workspace, and picks up from there when you run it again.

When it finishes, the Web UI is at [http://localhost:8080](http://localhost:8080)
and `aap-bridge` is on your PATH — the same command either installation gives
you, from any directory:

```bash
aap-bridge                # the CLI, interactively
aap-bridge doctor         # any CLI command, run in the container

aap-bridge status         # what is running
aap-bridge stop           # stop the services, keeping everything
aap-bridge start          # start them again
aap-bridge logs           # follow the logs
aap-bridge uninstall      # remove AAP Bridge, keeping your data
```

How AAP Bridge is deployed is a choice you make once, at install time, rather
than something to remember at every invocation. Underneath, the command is a
few lines that run the launcher in your workspace, which you can also call
directly as `./aap-bridge` from there. If something else already occupies
`aap-bridge` on your PATH, the installer leaves it alone and tells you to use
the workspace copy.

`stop` and `start` are for pausing AAP Bridge when you are not migrating: the
containers, the network, and the database keep their state, and `start` resumes
rather than rebuilds. Podman Compose is still underneath if you prefer it.

### Ports

The container stack publishes three ports on this machine, all configurable:

| Setting               | Default | Service    |
|:----------------------|--------:|:-----------|
| `AAP_BRIDGE_DB_PORT`  |   15432 | PostgreSQL |
| `AAP_BRIDGE_API_PORT` |    8000 | API engine |
| `AAP_BRIDGE_UI_PORT`  |    8080 | Web UI     |

The installer checks all three before starting anything. If one is taken it
offers the next free port and records your answer in the workspace `.env`:

```text
Checking ports

  ! Port 8080 is already in use  needed by the Web UI

  Port for the Web UI [8081]:
  ✔ Web UI will use port 8081
```

A service whose port is in use starts but never answers, so this is resolved
rather than reported. Pre-set any of them to skip the question:

```bash
AAP_BRIDGE_UI_PORT=8090 curl -LsSf https://raw.githubusercontent.com/redhat-cop/aap-bridge/main/scripts/install.sh | sh
```

Changing `AAP_BRIDGE_DB_PORT` by hand afterwards means changing the port in
`MIGRATION_STATE_DB_PATH` to match; the installer changes both.

A command-line installation publishes nothing of its own unless you use the
bundled database, which takes 15432 as well. Point `MIGRATION_STATE_DB_PATH` at
your own PostgreSQL and it needs no ports at all.

!!! tip "Review before running"
    The script is [`scripts/install.sh`](https://github.com/redhat-cop/aap-bridge/blob/main/scripts/install.sh).
    Download and read it first if piping to a shell is against your policy.

!!! note "Images are built locally"
    AAP Bridge does not yet publish container images to a registry, so the
    installer builds them. Once images are published this step becomes a pull.

### Running it again

An existing workspace is a normal thing for the installer to find - a
reinstall, an upgrade, a second run after a failure. It looks before it
installs anything, and asks:

```text
Checking workspace

  ✔ Existing AAP Bridge workspace found
  ✔ Configuration found
  ✔ AAP credentials found
  ✔ Migration data found

This workspace is already configured.

  1. Use existing configuration
     Keep your settings and migration data

  2. Reconfigure
     Update connection settings without deleting migration data

  3. Choose another workspace

  q. Quit

Choose [1]:
```

**Use existing configuration** is the default and the usual answer: it
installs, verifies that the database and both AAP instances answer, and stops.
**Reconfigure** walks the settings again with the current ones as defaults -
Enter keeps each, and an existing API token is never displayed, only kept.
Either way, exports, transformed data, reports, schemas, and logs are left
alone. **Choose another workspace** asks for a different path rather than
sending you back to the command you started with.

A workspace with only some of its configuration gets its own path: complete
the setup, or pick a different directory.

### The workspace

Either path shows what it will do and asks for confirmation before touching
anything. After installing, `aap-bridge init` asks for source and target AAP
URLs, versions, and API tokens, then whether to use the bundled PostgreSQL
container or your own connection string. (The container path skips that last
question: its stack already includes PostgreSQL.) It writes everything into
one directory, `$HOME/aap-migration` by default (you can enter any other
path at the prompt, or set `AAP_BRIDGE_WORKSPACE`):

```text
$HOME/aap-migration/
  .env                 # endpoints, tokens (0600), database URL
  config/config.yaml   # references .env; all other settings use defaults
  exports/ xformed/ reports/ logs/ schemas/ backups/
```

Run the CLI from that directory. It locates `.env` and `config/config.yaml` by
walking up from the working directory, so subdirectories work too. To use a
workspace from elsewhere, set `AAP_BRIDGE_ENV=/path/to/.env`.

Re-run `aap-bridge init --force` to reconfigure, or edit `.env` directly. Each
migration can have its own workspace directory.

### Uninstalling

```bash
aap-bridge uninstall
```

or, from anywhere:

```bash
curl -LsSf https://raw.githubusercontent.com/redhat-cop/aap-bridge/main/scripts/uninstall.sh | sh
```

It reports what it found, then offers two choices:

| Choice                             | Removed                                                      | Kept                                                           |
|:-----------------------------------|:-------------------------------------------------------------|:---------------------------------------------------------------|
| **Uninstall AAP Bridge**           | Containers, AAP Bridge images, the `aap-bridge` command      | Workspace, configuration, API tokens, migration data, database |
| **Remove AAP Bridge and all data** | All of the above, plus the workspace and the database volume | Nothing                                                        |

The first is the default, and it is safe: you can reinstall later and reuse the
same workspace. The second asks you to type `REMOVE` in full, because it
destroys the only copy of your API tokens and migration state.

The choices are tailored to how you installed: a command-line installation is
never offered the removal of container images it never had.

Run it again after uninstalling and it recognises that the runtime is gone but
your migration data is not, and offers to deal with that alone:

```text
AAP Bridge is not installed.

Migration data is still available at:
  $HOME/aap-migration

Choose what you want to do:

  1. Keep migration data
     You can reuse it if you reinstall AAP Bridge

  2. Remove all migration data
     Permanently delete configuration, API tokens,
     migration files, and database data

  q. Cancel
```

Once nothing is left at all, it simply says AAP Bridge is already uninstalled.

Neither removes the images AAP Bridge was *built from* — UBI, Node.js,
PostgreSQL — since other applications on the machine may use them. You are
never asked to delete anything by hand.

The lifecycle, end to end:

| Action        | Services running | Containers | AAP Bridge images | Workspace and data |
|:--------------|:-----------------|:-----------|:------------------|:-------------------|
| **install**   | yes              | yes        | yes               | yes                |
| **stop**      | no               | yes        | yes               | yes                |
| **uninstall** | no               | no         | no                | yes                |
| **remove**    | no               | no         | no                | no                 |

The rest of this page covers manual installation, which you need for
air-gapped environments, for contributing, or when you want control over each
step.

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

| Package            | Used by            | Notes                                                                    |
|:-------------------|:-------------------|:-------------------------------------------------------------------------|
| **make**           | All workflows      | Convenience wrapper for setup, testing, and container commands           |
| **uv** or **pip**  | Local host install | `make setup` uses **uv** when installed, otherwise **stdlib venv + pip** |
| **podman-compose** | Container CLI      | Provides `podman compose` for the bundled PostgreSQL + bridge stack      |

### Hardware Requirements

| Migration Size        | RAM   | Notes                  |
|:----------------------|:------|:-----------------------|
| < 10,000 hosts        | 4GB   | Minimal setup          |
| 10,000 - 50,000 hosts | 8GB   | Recommended            |
| 50,000+ hosts         | 16GB+ | Large-scale migrations |

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

!!! warning "Check the port `make setup` wrote"
    `make init-env` (run by `make setup`) seeds `MIGRATION_STATE_DB_PATH` with
    port **15432**, which is the bundled compose PostgreSQL service, not a
    host-installed server. If you followed [Database Setup](#database-setup)
    above and installed PostgreSQL yourself, change the port to **5432** as
    shown. If you would rather use the bundled database, leave the generated
    value alone and start just that service with `podman compose up -d db`.

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

# Start the db + bridge services (also creates the host artifact directories)
make up-dev

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
- The UI proxies `/api` and `/ws` traffic to the FastAPI engine. The port comes from
  `AAP_BRIDGE_API_PORT` in `.env` (default `8000`) and is shared by the engine
  container, the nginx proxy, and the Vite dev server.
- For frontend-only development, run `aap-bridge serve --reload` in one terminal
  and `make web-dev` in another.
- To build on a connected host and run without registry access, see
  [Disconnected Environment](../user-guide/disconnected-environment.md).

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

| Command               | Description                                                  |
|:----------------------|:-------------------------------------------------------------|
| `make setup`          | Complete local host setup (auto-detects uv or pip)           |
| `make setup USE_UV=0` | Local host setup using stdlib venv + pip                     |
| `make build`          | Build the container images used by the CLI workflow          |
| `make build-all`      | Build the API and UI images for the browser workflow         |
| `make up`             | Start the PostgreSQL + engine + UI services                  |
| `make up-dev`         | Start the PostgreSQL + bridge containers                     |
| `make shell`          | Open a shell in the running bridge container                 |
| `make c-test`         | Quick unit-test smoke check inside the bridge container      |
| `make c-test-all`     | Full unit test suite inside the bridge container             |
| `make c-check`        | Run lint, typecheck, and tests inside the bridge container   |
| `make shell-engine`   | Open a shell in the engine container                         |
| `make web-dev`        | Start the Vite frontend dev server                           |
| `make logs`           | Tail compose service logs                                    |
| `make down`           | Stop the db + bridge compose stack                           |
| `make down-all`       | Stop compose stack and all running AAP test/build containers |

## Next Steps

- [Quick Start](quickstart.md) - Get up and running in 5 minutes
- [Configuration](configuration.md) - Configure your environment
- [Disconnected Environment](../user-guide/disconnected-environment.md) - Build
  connected and run the Web UI without registry access
- [Testing with Ephemeral AAP Instances](../developer-guide/testing.md) - Build golden
  images and run migration test pairs (podman + make; no local Python/AAP required)
