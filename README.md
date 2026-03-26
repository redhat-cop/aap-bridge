# AAP Bridge

A production-grade Python tool for migrating Ansible Automation Platform (AAP)
installations from one version to another, designed to handle large-scale
migrations

## Supported Versions

**Source AAP:**
- AAP 2.4, 2.5 (RPM-based or containerized)

**Target AAP:**
- AAP 2.5, 2.6 (containerized recommended)

**Common Migration Path:**
- AAP 2.4 (RPM-based) → AAP 2.6 (containerized) ✅ Tested

The tool automatically detects AAP versions and validates compatibility before migration.

## Before You Begin

### Prerequisites: Running AAP Instances

This migration tool requires **two accessible AAP instances**:
- **Source AAP** (version 2.4 or 2.5)
- **Target AAP** (version 2.5 or 2.6)

#### Quick Health Check

Verify both AAP instances are running and accessible:

```bash
# Test Source AAP (should return version info)
curl -k https://your-source-aap/api/v2/ping/
# Expected: {"version": "2.4.x", ...}

# Test Target AAP (should return version info)
curl -k https://your-target-aap/api/controller/v2/ping/
# Expected: {"version": "2.6.x", ...}
```

✅ **If both commands return JSON with version info, you're ready to proceed.**

❌ **If you get connection errors:**
- Verify AAP instances are running
- Check network connectivity and firewall rules
- Verify URLs are correct (note `/api/controller/v2` for AAP 2.6)

#### Don't Have AAP Instances Yet?

**Option 1: Use Existing AAP Infrastructure**
- Contact your AAP administrator for access
- You need **admin** or **superuser** permissions on both instances

**Option 2: Set Up Test Instances**
- Follow [AAP Installation Guide](https://access.redhat.com/documentation/en-us/red_hat_ansible_automation_platform)
- Minimum requirements: 8GB RAM per instance
- Recommended ports: 8443 (source), 10443 (target)

**Option 3: Red Hat Demo Environment**
- Request AAP sandbox from Red Hat for testing

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
git clone https://github.com/arnav3000/aap-bridge-fork.git
cd aap-bridge-fork

# Create virtual environment (using uv)
uv venv --seed --python 3.12
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv sync
```

**Alternative: Using standard Python venv**

If you don't have `uv` installed, use Python's built-in venv:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install package and dependencies
pip install -e .
```

**Verify Installation:**

```bash
# Check installation was successful
aap-bridge --version
# Should display: AAP Bridge version 0.2.0

# View available commands
aap-bridge --help
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

#### 2. Getting AAP API Tokens

You need API tokens with **write** permissions for both Source and Target AAP instances.

##### Method 1: AAP Web UI (Recommended)

**For each AAP instance (repeat for Source and Target):**

1. Log in to AAP web interface
2. Click your **username** in the top-right corner
3. Select **"Tokens"** from the dropdown menu
4. Click **"Add"** or **"Create Token"**
5. Fill in the form:
   - **Description:** `Migration Tool - Source` (or `Target`)
   - **Application:** Leave blank
   - **Scope:** Select **"Write"**
6. Click **"Save"**
7. **⚠️ Copy the token immediately!** It will only be shown once.

**Required Permissions:**
- Your user account needs **Superuser** or **Organization Admin** permissions
- Token must have **Write** scope (not just Read)
- Tokens don't expire by default but can be revoked

##### Method 2: CLI/API

```bash
# Generate token using username and password
curl -k -X POST https://your-aap/api/v2/tokens/ \
  -H "Content-Type: application/json" \
  -u "your_username:your_password" \
  -d '{
    "description": "Migration Tool",
    "scope": "write"
  }'

# Response includes your token - copy the "token" field value
```

##### Verify Your Tokens

Test that your tokens work before proceeding:

```bash
# Test Source token
curl -k -H "Authorization: Bearer YOUR_SOURCE_TOKEN" \
  https://your-source-aap/api/v2/me/
# Should return your user information

# Test Target token
curl -k -H "Authorization: Bearer YOUR_TARGET_TOKEN" \
  https://your-target-aap/api/controller/v2/me/
# Should return your user information
```

#### 3. Environment Configuration

Copy the example environment file and configure your credentials:

```bash

cp .env.example .env

