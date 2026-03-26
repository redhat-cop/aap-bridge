# Getting Started with AAP Bridge

## What is AAP Bridge?

AAP Bridge is a migration tool that helps you move from Ansible Automation Platform (AAP) 2.4 to AAP 2.6. It handles the complex dependencies between resources and migrates everything in the correct order.

**Supported Migration Path:**
- Source: AAP 2.4+ (RPM-based)
- Target: AAP 2.6+ (containerized)

## Architecture Overview

### How It Works

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│  AAP 2.4    │      │  AAP Bridge  │      │  AAP 2.6    │
│  (Source)   │─────▶│              │─────▶│  (Target)   │
└─────────────┘      └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  SQLite DB   │
                     │ (State Track)│
                     └──────────────┘
```

### Three-Phase Process

1. **Export**: Download resources from source AAP (JSON format)
2. **Transform**: Convert data to AAP 2.6 format and map IDs
3. **Import**: Upload resources to target AAP (with automatic retry)

### Key Features

- **Automatic Dependency Handling**: Migrates in correct order
- **Idempotent**: Safe to re-run, won't create duplicates
- **State Tracking**: SQLite database tracks progress
- **Resumable**: Continue from where you left off after interruption
- **Bulk Operations**: Fast migration using AAP's bulk APIs

## Quick Setup

### 1. Install Dependencies

```bash
# Clone the repository
git clone https://github.com/your-org/aap-bridge.git
cd aap-bridge

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install the tool
pip install -e .
```

### 2. Configure Connection

Create a `.env` file with your AAP credentials:

```bash
# Source AAP 2.4
SOURCE__URL=https://source-aap.example.com/api/v2
SOURCE__TOKEN=your_source_token

# Target AAP 2.6 (IMPORTANT: Use Platform Gateway path)
TARGET__URL=https://target-aap.example.com/api/controller/v2
TARGET__TOKEN=your_target_token

# Database (auto-configured)
MIGRATION_STATE_DB_PATH=sqlite:///./migration_state.db
```

**Critical Note**: Target URL must use `/api/controller/v2` (Platform Gateway), not `/api/v2`.

### 3. Verify Connection

```bash
# Test connectivity
aap-bridge validate connection
```

## Phased Migration Approach

### Why Phased Migration?

Resources in AAP depend on each other. For example:
- Job templates need projects, inventories, and credentials
- Projects need organizations and credentials
- Credentials need credential types and organizations

Migrating in phases ensures dependencies exist before they're referenced.

### Migration Order

```
Phase 1: Foundation (Organizations, Users, Teams)
         ↓
Phase 2: Credentials (Credential Types → Credentials)
         ↓
Phase 3: Infrastructure (Projects, Inventories, Inventory Sources)
         ↓
Phase 4: Hosts
         ↓
Phase 5: Execution Infrastructure (Execution Environments, Instance Groups)
         ↓
Phase 6: Automation (Job Templates, Workflows)
         ↓
Phase 7: Scheduling (Schedules)
         ↓
Phase 8: Configuration (Settings - Optional)
         ↓
Phase 9: Access Control (RBAC - Optional)
```

## Step-by-Step Migration

### Phase 1: Foundation

```bash
# Migrate organizations, users, and teams
aap-bridge migrate -r organizations -r users -r teams --skip-prep

# Verify
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings GROUP BY resource_type;"
```

**Expected Output:**
- Organizations: X migrated
- Users: Y migrated
- Teams: Z migrated

### Phase 2: Credentials (CRITICAL)

```bash
# IMPORTANT: Credential types MUST come before credentials
aap-bridge migrate -r credential_types -r credentials --skip-prep

# Verify
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type IN ('credential_types', 'credentials') GROUP BY resource_type;"
```

**Why this order matters:**
- Credentials reference credential types
- Without credential types migrated first, credential migration will fail

### Phase 3: Infrastructure

```bash
# Migrate projects and inventories
aap-bridge migrate -r projects -r inventories --skip-prep

# Migrate inventory sources (automatically synced after import)
aap-bridge migrate -r inventory_sources --skip-prep
```

**Automatic Sync:**
- Inventory sources are automatically synced after import
- This fetches inventory data from SCM/cloud providers
- No manual sync required

### Phase 4: Hosts

```bash
# Migrate static inventory hosts
aap-bridge migrate -r hosts --skip-prep
```

**Note:** Dynamic inventory hosts are fetched by inventory source syncs (Phase 3).

### Phase 5: Execution Infrastructure

```bash
# Migrate execution environments and instance groups
aap-bridge migrate -r execution_environments --skip-prep
aap-bridge migrate -r instance_groups --skip-prep

# Verify
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type IN ('execution_environments', 'instance_groups') GROUP BY resource_type;"
```

### Phase 6: Automation

```bash
# Migrate job templates
aap-bridge migrate -r job_templates --skip-prep

# Migrate workflow job templates
aap-bridge migrate -r workflow_job_templates --skip-prep

# Verify
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type IN ('job_templates', 'workflow_job_templates') GROUP BY resource_type;"
```

### Phase 7: Schedules

```bash
# Migrate schedules
aap-bridge migrate -r schedules --skip-prep

# Verify
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) FROM id_mappings WHERE resource_type='schedules';"
```

### Phase 8: Settings (Optional)

```bash
# WARNING: Review settings before applying
# Settings include LDAP, logging, UI configuration
aap-bridge migrate -r settings --skip-prep
```

**Important:** Settings are environment-specific. Review before applying to ensure they match your target environment.

### Phase 9: RBAC (Optional)

```bash
# Migrate role-based access control assignments
python rbac_migration.py
```

## Understanding the State Database

The SQLite database tracks migration progress with two tables:

### 1. `id_mappings` - ID Translation
Maps source IDs to target IDs for all resources.

```sql
-- Example query: See all ID mappings
SELECT * FROM id_mappings WHERE resource_type='projects';

