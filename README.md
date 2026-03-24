# AAP Bridge

A production-grade Python tool for migrating Ansible Automation Platform (AAP)
installations from one version to another, designed to handle large-scale
migrations

## Supported Versions

**Source AAP:**
- AAP 2.3, 2.4, 2.5 (RPM-based or containerized)

**Target AAP:**
- AAP 2.5, 2.6 (containerized recommended)

**Common Migration Path:**
- AAP 2.4 (RPM-based) → AAP 2.6 (containerized) ✅ Tested

The tool automatically detects AAP versions and validates compatibility before migration.

## Features

- **🔐 Credential-First Migration**: Ensures credentials are checked, compared, and migrated BEFORE all other resources
- **Bulk Operations**: Leverages AAP bulk APIs for high-performance migrations
- **State Management**: SQLite or PostgreSQL-backed state tracking with checkpoint/resume capability
- **Idempotency**: Safely resume interrupted migrations without creating duplicates
- **Automatic Credential Comparison**: Pre-flight checks to identify missing credentials with detailed reports
- **Dynamic Inventories**: Full support for migrating dynamic inventories including:
  - Inventory containers
  - Inventory sources (SCM configuration)
  - Inventory source schedules
  - All hosts from dynamic inventories
- **Professional Progress Display**: Rich-based live progress display with
  real-time metrics (rate, success/fail counts, timing)
- **Flexible Output Modes**: Normal, quiet, CI/CD, and detailed modes for
  different environments
- **Comprehensive Logging**: Structured logging with separate console (WARNING)
  and file (DEBUG) levels
- **Split-File Export/Import**: Automatic file splitting for large datasets with
  metadata tracking
- **CLI Interface**: Intuitive Click-based CLI with extensive options and
  environment variable support
- **RBAC Migration**: Separate script for migrating role-based access control assignments

## 🔐 Credential-First Migration Workflow

AAP Bridge implements a **credential-first migration approach** that ensures credentials are properly handled before any dependent resources are migrated. This prevents common migration failures and provides complete visibility into credential status.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CREDENTIAL-FIRST WORKFLOW                        │
└─────────────────────────────────────────────────────────────────────┘

Step 1: PRE-MIGRATION CREDENTIAL CHECK (Automatic)
   ┌──────────────────────────────────────────────┐
   │  • Fetch all credentials from source AAP     │
   │  • Fetch all credentials from target AAP     │
   │  • Compare by (name, type, organization)     │
   │  • Generate detailed diff report             │
   │  • Display summary in console                │
   └──────────────────────────────────────────────┘
                       ↓
Step 2: MIGRATION PHASE 1 - Organizations
   ┌──────────────────────────────────────────────┐
   │  • Migrate organizations (credential deps)   │
   │  • Store ID mappings                         │
   └──────────────────────────────────────────────┘
                       ↓
Step 3: MIGRATION PHASE 2 - Credentials (CRITICAL)
   ┌──────────────────────────────────────────────┐
   │  • Migrate credential types                  │
   │  • Migrate ALL credentials                   │
   │  • 100% completion before proceeding         │
   │  • Store ID mappings                         │
   └──────────────────────────────────────────────┘
                       ↓
Step 4: MIGRATION PHASES 3+ - All Other Resources
   ┌──────────────────────────────────────────────┐
   │  • Credential Input Sources                  │
   │  • Users, Teams, Labels                      │
   │  • Execution Environments                    │
   │  • Projects (can use credentials)            │
   │  • Inventories (can use credentials)         │
   │  • Job Templates (require credentials)       │
   │  • Workflows                                 │
   └──────────────────────────────────────────────┘
```

### Key Benefits

✅ **No Dependency Failures**: Credentials exist before resources that need them
✅ **Full Visibility**: Know exactly what credentials are missing before migration
✅ **Detailed Reports**: Generated automatically with credential details
✅ **Structure Migration**: Credential definitions migrated (secrets require manual update)
✅ **Idempotent**: Safe to re-run, already-migrated credentials are skipped

### Important Limitation

⚠️ **Secret values cannot be migrated** - AAP API returns `$encrypted$` for all secret fields. After migration, you must manually update passwords, tokens, and keys in the target AAP via the Web UI or API.

### Quick Start with Credential-First

```bash
# Option 1: Check credentials before full migration
aap-bridge credentials compare
# Review: ./reports/credential-comparison.md

