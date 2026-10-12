# AAP Bridge

Production-grade Python tool for migrating Ansible Automation Platform (AAP)
installations between versions, including large-scale environments
(e.g. 80,000+ hosts).

Migrate from AAP 1.0–2.7 (or upstream AWX at an equivalent release level) to a
**same-or-newer** target (2.6 or 2.7). Downgrade paths are not
supported. See the
[compatibility matrix](docs/reference/compatibility-matrix.md) and
[AWX migration](docs/reference/awx-migration.md) notes.

## Features

- Bulk API operations, checkpoint/resume, and idempotent imports
- Local host, optional containerized CLI, and optional Web UI workflows
- PostgreSQL-backed migration state
- Broad resource coverage (orgs, credentials, inventories, hosts, projects,
  job/workflow templates, schedules, classic and gateway RBAC, and more)
- Rich progress display with normal, quiet, CI/CD, and detailed output modes

## Documentation

Published docs: [https://redhat-cop.github.io/aap-bridge/](https://redhat-cop.github.io/aap-bridge/)

Full docs live under [`docs/`](docs/) and are built with MkDocs Material.
This README carries only the shortest working path for each workflow; detailed
procedures and reference material live in the guides below, which are the
source of truth.

| Topic                                  | Guide                                                          |
|:---------------------------------------|:---------------------------------------------------------------|
| Install (local, container CLI, Web UI) | [Installation](docs/getting-started/installation.md)           |
| First migration                        | [Quick Start](docs/getting-started/quickstart.md)              |
| `.env`, tokens, `config.yaml`          | [Configuration](docs/getting-started/configuration.md)         |
| Phases, resource order, resume         | [Migration Workflow](docs/user-guide/migration-workflow.md)    |
| Commands                               | [CLI Reference](docs/user-guide/cli-reference.md)              |
| Browser UI                             | [Web UI](docs/user-guide/web-ui.md)                            |
| Version paths                          | [Compatibility Matrix](docs/reference/compatibility-matrix.md) |
| Ephemeral AAP testing                  | [Testing](docs/developer-guide/testing.md)                     |

Browse the Markdown under [`docs/`](docs/) on GitHub, or preview the MkDocs
site locally (contributor workflow — see
[Contributing](docs/developer-guide/contributing.md)):

```bash
make docs-serve   # http://127.0.0.1:8001
# or: mkdocs serve  # http://127.0.0.1:8000
```

## Install

One command. It checks prerequisites, installs what is missing, and walks you
through configuring the source and target AAP instances.

```bash
curl -LsSf https://raw.githubusercontent.com/redhat-cop/aap-bridge/main/scripts/install.sh | sh
```

It asks how you want to run AAP Bridge:

| Choice           | What it does                                                                |
|:-----------------|:----------------------------------------------------------------------------|
| **Command line** | Installs the `aap-bridge` command in an isolated environment with uv        |
| **Containers**   | Builds the CLI, API engine, and Web UI images and runs them with PostgreSQL |

Pick without being asked with `sh -s -- --cli` / `--containers`, or
`AAP_BRIDGE_MODE=cli` / `container`.

The container path resolves `registry.redhat.io` access and checks every image
it needs before building anything, then starts the stack and verifies it. The
Web UI ends up at <http://localhost:8080>.

Prefer to read before running? The script lives in
[`scripts/install.sh`](scripts/install.sh). Download, review, then execute.

Neither path keeps a source checkout: both build in a temporary directory and
remove it.

### What you get

Both paths run `aap-bridge init`, which asks for your source and target AAP
URLs, versions, and API tokens, then how you want to run PostgreSQL — the
bundled container, or your own connection string. (The container path skips
that question: PostgreSQL is part of its stack.) It writes a self-contained
workspace:

```text
$HOME/aap-migration/
  .env                 # endpoints, tokens (0600), database URL
  config/config.yaml   # references .env; everything else uses defaults
  exports/ xformed/ reports/ logs/ schemas/ backups/
```

The installer shows what it will do and waits before touching anything. The
default workspace is `$HOME/aap-migration`; press Enter to accept it, type any
other path (`~/...`, `$HOME/...`, relative, or absolute), or type `q` to quit.
When setup finishes it drops you into a shell already in the workspace.

The installer does the rest itself: it starts the database, verifies that both
AAP instances and the database are reachable, and opens the migration. Nothing
is left for you to run by hand.

If anything looks wrong, later or during setup:

```bash
aap-bridge doctor        # diagnose
aap-bridge doctor --fix  # repair safe, local problems
```

`doctor` checks the system, workspace, database, and both AAP connections in
one place. `--fix` starts a stopped database, recreates missing directories,
and tightens file permissions; it never changes AAP URLs, tokens, or anything
remote.

To reconfigure later, edit `.env` or re-run `aap-bridge init --force`. A second
migration is just a second directory with its own `aap-bridge init`.

### Web UI

The container path starts this for you — open
[http://localhost:8080](http://localhost:8080) and manage connections in the
browser. Either installation gives you the same command, from anywhere:

```bash
aap-bridge status              # what is running
aap-bridge stop                # stop the services, keeping everything
aap-bridge start               # start them again
aap-bridge uninstall           # remove AAP Bridge, keeping your data
```

See [Web UI](docs/user-guide/web-ui.md) and
[Installation](docs/getting-started/installation.md#uninstalling).

### Developer setup

Contributing, or want the full source tree, test suite, and pre-commit hooks?
That is a different path — see
[Contributing](docs/developer-guide/contributing.md):

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge
make setup
```

Manual and air-gapped installation, hardware sizing, and API token scopes are
in [Installation](docs/getting-started/installation.md).

## About the phases

The TUI and Web UI both walk prep → export → transform → import in steps so you
can pause for credential secrets (Vault or manual re-entry — `$encrypted$`
values cannot be read from the source API) before import. A single
`aap-bridge migrate` runs the full pipeline unattended and is usually a poor
first choice until secrets are ready.

## Project status

Active development (0.1.0+). See [CHANGELOG.md](CHANGELOG.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/developer-guide/contributing.md](docs/developer-guide/contributing.md).

## License

[GNU General Public License v3.0](LICENSE)

## Security

Report vulnerabilities per [SECURITY.md](SECURITY.md).

## Support

- **Issues**: [GitHub Issues](https://github.com/redhat-cop/aap-bridge/issues)
- **Security**: [SECURITY.md](SECURITY.md)
