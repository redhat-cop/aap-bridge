# Quick Start

Get AAP Bridge running in 5 minutes.

## 1. Set Up Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your AAP credentials:

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

!!! note "Version-driven API routing"
    Set `SOURCE__VERSION` and `TARGET__VERSION` (e.g. `2.4`, `2.6`). The tool
    uses these to select `/api/v2` (2.4 and earlier) or `/api/gateway/v1` plus
    `/api/controller/v2` (2.5+). Host URLs should be `https://fqdn` only.

!!! note "API token scope"
    The source token needs read-only scope (export/prep only read data). The
    target token needs read/write scope with admin-level access for import and
    cleanup. See [Configuration](configuration.md#api-token-permissions) for
    details and `curl` examples.

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

## One-Command Migration

For a complete migration in one command:

```bash
aap-bridge migrate full
```

This runs all phases sequentially with progress tracking.

## Interactive Mode

Run without arguments for an interactive menu:

```bash
aap-bridge
```

## Next Steps

- [Configuration](configuration.md) - Fine-tune settings for your environment
- [CLI Reference](../user-guide/cli-reference.md) - Explore all available
  commands
- [Migration Workflow](../user-guide/migration-workflow.md) - Understand the
  full process