# Option 2: Migrate only credentials
aap-bridge credentials migrate

# Option 3: Full migration (credentials checked automatically)
aap-bridge migrate full
```

**📚 Documentation:**
- **[CREDENTIAL-FIRST-WORKFLOW.md](docs/workflows/CREDENTIAL-FIRST-WORKFLOW.md)** - Complete user guide
- **[MIGRATION-WORKFLOW-DIAGRAM.md](docs/workflows/MIGRATION-WORKFLOW-DIAGRAM.md)** - Visual diagrams and flowcharts
- **[QUICK-START.md](QUICK-START.md)** - Quick reference guide

## Architecture

The tool is organized into several key components:

- **Client Layer**: HTTP clients for source AAP, target AAP, and HashiCorp Vault
  with retry logic and rate limiting
- **Migration Layer**: ETL pipeline with exporters, transformers, and importers
  for all AAP resource types
- **Credential Comparator**: Dedicated module for credential diff and validation
- **State Management**: Database-backed progress tracking, checkpoint creation,
  and ID mapping
- **CLI**: User-friendly command-line interface for all operations

## Quick Start

### Prerequisites

- **Python 3.12** or higher
- **Hardware**: Minimum 8GB RAM recommended for large migrations
- **Network**: Access to Source AAP and Target AAP
- **Credentials**: Admin access to both Source and Target AAP instances
- **Database**: SQLite (built-in, no setup) or PostgreSQL (optional, for 100k+ resources)
- **HashiCorp Vault** (Optional but recommended): For migrating encrypted
  credentials securely

### Installation

```bash
# Clone the repository
git clone https://github.com/antonysallas/aap-bridge.git
cd aap-bridge

# Create virtual environment
uv venv --seed --python 3.12
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

2. **Install dependencies and editable package:**
This command will create/update your virtual environment, install all dependencies (including development dependencies), and install the `aap-bridge` package in editable mode.

uv sync
```

### Configuration

The project includes configuration files with recommended default values. You need to set up your environment variables for AAP credentials and the database.

#### 1. Database Setup

The tool uses a database to track migration state (ID mappings, checkpoints, progress). **SQLite is the default** - no setup required!

**Database Comparison:**

| Feature | SQLite (Default) | PostgreSQL (Optional) |
|---------|------------------|----------------------|
| **Setup** | ✅ Zero configuration | Requires PostgreSQL server |
| **Capacity** | Large migrations | Very large migrations |
| **Location** | Local file | Local or remote |
| **Backup** | Copy single file | Database dump |
| **Best For** | Most migrations | Enterprise scale |

##### Option A: SQLite (Default - Zero Configuration) ⭐ Recommended

SQLite is a file-based database that requires no server setup. Perfect for most migrations.

- ✅ **No installation required** - Built into Python
- ✅ **Automatic setup** - Database file created on first run
- ✅ **Handles large migrations** - Supports substantial workloads
- ✅ **Easy backup** - Just copy the `migration_state.db` file
- ✅ **Production-ready** - Successfully used in AAP migrations

**No configuration needed!** The default `.env` uses SQLite.

##### Option B: PostgreSQL (Optional - For Enterprise Scale)

Consider PostgreSQL only if you need:
- Very large migrations
- Distributed/remote state access
- Cloud RDS integration

**Important:** This is a separate PostgreSQL instance for migration state tracking, NOT AAP's internal database.

```bash
# Create PostgreSQL database and user
psql -c "CREATE DATABASE aap_migration;"
psql -c "CREATE USER aap_migration_user WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE aap_migration TO aap_migration_user;"
# Ensure the user owns the schema/tables (Postgres 15+)
psql -d aap_migration -c "GRANT ALL ON SCHEMA public TO aap_migration_user;"
```

Then update `.env`:
```bash
MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:password@localhost:5432/aap_migration
```

#### 2. Environment Setup

Copy the example environment file and configure your credentials:

```bash

