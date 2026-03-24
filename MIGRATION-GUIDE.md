# AAP Migration Guide - Complete Workflow

## ✅ Recommended Approach: Use the Automated Script

The **easiest and most reliable** way to migrate is using the provided script:

```bash
./migrate-complete.sh
```

This script automates all 5 steps and provides a complete migration with progress tracking and error handling.

---

## Manual Step-by-Step Migration

If you prefer to run each step manually or need to troubleshoot:

### Prerequisites
```bash
# Activate virtual environment
source .venv/bin/activate

# Clean previous migration data (optional, for fresh start)
rm -rf exports xformed migration_state.db
```

### Step 1: Export Data from Source AAP
```bash
aap-bridge export --force --yes
```

**What it does:** Exports all resources from your source AAP 2.3/2.4 instance to `exports/` directory.

**Duration:** ~1-2 minutes

---

### Step 2: Transform Data for AAP 2.6 Compatibility
```bash
aap-bridge transform --force
```

**What it does:** Converts exported data to AAP 2.6 format, removing deprecated fields and updating schemas.

**Duration:** ~30 seconds

---

### Step 3: Import Phase 1 (Infrastructure & Projects)
```bash
aap-bridge import --yes --phase phase1
```

**What it imports:**
- Organizations
- Users
- Teams
- Credential Types
- Credentials
- Execution Environments
- Inventories
- Inventory Sources
- Inventory Groups
- Hosts
- Instances
- Instance Groups
- Projects

**Duration:** ~40 seconds

---

### Step 4: Patch Projects with SCM Details
```bash
aap-bridge patch-projects
```

**What it does:** Activates SCM synchronization for projects that were imported with deferred SCM details.

**Duration:** ~20 seconds

---

### Step 5: Import Phase 3 (Automation Definitions)
```bash
aap-bridge import --yes \
    --resource-type job_templates \
    --resource-type workflow_job_templates \
    --resource-type schedules \
    --resource-type notification_templates
```

**What it imports:**
- Job Templates
- Workflow Job Templates (if importer available)
- Schedules
- Notification Templates

**Duration:** ~30 seconds

---

## Verification

### Check Migration Status
```bash
sqlite3 migration_state.db "
SELECT
    resource_type,
    COUNT(*) as total,
    SUM(CASE WHEN target_id IS NOT NULL THEN 1 ELSE 0 END) as imported,
    SUM(CASE WHEN target_id IS NULL THEN 1 ELSE 0 END) as failed
FROM id_mappings
GROUP BY resource_type
ORDER BY resource_type;
"
```

### Expected Results
| Resource Type | Typical Import Rate |
|--------------|---------------------|
| Organizations | 100% |
| Users | 100% |
| Teams | 100% |
| Credentials | 95-100% |
| Projects | 50-100% (some may fail due to SCM issues) |
| Job Templates | 20-50% (many fail due to missing dependencies) |
| **Schedules** | **100%** (key metric for Phase 3 success) |

---

## Troubleshooting

### Issue: Job Templates Fail to Import

**Cause:** Missing project dependencies. If projects fail to import, job templates that depend on them will also fail.

**Solution:**
1. Check which projects failed: `sqlite3 migration_state.db "SELECT * FROM id_mappings WHERE resource_type='projects' AND target_id IS NULL;"`
2. Manually create or fix those projects in the target AAP
3. Re-run Phase 3 import

### Issue: Migration Hangs

**Cause:** Using the `migrate --phase all` command has a known issue with Phase 3.

**Solution:** Use the **automated script** (`./migrate-complete.sh`) or manual step-by-step approach instead.

### Issue: Credentials Fail to Import

**Cause:** Credential type dependencies missing or organization ownership issues.

**Solution:**
1. Ensure all credential types are imported first
2. Check credential ownership (must have organization, user, or team)
3. Review credential mappings in `config/mappings.yaml`

---

## Performance

**Total Migration Time:** ~2-3 minutes for typical AAP installation

| Phase | Duration |
|-------|----------|
| Export | 1-2 min |
| Transform | 30 sec |
| Phase 1 Import | 40 sec |
| Project Patching | 20 sec |
| Phase 3 Import | 30 sec |

---

## Known Limitations

1. **Workflow Job Templates:** No importer currently available (skipped)
2. **System Job Templates:** No importer currently available (skipped)
3. **Jobs History:** Not migrated (only definitions)
4. **Some Projects:** May fail if SCM credentials are invalid or repos unreachable

---

## Success Criteria

A successful migration should have:
- ✅ Organizations: 100% imported
- ✅ Users: 100% imported
- ✅ Credentials: >95% imported
- ✅ **Schedules: 100% imported** (key indicator Phase 3 works)
- ⚠️  Job Templates: >20% imported (failures expected due to dependencies)

---

## Support

For issues or questions:
1. Check the migration log files in the current directory
2. Review the database: `migration_state.db`
3. Check exported data: `exports/` and `xformed/` directories
4. Report issues at: https://github.com/anthropics/claude-code/issues

---

**Last Updated:** 2026-03-24
**Script Version:** 1.0
