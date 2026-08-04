# Quick Start

Get AAP Bridge running in a few minutes after installation.

!!! tip "Install first"
    Complete [Installation](installation.md) (local host, container CLI, or
    Web UI) before continuing. That guide covers PostgreSQL, `make setup` /
    compose, and seeding `.env`.

## 1. Configure Environment

Edit `.env` with your AAP credentials and database URL (created by
`make setup` or `make init-env`):

```bash
# Source AAP instance (read-only token)
SOURCE__URL=https://source-aap.example.com
SOURCE__VERSION=2.4
SOURCE__TOKEN=your_source_read_token

# Target AAP instance (read/write token)
TARGET__URL=https://target-aap.example.com
TARGET__VERSION=2.6
TARGET__TOKEN=your_target_write_token

# PostgreSQL state database
MIGRATION_STATE_DB_PATH=postgresql://user:password@localhost:5432/aap_migration
```

For version-driven API routing, token scopes, Vault, and full settings, see
[Configuration](configuration.md). For AWX sources, see
[AWX Migration](../reference/awx-migration.md).

## 2. Validate Configuration

```bash
aap-bridge config validate
```

This checks connectivity to both AAP instances and the database.

## 3. Run Preparation Phase

```bash
aap-bridge prep
```

This:

- Fetches schemas from both AAP instances
- Compares field differences
- Generates transformation rules

## 4. Export from Source

```bash
aap-bridge export
```

Exports all resources from the source AAP to the `exports/` directory.

## 5. Transform Data

```bash
aap-bridge transform
```

Applies schema transformations for the target AAP version.

## 6. Import to Target

```bash
aap-bridge import
```

Imports transformed data to the target AAP.

## 7. Validate Migration

```bash
aap-bridge validate
```

Compares source and target to verify migration success.

## Interactive Mode (recommended)

Run without arguments for the interactive menu:

```bash
aap-bridge
```

Use this for most migrations. The menu runs prep, export, transform, and
import in separate steps so you can pause after export/transform to load
credential secrets into Vault (or recreate them on the target) before import.
Encrypted fields appear as `$encrypted$` on the source API and cannot be
migrated without that step — see
[Compatibility Matrix](../reference/compatibility-matrix.md) and
[Configuration](configuration.md#optional-variables).

## Unattended full pipeline

When Vault (or manual secrets) is already in place and you want a single
unattended run:

```bash
aap-bridge migrate
```

This runs prep → export → transform → import sequentially. Prefer the TUI
until that secret path is ready.

## Next Steps

- [Configuration](configuration.md) - Fine-tune settings for your environment
- [CLI Reference](../user-guide/cli-reference.md) - Explore all available
  commands
- [Migration Workflow](../user-guide/migration-workflow.md) - Understand the
  full process