cp .env.example .env

```

Edit `.env` with your AAP instance details and database connection string.

**Critical AAP 2.6 Note:** The Target URL must point to the **Platform Gateway** (`/api/controller/v2`), not the direct controller API.

```bash

# Source AAP instance
SOURCE__URL=https://source-aap.example.com/api/v2
SOURCE__TOKEN=your_source_token

# Target AAP instance (Platform Gateway)
TARGET__URL=https://target-aap.example.com/api/controller/v2
TARGET__TOKEN=your_target_token

# State database (SQLite by default - no setup required!)
MIGRATION_STATE_DB_PATH=sqlite:///./migration_state.db

# For PostgreSQL (enterprise scale only):
# MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:password@localhost:5432/aap_migration

# HashiCorp Vault (Optional)
# If configured, the tool can inject credentials. If skipped, credentials must
be manually recreated.
VAULT__URL=https://vault.example.com
VAULT__ROLE_ID=xxxxx
VAULT__SECRET_ID=xxxxx

```

#### 3. Application Configuration

Review and adjust `config/config.yaml` for your environment:

- **Performance settings**: Adjust batch sizes and concurrency based on your AAP instance capacity
- **Logging**: Configure log levels and file paths
- **Migration phases**: Enable/disable specific resource types

1. Update `config/mappings.yaml` if you need to rename resources during migration (e.g., credential types with different names between AAP versions).

### Usage

#### Recommended Workflow

The recommended approach is to check credentials first, then run the full migration:

```bash
# Step 1: Check what credentials are missing
aap-bridge credentials compare

# Step 2: Review the credential comparison report
cat ./reports/credential-comparison.md

# Step 3: Run full migration (credentials will be migrated first automatically)
aap-bridge migrate full

# Step 4: Validate migration
aap-bridge validate all --sample-size 4000

# Step 5: Migrate RBAC role assignments (after main migration)
python rbac_migration.py
```

#### Credential Management Commands

New in v0.2.0 - Dedicated credential management:

```bash
# Compare credentials between source and target
aap-bridge credentials compare [--output ./reports/creds.md]

# Migrate only credentials (and their dependencies)
aap-bridge credentials migrate [--dry-run] [--report-dir ./reports]

# Generate credential status report
aap-bridge credentials report [--output ./reports/status.md]
```

**What happens during credential migration:**
1. ✅ Compares credentials to find missing ones
2. ✅ Migrates organizations (dependency)
3. ✅ Migrates credential types (dependency)
4. ✅ Migrates credentials
5. ✅ Generates detailed migration report

#### Basic Migration Commands

```bash
# Menu-based CLI (interactive)
aap-bridge

# Full migration with automatic credential-first workflow
aap-bridge migrate full --config config/config.yaml

# Export from source AAP only
aap-bridge export all --output exports/

# Import to target AAP only
aap-bridge import inventories --input exports/inventories.json

# Validate migration
aap-bridge validate all --sample-size 4000

# View migration report
aap-bridge report summary

# Migrate RBAC role assignments (separate script)
python rbac_migration.py
```

**Note:** RBAC role assignments are migrated using a separate Python script (`rbac_migration.py`) after the main migration completes. This ensures all resources exist before assigning roles. See [USER-GUIDE.md](USER-GUIDE.md) for detailed RBAC migration instructions.

#### Output Control

The tool provides flexible output modes for different environments:

```bash

# Default: Live progress display with clean console output
aap-bridge migrate full --config config/config.yaml

# Quiet mode: Errors only (for scripting)
aap-bridge migrate full --config config/config.yaml --quiet

# Disable progress: For CI/CD environments
aap-bridge migrate full --config config/config.yaml --disable-progress

# Detailed stats: Show additional metrics
aap-bridge migrate full --config config/config.yaml --show-stats