```

Edit `.env` with your AAP instance details and database connection string.

##### Understanding AAP 2.6 Platform Gateway

⚠️ **Critical for AAP 2.6:** The API path is different!

```
AAP 2.4/2.5: https://your-aap/api/v2
AAP 2.6:     https://your-aap/api/controller/v2
             Note the /controller/ ^^^^^^^^^^^^
```

AAP 2.6 uses "Platform Gateway" which provides a unified API entry point. Always use `/api/controller/v2` for target AAP 2.6.

**How to verify:**
```bash
# AAP 2.6 responds to Platform Gateway path
curl -k https://your-aap26/api/controller/v2/ping/
```

##### Configuration Examples

**Example 1: Basic Setup (Recommended for Most Users)**

```bash
# .env file

# Source AAP 2.4 instance
SOURCE__URL=https://aap24-prod.company.com/api/v2
SOURCE__TOKEN=aBc123dEf456GhI789jKlMnO...  # Your actual token from step 2
SOURCE__VERIFY_SSL=false  # Use 'true' for production with valid SSL certs
SOURCE__TIMEOUT=300

# Target AAP 2.6 instance
TARGET__URL=https://aap26-prod.company.com/api/controller/v2  # Note: /api/controller/v2
TARGET__TOKEN=xYz987WvU654TsR321qPoNmL...  # Your actual token from step 2
TARGET__VERIFY_SSL=false  # Use 'true' for production with valid SSL certs
TARGET__TIMEOUT=300

# Database: SQLite (default - no setup needed!)
MIGRATION_STATE_DB_PATH=sqlite:///./migration_state.db

# Vault: Not using (credentials will need manual secret updates after migration)
# VAULT__URL=
# VAULT__ROLE_ID=
# VAULT__SECRET_ID=
```

**Example 2: With HashiCorp Vault (Optional)**

```bash
# Same as Example 1, plus:

# HashiCorp Vault configuration
VAULT__URL=https://vault.company.com:8200
VAULT__ROLE_ID=12345678-1234-1234-1234-123456789012
VAULT__SECRET_ID=87654321-4321-4321-4321-210987654321
VAULT__MOUNT_POINT=secret
VAULT__PATH=aap/credentials
```

**Example 3: Enterprise Scale with PostgreSQL**

```bash
# Source and Target configs (same as Example 1)
SOURCE__URL=https://aap24-prod.company.com/api/v2
SOURCE__TOKEN=aBc123dEf456GhI789jKlMnO...
# ... (other SOURCE settings)

TARGET__URL=https://aap26-prod.company.com/api/controller/v2
TARGET__TOKEN=xYz987WvU654TsR321qPoNmL...
# ... (other TARGET settings)

# Database: PostgreSQL (for very large migrations)
MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:SecurePass123!@db-server.company.com:5432/aap_migration
```

**Common Configuration Values:**

| Setting | Recommended Value | Notes |
|---------|------------------|-------|
| `SOURCE__VERIFY_SSL` | `false` for testing, `true` for production | Set to `false` if using self-signed certs |
| `TARGET__VERIFY_SSL` | `false` for testing, `true` for production | Set to `false` if using self-signed certs |
| `SOURCE__TIMEOUT` | `300` | Increase for slow networks or large datasets |
| `TARGET__TIMEOUT` | `300` | Increase for slow networks or large datasets |

#### 4. Application Configuration

Review and adjust `config/config.yaml` for your environment:

- **Performance settings**: Adjust batch sizes and concurrency based on your AAP instance capacity
- **Logging**: Configure log levels and file paths
- **Migration phases**: Enable/disable specific resource types
- **Resource mappings**: Update `config/mappings.yaml` if you need to rename resources during migration (e.g., credential types with different names between AAP versions)

### Usage

#### Recommended Workflow

The recommended approach is to check credentials first, then run phased migration following the dependency order:

```bash
# Step 1: Check what credentials are missing
aap-bridge credentials compare

# Step 2: Review the credential comparison report
cat ./reports/credential-comparison.md

# Step 3: Phased migration (following dependency graph to avoid failures)
# NOTE: If you encounter asyncio errors, use the manual three-step process shown below

# Phase 1: Foundation
aap-bridge migrate -r organizations -r users -r teams --skip-prep

# Phase 2: Credentials (CRITICAL - must be 100% complete)
aap-bridge migrate -r credential_types -r credentials --skip-prep

# Phase 3: Infrastructure
aap-bridge migrate -r execution_environments -r projects -r inventories --skip-prep
aap-bridge migrate -r inventory_sources --skip-prep

