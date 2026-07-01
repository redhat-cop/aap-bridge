# Configuration

AAP Bridge uses a combination of environment variables and YAML configuration
files.

## Environment Variables

Create a `.env` file from the example:

```bash
cp .env.example .env

```

### Required Variables

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

### API routing (`SOURCE__VERSION` / `TARGET__VERSION`)

`SOURCE__VERSION` and `TARGET__VERSION` are **required**. They select which API
paths the tool uses — older AAP releases do not expose a reliable product
version in API responses.

`SOURCE__URL` and `TARGET__URL` should be the AAP host only (`https://fqdn`):

| Configured version | API topology | Endpoints used |
|--------------------|--------------|----------------|
| 2.4 and earlier | Legacy controller | `/api/v2/` for all resources |
| 2.5+ | Platform gateway | `/api/gateway/v1/` for orgs, users, teams, RBAC, etc. |
| 2.5+ | Platform gateway | `/api/controller/v2/` for projects, inventories, jobs, etc. |

Legacy paths such as `/api/v2` or `/api/controller/v2` in a configured URL are
stripped with a log message. EDA and Galaxy APIs are not used by AAP Bridge.

### API Token Permissions

| Instance | Token scope | Why |
| --- | --- | --- |
| Source | Read-only | Export and prep only read data from the source AAP |
| Target | Read/write | Import, cleanup, and validation create and modify resources on the target |

The source token user must still have permission to read all resources being
migrated. The target token user needs admin-level access.

To create tokens via the API (avoid putting passwords in shell history):

```bash
# Source — read-only scope
# AAP 2.4 and earlier
curl -k -X POST -u "<username>:<password>" \
  -H "Content-Type: application/json" \
  -d '{"description": "AAP Bridge Source Token", "scope": "read"}' \
  https://<source_aap_base_url>/api/v2/tokens/ | jq -r '.token'

# AAP 2.5+ source (Platform Gateway)
curl -k -X POST -u "<username>:<password>" \
  -H "Content-Type: application/json" \
  -d '{"description": "AAP Bridge Source Token", "scope": "read"}' \
  https://<source_aap_base_url>/api/gateway/v1/tokens/ | jq -r '.token'

# Target (AAP 2.6 or 2.7) — read/write scope via Platform Gateway
curl -k -X POST -u "<username>:<password>" \
  -H "Content-Type: application/json" \
  -d '{"description": "AAP Bridge Target Token", "scope": "write"}' \
  https://<target_aap_base_url>/api/gateway/v1/tokens/ | jq -r '.token'
```

The Platform Gateway token API (`/api/gateway/v1/tokens/`) was introduced in AAP 2.5.
Use `/api/v2/tokens/` for AAP 2.4 and earlier.

### Optional Variables

```bash
# HashiCorp Vault (for credential migration)
VAULT__URL=https://vault.example.com
VAULT__ROLE_ID=your_role_id
VAULT__SECRET_ID=your_secret_id

# Logging overrides
AAP_BRIDGE__LOGGING__CONSOLE_LEVEL=WARNING
AAP_BRIDGE__LOGGING__DISABLE_PROGRESS=false

```

## Configuration File

The main configuration file is `config/config.yaml`:

### Path Configuration

```yaml
paths:
  state_db: ${MIGRATION_STATE_DB_PATH}
  export_dir: ./exports
  transform_dir: ./transformed
  log_dir: ./logs
  checkpoint_dir: ./checkpoints

```

### Performance Tuning

```yaml
performance:
  max_concurrent: 20           # Concurrent API requests
  batch_sizes:
    organizations: 100
    inventories: 200           # Maximum API page size for optimal performance
    hosts: 200                 # Maximum API page size (required for bulk operations)
    credentials: 50
  rate_limit: 25               # Requests per second

  # Inventory source sync (runs after import before constructed/smart inventories)
  inventory_source_update_job_timeout_seconds: 3600
  inventory_source_update_poll_interval_seconds: 3
  inventory_source_sync_max_concurrent: 5
  inventory_source_sync_fail_on_job_failure: false  # Set true to abort on sync failure

  # Project sync
  project_sync_timeout: 600
  project_sync_poll_interval: 10
  project_sync_max_retries: 2
  project_sync_fail_on_sync_failure: true

```

### Export Settings

```yaml
export:
  # Skip hosts managed by inventory sources (recreated by sync on target)
  skip_dynamic_hosts: true
  skip_smart_inventories: false
  skip_pending_deletion_inventories: true
  skip_hosts_with_inventory_sources: false

  # Installer-created execution environments – excluded by default.
  # Set to [] to migrate all EEs.
  skip_execution_environment_names:
    - Control Plane Execution Environment
    - Default execution environment
    - Hub Default execution environment
    - Hub Minimal execution environment
    - Minimal execution environment

  # Installer-created credentials – excluded by default.
  # The AAP installer recreates these automatically in the target environment.
  # Set to [] to migrate all credentials.
  skip_credential_names:
    - Ansible Galaxy
    - Default Execution Environment Registry Credential

  records_per_file: 1000  # Max records per split file

```

### Cleanup Settings

Cleanup-related settings live under the `performance:` section:

```yaml
performance:
  cleanup_max_concurrent: 50        # Maximum concurrent deletions
  cleanup_job_cancel_concurrency: 10  # Maximum concurrent job cancellations (≤25 to prevent gateway overload)
  cleanup_page_fetch_concurrency: 10  # Maximum concurrent page fetches during resource discovery
  cleanup_job_finish_timeout: 300   # Seconds to wait for cancelled jobs to finish
  cleanup_job_poll_interval: 5      # Seconds between job status checks
  host_cleanup_batch_size: 200      # Hosts per batch during cleanup (max 500 - AAP limit)

```

### Logging Configuration

```yaml
logging:
  level: WARNING               # Console output level
  file_level: DEBUG            # File log level
  file: logs/migration.log     # Log file path
  format: json                 # Log format (json or console)

```

## Resource Mappings

The `config/mappings.yaml` file defines field mappings between AAP versions:

```yaml
credential_types:
  source_to_target:
    "Amazon Web Services": "Amazon Web Services"
    "VMware vCenter": "VMware vCenter"

```

## Ignored Endpoints

The `config/ignored_endpoints.yaml` file lists endpoints to skip:

```yaml
ignored_endpoints:
  global:
    - ping
    - config
    - dashboard
  source: []
  target: []

```

## Validating Configuration

Check your configuration:

```bash
# Validate all settings
aap-bridge config validate

# Show current configuration
aap-bridge config show

```

## Environment-Specific Settings

### CI/CD Pipelines

```bash
export AAP_BRIDGE__LOGGING__DISABLE_PROGRESS=true
export AAP_BRIDGE__LOGGING__CONSOLE_LEVEL=INFO
aap-bridge migrate full

```

### Large Migrations

Increase batch sizes and concurrency:

```yaml
performance:
  max_concurrent: 20
  batch_sizes:
    hosts: 200
    inventories: 200
  rate_limit: 25

```

### Limited Network Bandwidth

Reduce concurrent requests:

```yaml
performance:
  max_concurrent: 5
  rate_limit: 20

```
