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
# AAP 1.0–2.4: direct controller API
SOURCE__URL=https://source-aap.example.com/api/v2
# AAP 2.5+ source: Platform Gateway (uncomment and use instead of /api/v2)
# SOURCE__URL=https://source-aap.example.com/api/controller/v2
SOURCE__TOKEN=your_source_read_token

# Target AAP instance (read/write token; AAP 2.6+ via Platform Gateway)
TARGET__URL=https://target-aap.example.com/api/controller/v2
TARGET__TOKEN=your_target_write_token

# PostgreSQL state database
MIGRATION_STATE_DB_PATH=postgresql://user:password@localhost:5432/aap_migration
```

!!! note "Source URL by version"
    Set `SOURCE__URL` based on your source AAP version:

    | Source version | `SOURCE__URL` path |
    | --- | --- |
    | AAP 1.0–2.4 | `/api/v2` |
    | AAP 2.5+ | `/api/controller/v2` (Platform Gateway) |

!!! note "API token scope"
    The source token needs read-only scope (export/prep only read data). The
    target token needs read/write scope with admin-level access for import and
    cleanup. See [Configuration](configuration.md#api-token-permissions) for
    details and `curl` examples.

!!! warning "Platform Gateway URL"
    The target URL (AAP 2.6+) must use `/api/controller/v2` (Platform Gateway),
    not the direct controller `/api/v2` path. Source AAP 2.5+ also uses
    `/api/controller/v2`; only source versions 1.0–2.4 use `/api/v2`.

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
