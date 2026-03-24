# AAP Migration Tool - Complete User Guide

**Version:** 0.1.0
**Last Updated:** 2026-03-04

---

## Table of Contents

1. [Overview](#overview)
2. [What Gets Migrated](#what-gets-migrated)
3. [Prerequisites](#prerequisites)
4. [Installation & Setup](#installation--setup)
5. [Configuration](#configuration)
6. [Migration Process](#migration-process)
7. [RBAC Migration](#rbac-migration)
8. [Validation](#validation)
9. [Known Issues & Limitations](#known-issues--limitations)
10. [Troubleshooting](#troubleshooting)
11. [FAQ](#faq)
12. [Support](#support)

---

## Overview

### What is AAP Bridge?

AAP Bridge is a production-grade Python tool for migrating Ansible Automation Platform (AAP) installations between versions. It handles large-scale migrations (80,000+ hosts tested) using bulk APIs, database-backed state management, and checkpoint/resume capabilities.

### Key Features

✅ **Comprehensive Migration**
- Organizations, users, teams, credentials, projects
- Inventories, hosts, inventory sources, schedules
- Job templates, workflows, workflow nodes
- Execution environments, credential types
- **Note:** RBAC roles require separate script (see [RBAC Migration](#rbac-migration))

✅ **Production-Ready**
- Idempotent (safe to re-run)
- Checkpoint/resume capability
- Bulk operations for performance
- Database-backed state tracking
- Detailed logging and progress reporting

✅ **Flexible**
- Configurable batch sizes and concurrency
- Support for SQLite (default) or PostgreSQL
- Export-transform-import workflow
- Dry-run mode for testing

### Supported Versions

**Source (AAP to migrate FROM):**
- AAP 2.3+
- AAP 2.4+
- AAP 2.5+

**Target (AAP to migrate TO):**
- AAP 2.5+
- AAP 2.6+

**Common Migration Paths:**
- AAP 2.4 → AAP 2.6 ✅ **Tested**
- AAP 2.4 → AAP 2.5 ✅ Supported
- AAP 2.5 → AAP 2.6 ✅ Supported

---

## What Gets Migrated

### ✅ Fully Automated Migration

The following resources are **automatically migrated** by the main tool:

| Resource Type | Migrated | Notes |
|--------------|----------|-------|
| **Organizations** | ✅ Yes | Including all settings |
| **Users** | ✅ Yes | Accounts created, but see RBAC note |
| **Teams** | ✅ Yes | Team structure preserved |
| **Credential Types** | ✅ Yes | Custom credential types |
| **Credentials** | ⚠️ Partial | See [Encrypted Credentials](#encrypted-credentials) |
| **Execution Environments** | ✅ Yes | All EE configurations |
| **Projects** | ✅ Yes | SCM sync deferred to Phase 2 |
| **Inventories** | ✅ Yes | Including dynamic inventories |
| **Inventory Sources** | ✅ Yes | SCM configuration preserved |
| **Hosts** | ✅ Yes | Including host variables |
| **Job Templates** | ✅ Yes | All configurations |
| **Workflow Job Templates** | ✅ Yes | Including workflow structure |
| **Workflow Nodes** | ✅ Yes | Complete workflow graphs |
| **Schedules** | ✅ Yes | Including inventory source schedules |
| **Labels** | ✅ Yes | All label assignments |

### ⚠️ Requires Manual Migration

| Resource Type | Status | Solution |
|--------------|--------|----------|
| **RBAC Role Assignments** | Manual | Use `rbac_migration.py` script (see [RBAC Migration](#rbac-migration)) |
| **Settings** | Manual | Marked as `skipped_manual` |
| **OAuth Applications** | Manual | Recreate in target AAP |
| **OAuth Tokens** | Manual | Generate new tokens |

### ❌ Not Migrated

| Resource Type | Reason |
|--------------|--------|
| **Job History** | Runtime data, not configuration |
| **Inventory Updates** | Runtime data |
| **System Jobs** | AAP-managed |
| **Activity Stream** | Historical data |
| **Notifications** | Runtime data |

---

## Prerequisites

### 1. System Requirements

**Migration Server:**
- Python 3.12+ (tested with 3.12.11)
- 8GB+ RAM (configurable)
- 10GB+ free disk space
- Network access to both source and target AAP

**Source AAP:**
- AAP 2.3+ installation
- API access via `/api/v2/`
- Valid API token with admin privileges

**Target AAP:**
- AAP 2.5+ installation
- Platform Gateway API access via `/api/controller/v2/`
- Valid API token with admin privileges
- Empty or ready to receive migrations

### 2. Access Requirements

**API Tokens:**
- Source AAP: Admin-level OAuth token
- Target AAP: Admin-level OAuth token

**Network:**
- HTTPS access to source AAP (port 443 or custom)
- HTTPS access to target AAP (port 443 or custom)
- SSL certificates (or ability to disable verification for testing)

### 3. Optional: Database

**Default: SQLite (Zero Configuration)**
- Suitable for most migrations (tested with 80,000+ hosts)
- No setup required
- File-based database created automatically

**Optional: PostgreSQL**
- Recommended for 100,000+ resources
- Requires separate PostgreSQL server
- **NOT** AAP's internal database - separate instance

---

## Installation & Setup

### Step 1: Clone Repository

```bash
cd /path/to/your/projects
git clone <repository-url> aap-bridge
cd aap-bridge
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
uv venv --seed --python 3.12
source .venv/bin/activate

# Install dependencies
uv sync
```

### Step 3: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
nano .env
```

**Minimal required settings in `.env`:**

```bash
# Source AAP (where you're migrating FROM)
SOURCE__URL=https://source-aap.example.com/api/v2
SOURCE__TOKEN="your-source-token-here"
SOURCE__VERIFY_SSL=false  # Set to true for production
SOURCE__TIMEOUT=300

# Target AAP (where you're migrating TO)
TARGET__URL=https://target-aap.example.com/api/controller/v2
TARGET__TOKEN="your-target-token-here"
TARGET__VERIFY_SSL=false  # Set to true for production
TARGET__TIMEOUT=300

# Database (SQLite - default, zero configuration)
MIGRATION_STATE_DB_PATH=sqlite:///./migration_state.db
```

**IMPORTANT:**
- Source URL uses `/api/v2/` (standard AAP API)
- Target URL uses `/api/controller/v2/` (Platform Gateway for AAP 2.5+)

### Step 4: Get API Tokens

**Source AAP:**
```bash
# Login to source AAP UI
# Navigate to: User → Tokens
# Create new token with "Write" scope
# Copy the token
```

**Target AAP:**
```bash
# Login to target AAP UI
# Navigate to: User → Tokens
# Create new token with "Write" scope
# Copy the token
```

### Step 5: Test Connection

```bash
# Verify source connection
source .venv/bin/activate
aap-bridge --help

# Test API access
curl -sk -H "Authorization: Bearer YOUR_SOURCE_TOKEN" \
  "https://source-aap.example.com/api/v2/ping/" | jq .
```

---

## Configuration

### Main Configuration File: `config/config.yaml`

This file controls migration behavior. Key sections:

#### 1. Performance Tuning

```yaml
performance:
  # Concurrency settings
  max_concurrent: 5           # Concurrent API requests
  rate_limit: 10              # Requests per second
  max_concurrent_pages: 3     # Parallel page fetching

  # Batch sizes (how many resources per request)
  batch_sizes:
    organizations: 100
    users: 100
    teams: 50
    credentials: 50
    inventories: 100          # Adjust if timeouts occur
    hosts: 100                # Max 200 (AAP limit)
    job_templates: 50         # Reduce if timeouts occur
```

**When to Adjust:**
- **Timeouts occurring?** Reduce `max_concurrent`, `rate_limit`, and batch sizes
- **Migration too slow?** Increase these values (if target AAP can handle it)

#### 2. Export Configuration

```yaml
export:
  skip_dynamic_hosts: false   # Include hosts from dynamic inventories
  skip_smart_inventories: false  # Include dynamic inventories
  skip_hosts_with_inventory_sources: false  # Include all hosts
  records_per_file: 1000      # Split large exports into multiple files
```

**Important:** All set to `false` to include dynamic inventories. Only change if you specifically want to exclude them.

#### 3. Migration Phases

```yaml
phases:
  # Phase 1: Foundation
  organizations: true
  users: true
  teams: true
  labels: true
  credential_types: true

  # Phase 2: Credentials & EE
  credentials: true
  execution_environments: true

  # Phase 3: Projects
  projects: true

  # Phase 4: Inventories
  inventories: true
  inventory_sources: true  # Dynamic inventory sources
  hosts: true

  # Phase 5: Templates
  job_templates: true
  workflow_job_templates: true
  workflow_nodes: true

  # Phase 6: Schedules
  schedules: true

  # Phase 7: RBAC (manual - use rbac_migration.py)
  rbac_assignments: false  # Set to true if RBAC support added
```

**Enable/Disable Phases:**
- Set to `false` to skip a resource type
- Useful for partial migrations or testing

---

## Migration Process

### Overview: Three-Phase Workflow

The migration follows a three-phase process:

```
┌─────────┐       ┌───────────┐       ┌────────┐
│ EXPORT  │  -->  │ TRANSFORM │  -->  │ IMPORT │
│ Source  │       │  Data     │       │ Target │
└─────────┘       └───────────┘       └────────┘
```

### Method 1: Full Automatic Migration (Recommended)

**Single command for complete migration:**

```bash
source .venv/bin/activate
aap-bridge migrate --config config/config.yaml
```

This will:
1. ✅ Discover source and target AAP schemas
2. ✅ Export all resources from source
3. ✅ Transform data for target compatibility
4. ✅ Import to target in correct dependency order
5. ✅ Create checkpoints for resumability

**Expected Output:**
```
ℹ Phase 1: Exporting RAW data from AAP 2.4...
✓ Organizations: 9/9 (100%)
✓ Users: 23/23 (100%)
...

ℹ Phase 2: Transforming data for AAP 2.6...
✓ Organizations: 9 transformed
...

ℹ Phase 3: Importing to AAP 2.6...
✓ Organizations: 9 imported
...

✓ Migration complete!
```

**Duration:** Varies by size
- Small (< 100 resources): 5-10 minutes
- Medium (100-1000 resources): 30-60 minutes
- Large (1000-10000 resources): 2-6 hours
- Very Large (10000+ resources): 6-24+ hours

---

### Method 2: Step-by-Step Migration

For more control, run each phase separately:

#### Step 1: Export

```bash
# Export all resources from source AAP
aap-bridge export all --output exports/
```

**What this does:**
- Connects to source AAP
- Downloads all resource configurations
- Saves to `exports/` directory as JSON files
- Creates split files for large datasets (1000 records/file)

**Output files:**
```
exports/
  organizations/organizations_0001.json
  users/users_0001.json
  inventories/inventories_0001.json
  hosts/hosts_0001.json (and hosts_0002.json if > 1000 hosts)
  ...
```

#### Step 2: Transform

```bash
# Transform data for target AAP compatibility
aap-bridge transform --input exports/ --output xformed/
```

**What this does:**
- Reads exported JSON files
- Removes AAP 2.4-specific fields
- Defers project SCM sync to Phase 2
- Maps field names if changed between versions
- Saves to `xformed/` directory

**Output files:**
```
xformed/
  organizations/organizations_0001.json
  users/users_0001.json
  inventories/inventories_0001.json
  ...
```

#### Step 3: Import

```bash
# Import to target AAP
aap-bridge import --input xformed/
```

**What this does:**
- Reads transformed JSON files
- Resolves dependencies automatically
- Creates resources in target AAP
- Uses bulk operations for performance
- Tracks progress in database
- Creates checkpoints for resumability

---

### Method 3: Selective Migration

Migrate specific resource types only:

```bash
# Export only inventories and hosts
aap-bridge export -r inventories -r hosts

# Transform
aap-bridge transform -r inventories -r hosts

# Import
aap-bridge import -r inventories -r hosts
```

**Use cases:**
- Testing migration of specific resources
- Re-migrating failed resource types
- Partial migrations

---

### Resuming Failed Migrations

If migration fails or is interrupted:

```bash
# Resume from last checkpoint
aap-bridge migrate --resume

# Or resume import specifically
aap-bridge import --resume
```

**How it works:**
- Database tracks what's been migrated
- Resume skips already-completed resources
- Continues from interruption point

---

### Force Re-Migration

To re-import resources (will skip existing by default):

```bash
# Force re-import specific types (clears their progress)
aap-bridge import -r job_templates --force-reimport
```

---

## RBAC Migration

### Important: RBAC Roles Require Separate Script

**The main migration tool does NOT migrate RBAC role assignments.** User accounts are created, but they have no roles/permissions until RBAC is migrated.

### Why Separate?

1. RBAC depends on all resources existing in target
2. Role assignments must be created after resources are migrated
3. Allows you to review and customize role assignments

### RBAC Migration Process

#### Prerequisites

1. ✅ Main migration completed (organizations, users, teams, resources all migrated)
2. ✅ Database file exists: `migration_state.db`
3. ✅ Source and target API tokens in `.env`

#### Step 1: Run RBAC Script

```bash
source .venv/bin/activate
python rbac_migration.py
```

#### Step 2: Review Output

**Expected output:**
```
=== AAP RBAC MIGRATION ===

📊 Loading ID mappings from state database...
   - organizations: 9 mappings
   - users: 23 mappings
   - teams: 11 mappings
   - projects: 7 mappings
✅ Loaded 52 ID mappings

📥 Fetching users from source AAP...
✅ Found 23 users

🔄 Migrating roles for 23 users...

1/23: admin
   👤 admin: 16 roles
      - Admin on Default... ✅
      - Member on Engineering... ✅
      ...
      Result: 15/16 roles migrated

...

=== MIGRATION SUMMARY ===

📊 Statistics:
   Users processed:    23
   Roles found:        65
   Roles created:      47 ✅
   Roles skipped:      4 ⏭️
   Roles failed:       14 ❌

   Success Rate: 72.3%

⚠️  Errors (14):
   - admin: Missing job_template 'Deploy Application' (source ID: 15)
   ...
```

#### Step 3: Handle Failed Roles

**Common reasons for failures:**
1. **Resource doesn't exist in target** (e.g., job template not migrated)
2. **Resource name mismatch** (resource renamed in target)
3. **Resource type not supported** (custom role definitions)

**Solutions:**
- Re-run main migration for missing resource types
- Manually create missing resources
- Re-run RBAC script (it's idempotent)

#### Step 4: Verify RBAC

```bash
# Check user roles in target AAP
curl -sk -H "Authorization: Bearer $TARGET__TOKEN" \
  "https://target-aap/api/controller/v2/users/USERNAME/roles/" | \
  jq '.count'
```

**Or via Web UI:**
1. Login to target AAP
2. Navigate to: Access → Users
3. Select user
4. Check "Roles" tab

---

### Manual RBAC Assignment

If RBAC script fails for specific users, assign roles manually:

#### Via Web UI:
1. Navigate to the resource (Organization, Team, Inventory, etc.)
2. Click "Access" or "User Access" tab
3. Click "Add"
4. Select user and role
5. Save

#### Via API:
```bash
# Example: Assign Organization Admin role

# 1. Get organization ID
ORG_ID=5

# 2. Get Admin role ID for that organization
ROLE_ID=$(curl -sk -H "Authorization: Bearer $TARGET__TOKEN" \
  "https://target-aap/api/controller/v2/organizations/${ORG_ID}/object_roles/" | \
  jq -r '.results[] | select(.name=="Admin") | .id')

# 3. Assign user to role
USER_ID=10
curl -sk -X POST \
  -H "Authorization: Bearer $TARGET__TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"id\": ${USER_ID}}" \
  "https://target-aap/api/controller/v2/roles/${ROLE_ID}/users/"
```

---

## Validation

### Automatic Validation

After migration, validate that everything migrated correctly:

```bash
# Validate all resources
aap-bridge validate all --sample-size 1000

# Validate specific resource types
aap-bridge validate -r organizations -r users
```

**What this checks:**
- Resource counts (source vs target)
- Resource names match
- Key fields preserved
- Statistical sampling for large datasets

**Expected output:**
```
✓ Organizations: 9 source, 9 target (100%)
✓ Users: 23 source, 23 target (100%)
✓ Projects: 7 source, 9 target (includes system projects) ✅
⚠ Hosts: 21 source, 17 target (81%) - 4 missing
```

### Manual Verification

**1. Resource Counts:**
```bash
# Compare counts
echo "Organizations:"
curl -sk -H "Authorization: Bearer $SOURCE__TOKEN" \
  "https://source-aap/api/v2/organizations/?page_size=1" | jq '.count'
curl -sk -H "Authorization: Bearer $TARGET__TOKEN" \
  "https://target-aap/api/controller/v2/organizations/?page_size=1" | jq '.count'
```

**2. User Access Test:**
- Have users login to target AAP
- Verify they can see their assigned resources
- Test creating/running jobs

**3. Job Template Execution:**
- Run a test job template
- Verify inventory, credentials, and project work
- Check job output

---

## Known Issues & Limitations

### 1. Encrypted Credentials

**Issue:** AAP API returns `$encrypted$` for credential secrets.

**Impact:**
- Credential objects are created in target
- Credential secrets are NOT migrated
- Jobs using these credentials will fail until secrets are added

**Solutions:**

**Option A: HashiCorp Vault (Recommended for production)**
```bash
# Configure Vault in .env
VAULT__URL=https://vault.example.com
VAULT__ROLE_ID=xxxxx
VAULT__SECRET_ID=xxxxx

# Credentials will be fetched from Vault during migration
```

**Option B: Manual Recreation**
1. After migration, edit each credential in target AAP
2. Re-enter passwords, tokens, SSH keys, etc.
3. Save

**Option C: Pre-Migration Export (Advanced)**
```bash
# Before migration, export credentials to Vault
# Then import from Vault during migration
```

---

### 2. RBAC Not Migrated Automatically

**Issue:** User role assignments require separate script.

**Impact:**
- Users created without permissions
- Cannot access resources until RBAC script run

**Solution:** See [RBAC Migration](#rbac-migration) section.

---

### 3. Timeout Errors on Large Operations

**Issue:** Target AAP times out on complex imports (default 60 seconds).

**Symptoms:**
- Job template imports fail
- Inventory imports timeout
- Error: "Read timeout after 60 seconds"

**Solution:**

**1. Increase timeouts in `.env`:**
```bash
SOURCE__TIMEOUT=300
TARGET__TIMEOUT=300
```

**2. Reduce concurrency in `config/config.yaml`:**
```yaml
performance:
  max_concurrent: 5      # Reduce from 20
  rate_limit: 10         # Reduce from 25
  batch_sizes:
    job_templates: 50    # Reduce from 100
    inventories: 100     # Reduce from 200
```

**3. Target AAP Performance:**
- Check target AAP resources (CPU, memory, disk)
- Check AAP logs for slow database queries
- Consider upgrading target AAP resources

---

### 4. Duplicate Host Names

**Issue:** AAP 2.6 enforces stricter hostname uniqueness within inventories.

**Symptoms:**
```
Error: Hostnames must be unique in an inventory. Duplicates found: ['localhost']
```

**Impact:**
- Hosts with duplicate names fail to import
- Bulk host creation fails entire batch

**Solutions:**

**1. Identify duplicates in source:**
```bash
curl -sk -H "Authorization: Bearer $SOURCE__TOKEN" \
  "https://source-aap/api/v2/hosts/" | \
  jq -r '.results[] | "\(.inventory_name) - \(.name)"' | \
  sort | uniq -c | sort -rn | grep -v "1 "
```

**2. Rename duplicates in source AAP before migration:**
- Rename "localhost" to "localhost-1", "localhost-2", etc.
- Or use FQDN hostnames

**3. Accept partial host migration:**
- Non-duplicate hosts will import successfully
- Manually create duplicate hosts with unique names in target

---

### 5. Project Sync Errors During Migration

**Issue:** Projects with SCM sync fail during Phase 3 import.

**Why:** Migration defers SCM details to Phase 2 (controlled batching).

**Impact:**
- Phase 3 import shows errors for projects (expected)
- Projects exist but aren't synced yet

**Solution:**
- This is **normal behavior**
- Projects sync in Phase 2 (controlled batches)
- Wait for Phase 2 to complete
- Or manually sync projects after migration

---

### 6. Schedule Count Mismatch

**Issue:** Fewer schedules in target than source.

**Cause:** Transformation filters out schedules for resources that don't exist.

**Example:**
- Source has schedule for job template ID 15
- Job template 15 doesn't exist in target
- Schedule filtered out during transformation

**Solution:**
1. Ensure parent resources migrate successfully first
2. Re-export and re-import schedules after parent resources exist
3. Or manually create schedules in target

---

### 7. Inventory Source Schedules

**Issue:** Inventory source schedules created as disabled.

**Why:** To prevent automatic syncs before you're ready.

**Impact:**
- Inventory sources won't auto-sync until schedules enabled
- Manual sync works immediately

**Solution:**
```bash
# Enable schedule via API
curl -sk -X PATCH \
  -H "Authorization: Bearer $TARGET__TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' \
  "https://target-aap/api/controller/v2/schedules/SCHEDULE_ID/"
```

---

### 8. Platform Gateway URL Requirement

**Issue:** Target AAP 2.6 requires Platform Gateway URL path.

**Incorrect:**
```bash
TARGET__URL=https://target-aap.example.com/api/v2  # WRONG for AAP 2.6
```

**Correct:**
```bash
TARGET__URL=https://target-aap.example.com/api/controller/v2  # CORRECT
```

**Symptoms if wrong:**
- 404 Not Found errors
- "Invalid URL" errors

---

### 9. Database State Corruption

**Issue:** ID mappings table has NULL target_id values.

**Symptoms:**
- Resume mode skips resources that need importing
- "Resource not found" errors

**Solution:**
```bash
# Check for NULL mappings
sqlite3 migration_state.db "SELECT COUNT(*) FROM id_mappings WHERE target_id IS NULL;"

# Clear NULL mappings
sqlite3 migration_state.db "DELETE FROM id_mappings WHERE target_id IS NULL;"

# Clear migration progress
sqlite3 migration_state.db "DELETE FROM migration_progress;"

# Re-run migration
aap-bridge migrate --skip-prep --force
```

---

## Troubleshooting

### Common Issues

#### Issue: "No such command 'full'"

**Error:**
```
Error: No such command 'full'
```

**Cause:** Using old command syntax.

**Solution:**
```bash
# Don't use:
aap-bridge migrate full --config config/config.yaml

# Use instead:
aap-bridge migrate --config config/config.yaml
```

---

#### Issue: Interactive Prompts Block Migration

**Error:**
```
Schema files already exist. Overwrite? [y/N]:
click.exceptions.Abort
```

**Cause:** Running in non-interactive environment.

**Solution:**
```bash
# Use --force and --skip-prep flags
aap-bridge migrate --skip-prep --force
```

---

#### Issue: "ModuleNotFoundError: No module named 'requests'"

**Error:**
```
ModuleNotFoundError: No module named 'requests'
```

**Cause:** Not in virtual environment.

**Solution:**
```bash
# Activate virtual environment first
source .venv/bin/activate

# Then run command
python rbac_migration.py
```

---

#### Issue: All Resources Showing "0 imported"

**Symptoms:**
```
✓ Successfully imported 0 resources
ℹ Import Summary:
```

**Causes:**
1. Resume mode thinks everything is done
2. ID mappings corrupted

**Solution:**
```bash
# Clear migration state
sqlite3 migration_state.db "DELETE FROM migration_progress WHERE resource_type='hosts';"
sqlite3 migration_state.db "DELETE FROM id_mappings WHERE resource_type='hosts' AND target_id IS NULL;"

# Re-run without resume
aap-bridge import -r hosts --force-reimport
```

---

#### Issue: Connection Errors

**Error:**
```
Error: Failed to connect to source AAP
```

**Checks:**
1. Network connectivity:
   ```bash
   curl -sk https://source-aap.example.com/api/v2/ping/
   ```

2. Token validity:
   ```bash
   curl -sk -H "Authorization: Bearer YOUR_TOKEN" \
     https://source-aap.example.com/api/v2/me/
   ```

3. URL format:
   - Source: `/api/v2/`
   - Target: `/api/controller/v2/` (for AAP 2.6)

---

### Debug Mode

Enable detailed logging:

```bash
# Set log level in .env
LOG_LEVEL=DEBUG

# Or via command line
AAP_BRIDGE_LOG_LEVEL=DEBUG aap-bridge migrate
```

**Log files:**
- `logs/migration.log` - Detailed JSON logs
- Console output - Progress and errors

---

### Getting Help

**1. Check documentation:**
- This guide
- `docs/workflows/RBAC-MIGRATION-GUIDE.md`
- `CLAUDE.md` (developer documentation)

**2. Check logs:**
```bash
# View recent errors
tail -100 logs/migration.log | jq 'select(.level=="error")'

# Search for specific resource
grep "job_templates" logs/migration.log | jq .
```

**3. Check database state:**
```bash
# List all tables
sqlite3 migration_state.db ".tables"

# Check ID mappings
sqlite3 migration_state.db "SELECT * FROM id_mappings WHERE resource_type='projects';"

# Check migration progress
sqlite3 migration_state.db "SELECT * FROM migration_progress;"
```

**4. Report issues:**
- Create GitHub issue in the project repository
- Include: AAP versions, error messages, relevant logs

---

## FAQ

### General

**Q: How long does migration take?**
A: Depends on resource count:
- < 100 resources: 5-10 minutes
- 100-1000: 30-60 minutes
- 1000-10000: 2-6 hours
- 10000+: 6-24+ hours

**Q: Can I migrate from AAP 2.4 RPM to AAP 2.6 containerized?**
A: Yes! This is the most common use case.

**Q: Is it safe to re-run migration?**
A: Yes, the tool is idempotent. It checks what exists and skips duplicates.

**Q: Can I migrate to a non-empty target AAP?**
A: Yes, but:
- Existing resources are skipped
- Name conflicts may cause issues
- Recommended: Start with empty target for cleanest migration

---

### Technical

**Q: What database should I use?**
A: SQLite (default) is fine for most migrations. Use PostgreSQL only if:
- Migrating 100,000+ resources
- Need distributed access
- Running multiple migration instances

**Q: Can I pause and resume migration?**
A: Yes! Press Ctrl+C to stop, then resume with:
```bash
aap-bridge migrate --resume
```

**Q: How do I migrate only specific resources?**
A: Use the `-r` flag:
```bash
aap-bridge migrate -r inventories -r hosts
```

**Q: What if source and target have different organizations?**
A: Use `config/mappings.yaml` to map organization names:
```yaml
organization_mappings:
  "Old Org Name": "New Org Name"
```

**Q: Can I customize field transformations?**
A: Yes, modify transformation logic in `src/aap_migration/migration/transformer.py`.

---

### RBAC

**Q: Why aren't user roles migrated automatically?**
A: RBAC depends on all resources existing first. The separate script ensures resources are in place before assigning roles.

**Q: Can I run RBAC migration multiple times?**
A: Yes! It skips already-assigned roles.

**Q: What if RBAC script fails for some users?**
A:
- Check if required resources exist (projects, inventories, etc.)
- Assign roles manually via UI or API
- Re-run script after fixing issues

---

### Performance

**Q: Migration is too slow. How to speed up?**
A:
1. Increase concurrency in `config/config.yaml`
2. Increase batch sizes
3. Use PostgreSQL instead of SQLite
4. Check target AAP performance

**Q: Getting timeout errors. How to fix?**
A:
1. Increase timeout in `.env` (300 seconds)
2. Reduce concurrency in `config/config.yaml`
3. Reduce batch sizes
4. Check target AAP resources

---

### Data

**Q: Are credentials migrated?**
A: Credential objects yes, secrets no. You must:
- Use HashiCorp Vault integration, OR
- Manually re-enter secrets after migration

**Q: Is job history migrated?**
A: No, only job template configurations. Historical job runs are not migrated.

**Q: Are inventory sources migrated?**
A: Yes! Including SCM configuration and schedules.

**Q: What about custom credential types?**
A: Yes, custom credential types are migrated.

---

## Best Practices

### Pre-Migration

**1. Backup Everything**
```bash
# Backup source AAP (just in case)
# Backup target AAP (before migration starts)
```

**2. Test in Development**
```bash
# Run migration on dev/test instances first
# Verify everything works
# Then migrate production
```

**3. Review Configuration**
```bash
# Check config/config.yaml
# Verify .env settings
# Test API connectivity
```

**4. Document Custom Configurations**
- Note any custom settings in source
- Document credential types
- List critical job templates

---

### During Migration

**1. Monitor Progress**
```bash
# Watch logs
tail -f logs/migration.log

# Check target AAP UI
# Verify resources appearing
```

**2. Don't Interrupt Unless Necessary**
- Migration is resumable but cleaner if not interrupted
- Let phases complete

**3. Check for Errors**
```bash
# During migration, check for errors
grep "ERROR" logs/migration.log
```

---

### Post-Migration

**1. Run Validation**
```bash
aap-bridge validate all --sample-size 1000
```

**2. Run RBAC Migration**
```bash
python rbac_migration.py
```

**3. Test Thoroughly**
- User logins
- Job template execution
- Inventory syncs
- Workflow execution
- Schedules

**4. Update Credentials**
- Re-enter credential secrets
- Test each credential
- Update as needed

**5. Sync Projects**
- Manually sync projects if needed
- Verify SCM connections work
- Check project updates

**6. Enable Schedules**
- Review all schedules
- Enable as appropriate
- Monitor first runs

---

### Production Migration

**1. Plan Downtime**
- Source AAP: Read-only mode during migration
- Target AAP: Not accessible until migration complete
- Estimated downtime: 2x migration time (for safety)

**2. Communication**
- Notify users
- Provide timeline
- Have rollback plan

**3. Cutover**
- Complete migration
- Verify thoroughly
- Update DNS/load balancers to point to target
- Monitor closely

**4. Rollback Plan**
```bash
# If migration fails:
1. Keep source AAP running
2. Point users back to source
3. Investigate issues
4. Fix and retry
```

---

## Support

### Documentation

- **This Guide:** Complete user documentation
- **RBAC Guide:** `docs/workflows/RBAC-MIGRATION-GUIDE.md`
- **Developer Guide:** `CLAUDE.md`
- **API Documentation:** https://docs.ansible.com/automation-controller/

### Getting Help

**1. Check Logs:**
```bash
tail -100 logs/migration.log | jq 'select(.level=="error")'
```

**2. Check Database:**
```bash
sqlite3 migration_state.db "SELECT * FROM migration_progress WHERE status='failed';"
```

**3. GitHub Issues:**
- Search existing issues in the project repository
- Create new issue with:
  - AAP versions (source and target)
  - Error messages
  - Relevant log excerpts
  - Steps to reproduce

### Emergency Contacts

**Critical Production Issues:**
- Contact your AAP support team
- Have source and target AAP details ready
- Provide migration logs

---

## Quick Reference

### Common Commands

```bash
# Full migration
aap-bridge migrate --config config/config.yaml

# Resume failed migration
aap-bridge migrate --resume

# Migrate specific resources
aap-bridge migrate -r inventories -r hosts

# RBAC migration
python rbac_migration.py

# Validation
aap-bridge validate all

# Get help
aap-bridge --help
aap-bridge migrate --help
```

### Key Files

```
.env                        # API tokens and connection settings
config/config.yaml          # Performance and migration settings
migration_state.db          # Migration state database
logs/migration.log          # Detailed logs
rbac_migration.py          # RBAC migration script
```

### Key URLs

```bash
# Source AAP (AAP 2.4)
API: https://source-aap/api/v2/
UI:  https://source-aap/

# Target AAP (AAP 2.6)
API: https://target-aap/api/controller/v2/  # Note: /controller/v2
UI:  https://target-aap/
```

---

**Document Version:** 1.0
**Last Updated:** 2026-03-04
**Migration Tool Version:** 0.1.0

**This guide covers:**
✅ Complete setup and configuration
✅ Step-by-step migration process
✅ RBAC migration
✅ All known issues and solutions
✅ Troubleshooting guide
✅ FAQ and best practices

For technical details and development information, see `CLAUDE.md`.