# Combination: Quiet + no progress for automation
aap-bridge migrate full --config config/config.yaml --quiet --disable-progress

```

**Output Modes:**

- **Normal** (default): Live progress display with real-time metrics, WARNING-level console logs
- **Quiet** (`--quiet`): Minimal output, errors only
- **CI/CD** (`--disable-progress`): No live display, structured logs suitable for CI pipelines
- **Detailed** (`--show-stats`): Additional statistics and timing information

**Environment Variables:**

```bash

# Configure via environment
export AAP_BRIDGE__LOGGING__CONSOLE_LEVEL=WARNING
export AAP_BRIDGE__LOGGING__DISABLE_PROGRESS=true
aap-bridge migrate full --config config/config.yaml

```

#### Split-File Export/Import

For large datasets, the tool automatically splits exports into multiple files:

```bash

# Export with custom split size (default: 1000 records/file)
aap-bridge export --output exports/ --records-per-file 500

# Import handles multiple files automatically
aap-bridge import --input exports/

```

**Export Structure:**

```text

exports/
├── metadata.json           # Export metadata
├── organizations/
│   └── organizations_0001.json
├── inventories/
│   ├── inventories_0001.json  # 1000 records
│   ├── inventories_0002.json  # 1000 records
│   └── inventories_0003.json  # Remaining records
└── hosts/
    ├── hosts_0001.json
    └── hosts_0002.json

```

## Performance Targets (TBD)

- **Migration Rate**:
- **API Request Rate**:
- **Memory Usage**:
- **Total Time**:

## Key Design Principles

### Bulk Operations

The tool uses AAP's bulk operations API to dramatically improve performance:

- Hosts: 200 per request (API maximum)
- Inventories: 100 per batch
- Credentials: 50 per batch

### Checkpoint Recovery

All migrations are checkpoint-based, allowing safe resumption:

```bash

# Resume from last checkpoint
aap-bridge migrate resume

# Resume from specific checkpoint
aap-bridge migrate resume --checkpoint inventories_batch_50

```

### Idempotency

The tool tracks all migrated resources in a state database, ensuring that running the migration multiple times is safe and won't create duplicates.

## Migration Order

The tool migrates resources in the correct dependency order:

1. **Phase 1**: Organizations, Labels, Users, Teams
2. **Phase 2**: Credential Types, Credentials
3. **Phase 3**: Projects (with sync), Execution Environments
4. **Phase 4**: Inventories (bulk operations, including dynamic inventories)
5. **Phase 5**: Inventory Sources (SCM configuration for dynamic inventories)
6. **Phase 6**: Hosts (bulk operations, 200/batch - AAP maximum)
7. **Phase 7**: Schedules (including inventory source schedules)
8. **Phase 8**: Job Templates, Workflows
9. **Phase 9**: RBAC role assignments (via separate `rbac_migration.py` script)

## Known Issues and Limitations

### Critical Limitations

1. **Encrypted Credentials**: AAP API returns `$encrypted$` for secret fields. **Solution:**
   - Use the credential migration tool (see `docs/guides/credential-migration.md`)
   - Automated playbook generation from source AAP
   - Interactive secret filling workflow
   - Structure migration with proper encryption handling
   - Alternative: HashiCorp Vault integration or manual recreation

2. **Duplicate Hostnames**: AAP 2.6 enforces stricter hostname uniqueness validation. If source AAP has duplicate hostnames within the same inventory, those hosts will fail to migrate. Solution: Rename duplicates in source before migration.

3. **API Timeouts**: Large operations may timeout with default settings. If you encounter timeouts:
   - Increase timeout values in `.env` (e.g., `SOURCE__TIMEOUT=300`, `TARGET__TIMEOUT=300`)
   - Reduce concurrency in `config/config.yaml` (e.g., `max_concurrent: 5`, `rate_limit: 10`)

4. **Platform Gateway (AAP 2.6+)**: Target URL must use Platform Gateway path `/api/controller/v2` (not `/api/v2`)

5. **Manual RBAC Migration**: Role-based access control assignments are migrated via separate `rbac_migration.py` script (not included in main migration workflow)

### Dynamic Inventories

Dynamic inventories are fully supported with the following configuration in `config/config.yaml`:

```yaml
export:
  skip_dynamic_hosts: false
  skip_smart_inventories: false
  skip_hosts_with_inventory_sources: false