-- Example output:
-- source_id | target_id | source_name           | target_name
-- 6         | 235       | Demo Project          | Demo Project
-- 8         | 236       | Web App Deployment    | Web App Deployment
```

### 2. `migration_progress` - Status Tracking
Tracks the status of each resource migration.

```sql
-- Example query: Check migration status
SELECT resource_type, status, COUNT(*) as count
FROM migration_progress
GROUP BY resource_type, status;

-- Example output:
-- resource_type | status    | count
-- projects      | completed | 10
-- credentials   | completed | 57
```

## Key Concepts

### Idempotency

AAP Bridge is **idempotent** - you can safely re-run migrations:

```bash
# First run: Creates 10 projects
aap-bridge migrate -r projects --skip-prep

# Second run: Skips 10 existing projects, creates 0 new ones
aap-bridge migrate -r projects --skip-prep
```

The tool checks the state database before creating resources.

### Resumability

If migration is interrupted:

```bash
# Migration interrupted after 50% complete
^C  # Ctrl+C

# Resume - continues from where it left off
aap-bridge migrate -r projects --skip-prep
```

The state database tracks progress, so you never lose work.

### Dependency Resolution

The tool automatically handles dependencies:

```bash
# Example: Job template references
- Organization (ID mapping: source 1 → target 14)
- Project (ID mapping: source 6 → target 235)
- Inventory (ID mapping: source 8 → target 77)
- Credential (ID mapping: source 11 → target 98)

# Tool automatically looks up target IDs and creates job template
```

## Common Issues and Solutions

### Issue: "Credential type not found"

**Cause:** Migrated credentials before credential types

**Solution:** Migrate in correct order:
```bash
# Wrong order (will fail)
aap-bridge migrate -r credentials --skip-prep
aap-bridge migrate -r credential_types --skip-prep

# Correct order (will succeed)
aap-bridge migrate -r credential_types --skip-prep
aap-bridge migrate -r credentials --skip-prep
```

### Issue: "Organization not found"

**Cause:** Migrated resources before organizations

**Solution:** Always migrate organizations first (Phase 1)

### Issue: Inventory sources not synced

**Cause:** None - inventory sources are automatically synced

**Verification:**
```bash
# Check sync status
sqlite3 migration_state.db "SELECT source_id, target_id FROM id_mappings WHERE resource_type='inventory_sources';"

# Verify in AAP Web UI:
# Resources → Inventories → [Select Inventory] → Sources → Check sync status
```

## Performance Tuning

### Adjust Batch Sizes

Edit `config/config.yaml`:

```yaml
performance:
  max_concurrent: 10        # Concurrent API requests
  batch_size: 100          # Items per batch (most resources)
  host_batch_size: 200     # Hosts per batch (AAP maximum)
  inventory_batch_size: 200 # Inventories per batch
```

### Use PostgreSQL for Large Migrations

For 100,000+ resources, use PostgreSQL instead of SQLite:

```bash
# Install PostgreSQL (separate from AAP's database)
# Update .env
MIGRATION_STATE_DB_PATH=postgresql://user:pass@localhost:5432/aap_migration
```

## Verification

### Check Migration Status

```bash
# View all migrated resources
sqlite3 migration_state.db "SELECT resource_type, COUNT(*) as total FROM id_mappings WHERE target_id IS NOT NULL GROUP BY resource_type ORDER BY resource_type;"
```

### Validate Resources

```bash
# Validate all resources
aap-bridge validate all --sample-size 100

# Validate specific resource types
aap-bridge validate projects inventories
```

### Generate Report

```bash
# Create migration summary report
aap-bridge report summary
```

## Next Steps

1. **Test in Non-Production**: Always test migration in a staging environment first
2. **Review Credentials**: Use the credential migration tool for encrypted credentials
3. **Verify RBAC**: Check that role assignments match expected permissions
4. **Test Job Runs**: Execute a few job templates to verify functionality
5. **Monitor Schedules**: Ensure schedules trigger at expected times

## Getting Help

- **Documentation**: See full README.md for detailed information
- **Issues**: Report bugs at https://github.com/anthropics/claude-code/issues
- **Logs**: Check `logs/aap_migration_*.log` for detailed error messages

## Quick Reference

### Essential Commands

```bash
# Check what will be migrated (dry run)
aap-bridge migrate -r projects --dry-run

# Migrate with automatic yes to prompts
printf "y\ny\n" | aap-bridge migrate -r projects --skip-prep

# Clear progress to re-export/re-import
aap-bridge state clear --resource-type projects

# View migration state
sqlite3 migration_state.db "SELECT * FROM id_mappings WHERE resource_type='projects';"

# Reset target IDs (preserves source mappings)
aap-bridge state reset-target-ids --resource-type projects
```

### Migration Checklist

- [ ] Phase 1: Organizations, Users, Teams
- [ ] Phase 2: Credential Types, Credentials
- [ ] Phase 3: Projects, Inventories, Inventory Sources
- [ ] Phase 4: Hosts
- [ ] Phase 5: Execution Environments, Instance Groups
- [ ] Phase 6: Job Templates, Workflow Job Templates
- [ ] Phase 7: Schedules
- [ ] Phase 8: Settings (Optional)
- [ ] Phase 9: RBAC (Optional)
- [ ] Validation and Testing

## Summary

AAP Bridge makes AAP 2.4 → 2.6 migration straightforward:

1. **Export** data from source AAP
2. **Transform** to AAP 2.6 format
3. **Import** to target AAP
4. **Verify** migration success

The phased approach handles dependencies automatically, and the state database ensures migrations are safe, idempotent, and resumable.

Happy migrating!