# Phase 4: Hosts
aap-bridge migrate -r hosts --skip-prep

# Phase 5: Instance Groups
aap-bridge migrate -r instance_groups --skip-prep

# Phase 6: Automation
aap-bridge migrate -r job_templates -r workflow_job_templates --skip-prep

# Phase 7: Schedules
aap-bridge migrate -r schedules --skip-prep

# Phase 8: Settings (Optional - review before applying)
aap-bridge migrate -r settings --skip-prep

# Step 4: Validate migration
aap-bridge validate all --sample-size 4000

# Step 5: Migrate RBAC role assignments (after main migration)
python rbac_migration.py
```

**⚠️ Workaround: Manual Three-Step Migration (Use if `migrate` command fails)**

If the `migrate` command fails with asyncio errors, run each phase separately:

```bash
# Phase 1: Foundation
aap-bridge export -r organizations -r users -r teams
aap-bridge transform -r organizations -r users -r teams
aap-bridge import -r organizations -r users -r teams --yes

# Phase 2: Credentials
aap-bridge export -r credential_types -r credentials
aap-bridge transform -r credential_types -r credentials
aap-bridge import -r credential_types -r credentials --yes

# Phase 3: Infrastructure
aap-bridge export -r execution_environments -r projects -r inventories -r inventory_sources
aap-bridge transform -r execution_environments -r projects -r inventories -r inventory_sources
aap-bridge import -r execution_environments -r projects -r inventories -r inventory_sources --yes

# Phase 4: Hosts
aap-bridge export -r hosts
aap-bridge transform -r hosts
aap-bridge import -r hosts --yes

# Phase 5: Instance Groups
aap-bridge export -r instance_groups
aap-bridge transform -r instance_groups
aap-bridge import -r instance_groups --yes

# Phase 6: Automation
aap-bridge export -r job_templates -r workflow_job_templates
aap-bridge transform -r job_templates -r workflow_job_templates
aap-bridge import -r job_templates -r workflow_job_templates --yes

# Phase 7: Schedules
aap-bridge export -r schedules
aap-bridge transform -r schedules
aap-bridge import -r schedules --yes

# Phase 8: Settings (Optional)
aap-bridge export -r settings
aap-bridge transform -r settings
aap-bridge import -r settings --yes
```

**Understanding `--skip-prep`:**

The `--skip-prep` flag skips the schema discovery phase. Use it when:
- ✅ You've already run schema prep once (schemas already exist in `schemas/` directory)
- ✅ Running subsequent migration phases after Phase 1
- ✅ Re-running migrations in the same session

Don't use `--skip-prep` when:
- ❌ First time running the migration (no schemas exist yet)
- ❌ Schema files were deleted or need to be regenerated
- ❌ AAP instances were upgraded and schemas may have changed

**Note:** The `export`, `transform`, and `import` commands don't use `--skip-prep` because they don't perform schema discovery.

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

# Phased migration (recommended - follows dependency graph)
# Phase 1: Foundation
aap-bridge migrate -r organizations -r users -r teams --skip-prep

# Phase 2: Credentials
aap-bridge migrate -r credential_types -r credentials --skip-prep

# Phase 3: Projects & Inventories
aap-bridge migrate -r execution_environments -r projects -r inventories --skip-prep

# Phase 4: Job Templates
aap-bridge migrate -r job_templates -r workflow_job_templates --skip-prep

# Export from source AAP only (for specific resource types)
aap-bridge export -r inventories --output exports/

# Import to target AAP only (for specific resource types)
aap-bridge import -r inventories --input exports/

# Validate migration
aap-bridge validate all --sample-size 4000

# View migration report
aap-bridge report summary

# Migrate RBAC role assignments (separate script - after all resources)
python rbac_migration.py
```

**Note:** RBAC role assignments are migrated using a separate Python script (`rbac_migration.py`) after the main migration completes. This ensures all resources exist before assigning roles. See [USER-GUIDE.md](USER-GUIDE.md) for detailed RBAC migration instructions.

#### Workaround: Manual Three-Step Migration

**⚠️ If `aap-bridge migrate -r <resource>` fails with asyncio or event loop errors, use the manual three-step process:**

The migration process consists of three separate phases that can be executed independently:

```bash
# Step 1: Export from source AAP
aap-bridge export -r organizations

# Step 2: Transform to target format
aap-bridge transform -r organizations

# Step 3: Import to target AAP
aap-bridge import -r organizations
```

