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

Full docs live under [`docs/`](docs/) and are built with MkDocs Material.
Procedures and reference material are **not** duplicated in this README —
use the guides below as the source of truth.

| Topic | Guide |
| --- | --- |
| Install (local, container CLI, Web UI) | [Installation](docs/getting-started/installation.md) |
| First migration | [Quick Start](docs/getting-started/quickstart.md) |
| `.env`, tokens, `config.yaml` | [Configuration](docs/getting-started/configuration.md) |
| Phases, resource order, resume | [Migration Workflow](docs/user-guide/migration-workflow.md) |
| Commands | [CLI Reference](docs/user-guide/cli-reference.md) |
| Browser UI | [Web UI](docs/user-guide/web-ui.md) |
| Version paths | [Compatibility Matrix](docs/reference/compatibility-matrix.md) |
| Ephemeral AAP testing | [Testing](docs/developer-guide/testing.md) |

Browse the Markdown under [`docs/`](docs/) on GitHub, or preview the MkDocs
site locally (contributor workflow — see
[Contributing](docs/developer-guide/contributing.md)):

```bash
make docs-serve   # http://127.0.0.1:8001
# or: mkdocs serve  # http://127.0.0.1:8000
```

## Quick path

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge
make setup                  # local host: .venv, deps, seed .env
# Edit .env — see docs/getting-started/configuration.md
source .venv/bin/activate
aap-bridge config validate
aap-bridge                   # interactive TUI (recommended)
```

The TUI walks prep → export → transform → import in steps so you can pause
for credential secrets (Vault or manual re-entry — `$encrypted$` values cannot
be read from the source API) before import. A single `aap-bridge migrate` runs
the full pipeline unattended and is usually a poor first choice until secrets
are ready.

The quick path above is the local host install. For that path plus container
CLI and Web UI options, see
[Installation](docs/getting-started/installation.md).

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