```

**What Gets Migrated:**
- ✅ Inventory containers (dynamic and static)
- ✅ Inventory sources (SCM configuration)
- ✅ Inventory source schedules
- ✅ All hosts (including hosts from dynamic inventories)

**Post-Migration:** You can manually trigger inventory source syncs or wait for scheduled syncs to update hosts from external sources.

### Credential Metadata Migration

A specialized tool migrates credential structure and metadata without database load:

**The Problem:**
- Source and Target AAP use different encryption keys (SECRET_KEY)
- Direct database copy won't work (target can't decrypt)
- Secret values return as `$encrypted$` from the API
- Manual recreation is time-consuming and error-prone

**The Solution:**

```bash
# Step 1: Export credential metadata (5 mins - API only, zero DB load)
python scripts/export_credentials_for_migration.py

# Step 2: Fill secrets interactively (10-20 mins - secure prompts)
python scripts/fill_secrets_interactive.py

# Step 3: Migrate to target (2 mins - creates with proper encryption)
ansible-playbook credential_migration/migrate_credentials.yml
```

**Benefits:**
- ✅ Credential structure migration successful
- ✅ Zero database load (uses API only - 3 calls total)
- ✅ Proper encryption (fresh credentials in target)
- ✅ Automated playbook generation
- ✅ Efficient credential migration workflow

⚠️ **Important:** Secrets (passwords, tokens, keys) must be manually filled as AAP API doesn't export them.

**Documentation:** See [credential-migration.md](docs/guides/credential-migration.md) for complete guide.

### Testing

The tool has been tested with:
- ✅ **AAP 2.4 → AAP 2.6** migrations
- ✅ Organizations, users, teams, and RBAC
- ✅ Inventories including dynamic inventories
- ✅ Credentials across multiple credential types
- ✅ Job templates with dependencies
- ✅ Projects and execution environments

For detailed information, see **[USER-GUIDE.md](USER-GUIDE.md)** for comprehensive documentation including:
- Complete setup and installation instructions
- Configuration reference
- Step-by-step migration process
- RBAC migration guide
- Troubleshooting and FAQ
- Best practices

## Documentation

Full documentation is available via MkDocs with the Material theme, and comprehensive user guidance in [USER-GUIDE.md](USER-GUIDE.md).

### Viewing Documentation Locally

```bash
# Serve docs locally (hot-reload enabled)
mkdocs serve

# Open in browser: http://127.0.0.1:8000
```

### Building Static Documentation

```bash
# Build static HTML site
mkdocs build

# Output is in site/ directory
```

### Documentation Structure

```text
docs/
├── index.md                           # Home page
├── getting-started/
│   ├── installation.md                # Installation guide
│   ├── quickstart.md                  # Quick start tutorial
│   └── configuration.md               # Configuration reference
├── user-guide/
│   ├── cli-reference.md               # CLI command reference
│   ├── migration-workflow.md          # Migration workflow guide
│   └── troubleshooting.md             # Troubleshooting guide
├── developer-guide/
│   ├── contributing.md                # Contribution guidelines
│   ├── adding-resource-types.md       # How to add new resource types
│   └── architecture.md                # Architecture overview
└── reference/
    └── changelog.md                   # Version history
```

## Development

### Running Tests

```bash

# Run all tests
pytest

# Run unit tests only (fast)
pytest tests/unit/

# Run with coverage
pytest --cov=src/aap_migration --cov-report=html

# Run integration tests (requires AAP instances)
pytest tests/integration/ -m integration

# Run performance benchmarks
pytest tests/performance/

# Disable progress display for CI
pytest tests/unit/ --disable-progress

```

### Code Quality

```bash

# Format code
make format