**When to use manual three-step process:**
- ✅ Asyncio event loop errors
- ✅ Connection timeouts during combined operation
- ✅ Need to inspect transformed data before import
- ✅ Debugging specific migration phases
- ✅ Split operations across different time windows

**Example: Complete Phase 1 using manual process**

```bash
# Export all Phase 1 resources
aap-bridge export -r organizations -r users -r teams

# Transform all Phase 1 resources
aap-bridge transform -r organizations -r users -r teams

# Import all Phase 1 resources
aap-bridge import -r organizations -r users -r teams
```

**Why this works:**
- Each command uses a separate event loop lifecycle
- Avoids asyncio cleanup issues
- Allows inspection of exports/ and xformed/ directories between steps
- Provides better error isolation

**File locations:**
- Exported data: `exports/<resource_type>/`
- Transformed data: `xformed/<resource_type>/`
- State database: `migration_state.db`

#### Output Control

The tool provides flexible output modes for different environments:

```bash

# Default: Live progress display with clean console output
aap-bridge migrate -r organizations -r credential_types -r credentials --skip-prep

# Quiet mode: Errors only (for scripting)
aap-bridge migrate -r organizations -r credential_types -r credentials --skip-prep --quiet

# Disable progress: For CI/CD environments
aap-bridge migrate -r organizations -r credential_types -r credentials --skip-prep --disable-progress

# Detailed stats: Show additional metrics
aap-bridge migrate -r organizations -r credential_types -r credentials --skip-prep --show-stats

# Combination: Quiet + no progress for automation
aap-bridge migrate -r organizations -r credential_types -r credentials --skip-prep --quiet --disable-progress

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
aap-bridge migrate -r organizations -r credential_types -r credentials --skip-prep

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

## Migration Order and Dependencies

⚠️ **CRITICAL**: Resources MUST be migrated in the correct dependency order to avoid failures.

### Dependency Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   CORRECT MIGRATION DEPENDENCY ORDER                    │
└─────────────────────────────────────────────────────────────────────────┘

PHASE 1: FOUNDATION (No Dependencies)
┌────────────────────────────────────────┐
│  1. Organizations                      │  ← START HERE (Required by almost everything)
│  2. Users                              │  ← Independent, can run in parallel with orgs
│  3. Labels                             │  ← Independent
└────────────────────────────────────────┘
                    ↓
PHASE 2: TEAMS (Requires Organizations)
┌────────────────────────────────────────┐
│  4. Teams                              │  ← Requires: Organizations
└────────────────────────────────────────┘
                    ↓
PHASE 3: EXECUTION ENVIRONMENTS (Independent)
┌────────────────────────────────────────┐
│  5. Execution Environments             │  ← Can run after Phase 1 or in parallel
└────────────────────────────────────────┘
                    ↓
PHASE 4: CREDENTIALS (CRITICAL - Requires Organizations & Credential Types)
┌────────────────────────────────────────┐
│  6. Credential Types (MUST BE FIRST)   │  ← Required by: Credentials
│     - Migrate all managed types        │
│     - Migrate all custom types         │
└────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────┐
│  7. Credentials (MUST BE SECOND)       │  ← Requires: Organizations, Credential Types
│     ⚠️ 100% completion required        │
│     before proceeding                  │
└────────────────────────────────────────┘
                    ↓
PHASE 5: PROJECTS & INVENTORIES (Require Credentials)
┌────────────────────────────────────────┐
│  8. Projects                           │  ← Requires: Organizations, Credentials
│     (with automatic sync)              │     (for SCM authentication)
└────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────┐
│  9. Inventories                        │  ← Requires: Organizations
│     (static & dynamic)                 │
└────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────┐
│  10. Inventory Sources                 │  ← Requires: Inventories, Projects
│      (SCM configuration)               │     Credentials (for SCM auth)
└────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────┐
│  11. Hosts (bulk operations)           │  ← Requires: Inventories
│      (200/batch - AAP maximum)         │
└────────────────────────────────────────┘
                    ↓
PHASE 6: EXECUTION ENVIRONMENTS & INSTANCE GROUPS
┌────────────────────────────────────────┐
│  12. Execution Environments            │  ← Requires: Organizations
│      (container images)                │
└────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────┐
│  13. Instance Groups                   │  ← Requires: None (infrastructure)
│      (controller node groups)          │
└────────────────────────────────────────┘
                    ↓
PHASE 7: JOB TEMPLATES & WORKFLOWS (Require Everything Above)
┌────────────────────────────────────────┐
│  14. Job Templates                     │  ← Requires: Organizations, Projects,
│                                        │     Inventories, Credentials,
│                                        │     Execution Environments, Instance Groups
└────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────┐
│  15. Workflow Job Templates            │  ← Requires: Job Templates
│      & Workflow Nodes                  │
└────────────────────────────────────────┘
                    ↓
PHASE 8: SCHEDULES
┌────────────────────────────────────────┐
│  16. Schedules                         │  ← Requires: Projects, Inventory Sources
│      (for job templates, workflows,    │     Job Templates, Workflow Job Templates
│       inventory sources, projects)     │
└────────────────────────────────────────┘
                    ↓
PHASE 9: SETTINGS (Optional)
┌────────────────────────────────────────┐
│  17. Settings (Global Configuration)   │  ← Optional: None (singleton)
│      (LDAP, logging, UI settings)      │     Review before applying
└────────────────────────────────────────┘
                    ↓
PHASE 10: ACCESS CONTROL (Final Step)
┌────────────────────────────────────────┐
│  18. RBAC Role Assignments             │  ← Requires: ALL resources above
│      (via rbac_migration.py)           │     to exist first
└────────────────────────────────────────┘
```

