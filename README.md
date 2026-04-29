# AAP Bridge

A production-grade Python tool for migrating Ansible Automation Platform (AAP)
installations from one version to another, designed to handle large-scale
migrations (e.g., 80,000+ hosts)

## Features

- **Bulk Operations**: Leverages AAP bulk APIs for high-performance migrations
- **State Management**: PostgreSQL-backed state tracking with checkpoint/resume
  capability
- **Idempotency**: Safely resume interrupted migrations without creating
  duplicates
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

## Architecture

The tool is organized into several key components:

- **Client Layer**: HTTP clients for source AAP, target AAP, and HashiCorp Vault
  with retry logic and rate limiting
- **Migration Layer**: ETL pipeline with exporters, transformers, and importers
  for all AAP resource types
- **State Management**: Database-backed progress tracking, checkpoint creation,
  and ID mapping
- **CLI**: User-friendly command-line interface for all operations

## Quick Start

### Prerequisites

- **Python 3.12** or higher
- **PostgreSQL** database (Required for state management)
- **Hardware**: Minimum 8GB RAM recommended for large migrations
- **Network**: Access to Source AAP, Target AAP, and the state management
  PostgreSQL database (not AAP)
- **Credentials**: Admin access to both Source and Target AAP instances
- **HashiCorp Vault** (Optional but recommended): For migrating encrypted
  credentials securely
- **Instance Groups**: Any instance groups that have RBAC role assignments on
  the source must already exist on the target with the same name before running
  the migration. Instance groups are not migrated by this tool; they are
  resolved by name on the target when applying role assignments.

### Installation

```bash
# Clone the repository
git clone https://github.com/redhat-cop/aap-bridge.git
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

The tool requires a PostgreSQL database to track migration state. You must create this database before running the tool. The tool will automatically create the necessary tables on first run.

```bash

# Example: Install and configure PostgreSQL.
sudo yum install postgresql-server
sudo postgresql-setup --initdb

# If you have kerberos, you likely need to change the IPv4 and IPv6 local connections to a newer METHOD, such as scram-sha-256.
sudo vi /var/lib/pgsql/data/pg_hba.conf

# IPv4 local connections:
host    all             all             127.0.0.1/32            scram-sha-256
# IPv6 local connections:
host    all             all             ::1/128                 scram-sha-256

sudo systemctl enable postgresql --now
systemctl status postgresql # Check it's good.

# Create database and user locally as the postgres user.
psql -c "CREATE DATABASE aap_migration;"
psql -c "CREATE USER aap_migration_user WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE aap_migration TO aap_migration_user;"
# Ensure the user owns the schema/tables (Postgres 15+)
psql -d aap_migration -c "GRANT ALL ON SCHEMA public TO aap_migration_user;"

# As a normal user, test connectivity to the database:
psql -h localhost -U aap_migration_user -W aap_migration

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

# PostgreSQL state database (REQUIRED)
MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:your_secure_password@localhost:5432/aap_migration

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

#### Basic Commands

```bash

# Menu Based CLI
aap-bridge

# Migrate full AAP
aap-bridge migrate full --config config/config.yaml

# Export from source AAP only
aap-bridge export all --output exports/

# Import to target AAP only
aap-bridge import inventories --input exports/inventories.json

# Validate migration
aap-bridge validate all --sample-size 4000

# View migration report
aap-bridge report summary

```

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

1. Organizations, Labels, Users, Teams
2. Credential Types, Credentials
3. Projects, Execution Environments
4. Inventories (bulk operations)
5. Hosts (bulk operations, 200/batch)
6. Job Templates, Workflows
7. RBAC role assignments

## Documentation

Full documentation is available via MkDocs with the Material theme.

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

## Critical Constraints

### Encrypted Credentials

**Important**: Encrypted credentials cannot be extracted from source AAP via API. Passwords, SSH keys, and secret fields will show as `$encrypted$`.

**Solution**: Credentials must be manually recreated in HashiCorp Vault before migration.

### Platform Gateway

AAP 2.6 routes all API calls through the Platform Gateway at `https://<gateway>/api/controller/v2/`. The tool automatically handles this routing.

## Project Status

**Current Version**: 0.1.0 - Initial Release

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

- **Issues**: Report bugs and request features via [GitHub Issues](https://github.com/redhat-cop/aap-bridge/issues)
- **Security**: Report vulnerabilities privately (see [SECURITY.md](SECURITY.md))

## Acknowledgments

Built following best practices from:

- Red Hat AAP documentation
- Red Hat Communities of Practice (COP) collections
- HashiCorp Vault integration patterns
- Python async/await patterns for high-performance API clients