# Run linters
make lint

# Type checking
make typecheck

# Run all checks
make check

```

## What Gets Migrated

The tool migrates all AAP resources in the correct dependency order:

✅ **Foundation Resources:**
- Organizations (100%)
- Users (100%)
- Teams (100%)
- Labels (100%)

✅ **Credentials:**
- Credential Types (100%)
- Credentials (100% - metadata only, secrets must be recreated)

✅ **Execution Environment:**
- Execution Environments (100%)
- Instance Groups (100%)

✅ **Projects:**
- Projects (100% - with automatic sync)

✅ **Inventories:**
- Static Inventories (100%)
- Dynamic Inventories (100%)
- Inventory Sources (SCM configuration)
- Inventory Source Schedules
- All Hosts (bulk operations)

✅ **Templates:**
- Job Templates (100%)
- Workflow Job Templates (100%)
- Workflow Nodes (100%)

✅ **Access Control:**
- RBAC Role Assignments (70-95% - via separate script)

**Total Migration Success Rate:** 89-95% of all resources (based on production testing)

For detailed information on what's included and what requires manual steps, see [USER-GUIDE.md](USER-GUIDE.md).

## 📚 Documentation

### Getting Started

1. **[QUICK-START.md](QUICK-START.md)** - Quick start guide
2. **[USER-GUIDE.md](USER-GUIDE.md)** - Complete user manual

### Workflow Guides

- **[Credential-First Migration](docs/workflows/CREDENTIAL-FIRST-WORKFLOW.md)** - Detailed credential workflow
- **[Migration Workflow Diagrams](docs/workflows/MIGRATION-WORKFLOW-DIAGRAM.md)** - Visual process diagrams
- **[RBAC Migration](docs/workflows/RBAC-MIGRATION-GUIDE.md)** - Role-based access control migration
- **[Credential Migration Guide](docs/guides/credential-migration.md)** - Comprehensive credential guide

### Configuration

- **[.env.example](.env.example)** - Environment variable template
- **[config/config.yaml](config/config.yaml)** - Application configuration
- **[config/mappings.yaml.example](config/mappings.yaml.example)** - Resource name mapping examples

### Additional Documentation

- **[docs/](docs/)** - Complete documentation (getting started, user guides, developer guides)
- **[examples/](examples/)** - Example configurations and playbooks
- **[CHANGELOG.md](CHANGELOG.md)** - Version history

### Getting Help

**Quick References:**
```bash
# Show all available commands
aap-bridge --help

# Show credential commands
aap-bridge credentials --help

# Show migration options
aap-bridge migrate --help

# View migration logs
tail -f logs/migration.log
```

**Common Questions:**
- How do I check which credentials are missing? → Run `aap-bridge credentials compare`
- Can I migrate only credentials? → Yes, run `aap-bridge credentials migrate`
- What if credentials fail to migrate? → Check `./reports/credential-comparison.md` and logs
- Why do secrets show as `$encrypted$`? → AAP API security - update secrets manually after migration
- Can I test without making changes? → Yes, use `--dry-run` flag

## Project Status

**Current Version**: 0.2.0 - Credential-First Release

**What's New in v0.2.0:**
- ✨ Credential-first migration workflow
- ✨ Automatic credential comparison before migration
- ✨ New CLI commands: `aap-bridge credentials`
- ✨ Detailed credential comparison reports
- ✨ Validated with regression and full migration tests
- 🐛 Fixed method name: `store_id_mapping` → `save_id_mapping`

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Security

For security concerns and vulnerability reporting, please see [SECURITY.md](SECURITY.md).

## Support

- **Issues**: Report bugs and request features via [GitHub Issues](https://github.com/antonysallas/aap-bridge/issues)
- **Security**: Report vulnerabilities privately (see [SECURITY.md](SECURITY.md))

## Acknowledgments

Built following best practices from:

- Red Hat AAP documentation
- Red Hat Communities of Practice (COP) collections
- HashiCorp Vault integration patterns
- Python async/await patterns for high-performance API clients