### Critical Dependency Rules

🔴 **MUST MIGRATE IN ORDER:**
1. **Organizations → Credential Types → Credentials** (This sequence is MANDATORY)
2. **Credentials → Projects/Inventories** (Projects & inventories need credentials)
3. **Job Templates LAST** (They depend on almost everything)

⚠️ **Common Mistakes to Avoid:**
- ❌ Migrating credentials before credential types → **WILL FAIL** (missing credential type mappings)
- ❌ Migrating credentials before organizations → **WILL FAIL** (missing organization references)
- ❌ Migrating job templates before credentials → **WILL FAIL** (missing credential dependencies)
- ❌ Migrating RBAC before resources exist → **WILL FAIL** (no resources to assign roles to)

✅ **Correct Phased Migration Example:**

```bash
# Phase 1: Foundation
aap-bridge migrate -r organizations -r users -r teams --skip-prep

# Verify Phase 1 completed successfully
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings GROUP BY resource_type;"

# Phase 2: Credentials (CRITICAL - Must come after organizations)
aap-bridge migrate -r credential_types -r credentials --skip-prep

# Verify Phase 2 completed successfully (should show 100% success)
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type IN ('credential_types', 'credentials') GROUP BY resource_type;"

# Phase 3: Projects & Inventories (Now safe - credentials exist)
aap-bridge migrate -r projects -r inventories --skip-prep

# Phase 3b: Inventory Sources (Dynamic inventories)
# Note: Inventory sources are automatically synced after import
aap-bridge migrate -r inventory_sources --skip-prep

# ℹ️ Automatic Sync: The migration tool automatically triggers sync for all
# inventory sources after import. This fetches the actual inventory data from
# SCM/cloud providers. You can verify sync status in the AAP Web UI or via API.

# Optional: Verify sync status if needed
sqlite3 migration_state.db "SELECT source_id, target_id FROM id_mappings WHERE resource_type='inventory_sources';"

# Check sync status via API (optional)
curl -sk -H "Authorization: Bearer $TARGET__TOKEN" \
  "https://localhost:10443/api/controller/v2/inventory_sources/<TARGET_ID>/inventory_updates/?order_by=-id&page_size=1" | \
  jq -r '.results[0].status'

# If sync failed, you can manually trigger it using one of these methods:

# Method 1: Via awx CLI (if available)
awx inventory_sources update <TARGET_ID>

# Method 2: Via API
curl -sk -X POST \
  -H "Authorization: Bearer $TARGET__TOKEN" \
  "https://localhost:10443/api/controller/v2/inventory_sources/<TARGET_ID>/update/"

# Method 3: Via AAP Web UI
# Go to: Resources → Inventories → [Select Inventory] → Sources → [Click Sync button]

# Phase 4: Hosts (Now safe after inventory sources are synced)
# Note: Static inventory hosts can be migrated now. Dynamic inventory hosts
# come from inventory source syncs (completed above).
aap-bridge migrate -r hosts --skip-prep

# Phase 5: Execution Environments & Instance Groups
# These are required by job templates
aap-bridge migrate -r execution_environments --skip-prep
aap-bridge migrate -r instance_groups --skip-prep

# Verify Phase 5 completed successfully
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type IN ('execution_environments', 'instance_groups') GROUP BY resource_type;"

# Phase 6: Job Templates & Workflows (Now safe - all dependencies exist)
aap-bridge migrate -r job_templates --skip-prep
aap-bridge migrate -r workflow_job_templates --skip-prep

# Verify Phase 6 completed successfully
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type IN ('job_templates', 'workflow_job_templates') GROUP BY resource_type;"

# Phase 7: Schedules (Requires job templates, workflows, projects, inventory sources)
aap-bridge migrate -r schedules --skip-prep

# Verify Phase 7 completed successfully
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type='schedules';"

# Phase 8: Settings (Optional - Global configuration)
# Note: Settings are environment-specific (LDAP, logging, UI settings, etc.)
# Review and adjust settings before applying to ensure they match your target environment
aap-bridge migrate -r settings --skip-prep

# Phase 9: RBAC (Final step)
python rbac_migration.py
```

