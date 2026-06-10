# Installation

## Prerequisites

Before installing AAP Bridge, ensure you have:

- **Python 3.12** or higher
- **PostgreSQL** database (for state management)
- **uv** package manager (recommended) or pip
- Network access to source and target AAP instances
- **API tokens**: read-only scope for the source AAP (with permission to read
  all resources being migrated); read/write scope with admin-level access for
  the target AAP

### Hardware Requirements

| Migration Size | RAM | Notes |
| --- | --- | --- |
| < 10,000 hosts | 4GB | Minimal setup |
| 10,000 - 50,000 hosts | 8GB | Recommended |
| 50,000+ hosts | 16GB+ | Large-scale migrations |

## Installation Methods

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Create virtual environment
uv venv --seed --python 3.12
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv sync

```

### Using pip

```bash
# Clone the repository
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

```

### Development Installation

For contributing or development:

```bash
# Clone and setup
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# Use make for complete setup
make setup

```

This installs all development dependencies including testing and linting tools.

## Database Setup

AAP Bridge requires a PostgreSQL database for state management:

```bash
# Create database and user
psql -c "CREATE DATABASE aap_migration;"
psql -c "CREATE USER aap_migration_user WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE aap_migration TO aap_migration_user;"

# For PostgreSQL 15+, grant schema permissions
psql -d aap_migration -c "GRANT ALL ON SCHEMA public TO aap_migration_user;"

```

!!! note
    The tool automatically creates the necessary tables on first run.

## Verify Installation

```bash
# Check version
aap-bridge --version

# Show help
aap-bridge --help

# Validate configuration
aap-bridge config validate

```

## Next Steps

- [Quick Start](quickstart.md) - Get up and running in 5 minutes
- [Configuration](configuration.md) - Configure your environment
