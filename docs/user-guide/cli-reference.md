# CLI Reference

AAP Bridge provides a comprehensive CLI for all migration operations.

## Global Options

```bash
aap-bridge [OPTIONS] COMMAND [ARGS]

```

| Option | Description |
| --- | --- |
| `--config`, `-c` | Path to configuration file |
| `--log-level` | Console log level (DEBUG, INFO, WARNING, ERROR) |
| `--log-file` | Path to log file |
| `--version` | Show version and exit |
| `--help` | Show help message |

## Commands

### Interactive Mode

```bash
aap-bridge

```

Launches an interactive menu for guided operation.

---

### prep

Run the preparation phase.

```bash
aap-bridge prep [OPTIONS]

```

**What it does:**

- Fetches schemas from source and target AAP
- Compares field differences
- Generates transformation rules

**Options:**

| Option | Description |
| --- | --- |
| `--force` | Overwrite existing prep data |

---

### export

Export resources from source AAP.

```bash
aap-bridge export [OPTIONS] [RESOURCE_TYPES]

```

**Examples:**

```bash
# Export all resources
aap-bridge export

# Export specific resource types
aap-bridge export organizations inventories hosts

# Export with custom output directory
aap-bridge export --output ./my-exports/

# Export with file splitting
aap-bridge export --records-per-file 500

```

**Options:**

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output directory (default: ./exports) |
| `--records-per-file` | Records per split file (default: 1000) |
| `--force` | Overwrite existing exports |

---

### transform

Transform exported data for target AAP.

```bash
aap-bridge transform [OPTIONS] [RESOURCE_TYPES]

```

**Examples:**

```bash
# Transform all exported data
aap-bridge transform

# Transform specific types
aap-bridge transform inventories hosts

```

**Options:**

| Option | Description |
| --- | --- |
| `--input`, `-i` | Input directory (default: ./exports) |
| `--output`, `-o` | Output directory (default: ./transformed) |

---

### import

Import data to target AAP.

```bash
aap-bridge import [OPTIONS] [RESOURCE_TYPES]

```

**Examples:**

```bash
# Import all transformed data
aap-bridge import

# Import specific types
aap-bridge import organizations inventories

# Import with progress disabled (CI/CD)
aap-bridge import --disable-progress

```

**Options:**

| Option | Description |
| --- | --- |
| `--input`, `-i` | Input directory |
| `--disable-progress` | Disable live progress display |
| `--dry-run` | Simulate without making changes |

---

### cleanup

Remove migrated resources from target AAP.

```bash
aap-bridge cleanup [OPTIONS] [RESOURCE_TYPES]

```

**Examples:**

```bash
# Cleanup all migrated resources
aap-bridge cleanup

# Cleanup specific types
aap-bridge cleanup hosts inventories

# Dry run to see what would be deleted
aap-bridge cleanup --dry-run

```

**Options:**

| Option | Description |
| --- | --- |
| `--dry-run` | Show what would be deleted |
| `--force` | Skip confirmation prompt |
| `--skip-defaults` | Skip default/system resources |

---

### validate

Validate migration results.

```bash
aap-bridge validate [OPTIONS] [RESOURCE_TYPES]

```

**Examples:**

```bash
# Validate all resources
aap-bridge validate

# Validate with sampling
aap-bridge validate --sample-size 1000

```

**Options:**

| Option | Description |
| --- | --- |
| `--sample-size` | Number of resources to sample |
| `--detailed` | Show detailed comparison |

---

### migrate

Run migration operations.

```bash
aap-bridge migrate SUBCOMMAND [OPTIONS]

```

**Subcommands:**

```bash
# Full migration (prep + export + transform + import)
aap-bridge migrate full

# Resume from checkpoint
aap-bridge migrate resume

# Resume from specific checkpoint
aap-bridge migrate resume --checkpoint inventories_batch_50

```

---

### checkpoint

Manage checkpoints.

```bash
aap-bridge checkpoint SUBCOMMAND

```

**Subcommands:**

```bash
# List all checkpoints
aap-bridge checkpoint list

# Show checkpoint details
aap-bridge checkpoint show <name>

# Delete a checkpoint
aap-bridge checkpoint delete <name>

# Clean old checkpoints
aap-bridge checkpoint clean --older-than 7d

```

---

### state

Manage migration state.

```bash
aap-bridge state SUBCOMMAND

```

**Subcommands:**

```bash
# Show state summary
aap-bridge state summary

# Reset state for a resource type
aap-bridge state reset hosts

# Clear all state (use with caution!)
aap-bridge state clear --confirm

```

---

### serve

Start the web API server.

```bash
aap-bridge serve [OPTIONS]

```

**What it does:**

- Starts a FastAPI/uvicorn server exposing the migration engine via REST API
- Enables the web UI (when served via nginx or Vite dev server)
- Provides WebSocket endpoints for real-time log streaming

**Options:**

| Option | Description |
| --- | --- |
| `--host` | Bind address (default: 0.0.0.0) |
| `--port` | Bind port (default: 8000) |
| `--reload` | Enable auto-reload for development |

**Examples:**

```bash
# Start API server with defaults
aap-bridge serve

# Start on custom port
aap-bridge serve --port 9000

# Development mode with auto-reload
aap-bridge serve --reload

# Serve still uses `MIGRATION_STATE_DB_PATH` for its database location
MIGRATION_STATE_DB_PATH=sqlite:///aap_bridge.db aap-bridge serve

```

!!! note
    Requires the `api` extras: `pip install '.[api]'`

---

### report

Generate migration reports.

```bash
aap-bridge report SUBCOMMAND

```

**Subcommands:**

```bash
# Summary report
aap-bridge report summary

# Detailed report
aap-bridge report detailed --output report.html

```

---

## Output Modes

Control output verbosity:

```bash
# Default: Live progress with WARNING logs
aap-bridge migrate full

# Quiet: Errors only
aap-bridge migrate full --quiet

# CI/CD: No live display
aap-bridge migrate full --disable-progress

# Detailed: Extra statistics
aap-bridge migrate full --show-stats

# Combined: Quiet + no progress
aap-bridge migrate full --quiet --disable-progress

```

## Environment Variables

Override options via environment:

```bash
export AAP_BRIDGE__LOGGING__CONSOLE_LEVEL=DEBUG
export AAP_BRIDGE__LOGGING__DISABLE_PROGRESS=true
aap-bridge migrate full

```