### Why This Order Matters

**Organizations First:**
- Organizations are referenced by credentials, projects, inventories, job templates
- Without organizations, most resources will fail to import

**Credential Types Before Credentials:**
- Credentials reference credential types by ID
- Managed credential types must be looked up and mapped in target AAP
- Custom credential types must be created before credentials can use them

**Credentials Before Projects/Inventories:**
- Projects need credentials for SCM authentication
- Inventory sources need credentials for dynamic inventory sync
- Without credentials, projects/inventories will import but won't be functional

**Inventory Sources Are Automatically Synced:**
- ✅ Inventory sources are automatically synced after import
- Syncing triggers the actual data fetch from SCM/cloud providers
- Dynamic inventory hosts are fetched during the sync process
- You can verify sync status in AAP Web UI or via API
- Manual sync commands are available in Phase 3b if needed for troubleshooting

**Execution Environments & Instance Groups Before Job Templates:**
- Execution environments define the container images used to run playbooks
- Instance groups define which controller nodes can execute jobs
- Job templates reference both execution environments and instance groups
- These must be migrated before job templates to avoid missing dependency errors

**Job Templates & Workflows Before Schedules:**
- Job templates reference: organizations, projects, inventories, credentials, execution environments, instance groups
- Workflow job templates reference: job templates
- Schedules reference: projects, inventory sources, job templates, workflow job templates
- All dependencies must exist before schedules can be created

**Schedules After Job Templates:**
- Schedules can be attached to projects, inventory sources, job templates, and workflow job templates
- Schedules define when these resources should run automatically (e.g., nightly, weekly)
- Must be migrated after all schedulable resources exist

**Settings Migration (Optional):**
- Settings is a singleton resource containing global AAP configuration (LDAP, logging, UI settings, etc.)
- ⚠️ **Review carefully before applying**: Settings are environment-specific and may not be appropriate for the target environment
- Settings migration is optional and independent of other resources
- Common settings to review: authentication backends, logging levels, session timeouts, UI configurations

### Dependency Reference Table

| Resource Type | Requires (Dependencies) | Required By |
|--------------|-------------------------|-------------|
| Organizations | None | Teams, Credentials, Projects, Inventories, Job Templates |
| Users | None | Teams, RBAC |
| Labels | None | Various resources |
| Teams | Organizations | RBAC |
| Execution Environments | Organizations (optional) | Job Templates |
| Instance Groups | None (infrastructure) | Job Templates |
| **Credential Types** | None | **Credentials** |
| **Credentials** | **Organizations, Credential Types** | **Projects, Inventory Sources, Job Templates** |
| Projects | Organizations, Credentials (for SCM) | Inventory Sources, Job Templates |
| Inventories | Organizations | Hosts, Inventory Sources, Job Templates |
| Inventory Sources | Inventories, Projects, Credentials | Schedules |
| Hosts | Inventories | Job Templates |
| Job Templates | Organizations, Projects, Inventories, Credentials, Execution Environments, Instance Groups | Workflows, Schedules |
| Workflow Job Templates | Job Templates | Schedules |
| Schedules | Projects, Inventory Sources, Job Templates, Workflow Job Templates | None |
| Settings | None (singleton) | None (global configuration) |
| RBAC | All resources above | None |

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
