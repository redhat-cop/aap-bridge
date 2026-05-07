# Filtering and Skipping Logic

This document explains why resource counts in the target environment may be lower than the source. AAP Bridge applies various filters and skip conditions across different phases to ensure a clean, consistent migration.

## Overview

Resources can be filtered or skipped for several reasons:

- **Intentional exclusion**: Dynamic hosts, smart inventories, installer-created default credentials, and disabled schedules are excluded by design
- **Dependency validation**: Resources with missing dependencies cannot be migrated
- **Idempotency**: Already-migrated resources are skipped to prevent duplicates
- **System constraints**: Some resources are read-only or non-deletable

---

## Export Phase Filters

The export phase applies API-level filters to exclude resources that shouldn't be migrated.

### Configurable Filters

These filters are controlled via `config.yaml` under the `export:` section:

| Setting | Default | Resource Type | Effect |
|---------|---------|---------------|--------|
| `skip_dynamic_hosts` | `true` | Hosts | Excludes hosts managed by inventory sources. These hosts are recreated automatically when the inventory source syncs on the target. |
| `skip_smart_inventories` | `true` | Inventories | Excludes smart inventories (computed inventories). Only static inventories are exported. |
| `skip_pending_deletion_inventories` | `true` | Inventories | Excludes inventories marked for deletion in the source. |
| `skip_hosts_with_inventory_sources` | `true` | Hosts | Same as `skip_dynamic_hosts` - excludes hosts with `has_inventory_sources=true`. |
| `skip_credential_names` | `["Ansible Galaxy", "Default Execution Environment Registry Credential"]` | Credentials | Excludes installer-created default credentials by name (case-insensitive). The target installer recreates these automatically. Use `[]` to migrate all credentials. |

**Example configuration:**

```yaml
export:
  skip_dynamic_hosts: true
  skip_smart_inventories: true
  skip_pending_deletion_inventories: true
  # Remove entries or use [] to migrate these credentials
  skip_credential_names:
    - Ansible Galaxy
    - Default Execution Environment Registry Credential
```

### Built-in Filters (Not Configurable)

| Resource Type | Filter | Reason |
|---------------|--------|--------|
| Schedules | `enabled=true` | Only enabled schedules are exported. Disabled schedules are excluded at the API level. |
| Credential Types | All exported | Both managed (built-in) and custom types are exported for mapping purposes. |

!!! note "Dynamic Hosts"
    Hosts managed by inventory sources (EC2, VMware, etc.) are excluded because they will be automatically recreated when the inventory source syncs on the target controller.

---

## Transform Phase Filters

The transform phase validates dependencies and skips resources that cannot be properly migrated.

### Dependency-Based Skips

Resources are skipped if their **required** dependencies weren't exported or don't exist:

| Resource Type | Required Dependencies | Skip Condition |
|---------------|----------------------|----------------|
| Inventories | `organization` | Organization not in export |
| Credentials | `organization`, `credential_type` | Missing org or type |
| Job Templates | `organization`, `project` | Missing org or project |
| Workflow Job Templates | `organization` | Missing organization |
| Projects | `organization` | Missing organization |
| Hosts | `inventory` | Inventory not exported (e.g., pending deletion) |
| Inventory Groups | `inventory` | Inventory not exported |
| Inventory Sources | `inventory` | Inventory not exported |
| Labels | `organization` | Missing organization |
| Execution Environments | `organization` | Missing organization |
| Schedules | `unified_job_template` | Referenced job template/workflow not exported |

### External Credential Types

Credentials using external credential types (custom types from the source) are skipped if the credential type cannot be mapped to the target environment.

**Log message:** `skipping_credential_external_type_unmapped`

---

## Import Phase Filters

The import phase handles idempotency and conflict resolution.

### Already Migrated (Idempotent)

Resources that have already been successfully migrated are skipped:

- The state database tracks `source_id → target_id` mappings
- On subsequent runs, migrated resources are skipped
- **Stats:** Increments `skipped_count`

### Managed Resources

Built-in (managed) resources in AAP cannot be created or fully modified:

| Resource Type | Behavior |
|---------------|----------|
| Credential Types | Built-in types are mapped by name, not created. Only `organization` field is PATCHed. |
| Credentials | Managed credentials skip PATCH operations entirely. Only ID mapping is saved. |
| System Job Templates | Read-only; exported for reference but cannot be modified. |

### Conflict Resolution

When a resource with the same name already exists on the target:

1. **Identical resource**: Skip (already migrated)
2. **Different resource**: Update existing resource with source data

---

## Cleanup Phase Filters

The cleanup command excludes certain resources that cannot be deleted.

### Non-Deletable Resources

| Resource Type | Reason |
|---------------|--------|
| Labels | API returns 405 Method Not Allowed |
| System Job Templates | Built-in, cannot be deleted |

### Excluded Endpoint Categories

| Category | Examples | Reason |
|----------|----------|--------|
| Read-Only | ping, config, dashboard, metrics | No DELETE operation |
| Runtime Data | jobs, workflow_jobs, project_updates | Historical/transient data |
| Manual Migration | settings, roles | Require manual intervention |

---

## Quick Reference: Common Skip Reasons

| Phase | Reason | Configurable? | How to Identify |
|-------|--------|---------------|-----------------|
| Export | Dynamic hosts (inventory source managed) | Yes | Check `skip_dynamic_hosts` setting |
| Export | Smart/pending deletion inventories | Yes | Check `skip_smart_inventories` setting |
| Export | Installer-created default credentials | Yes | Check `skip_credential_names` setting |
| Export | Disabled schedules | No | Only enabled schedules are exported |
| Transform | Missing organization | No | Check export logs for organization |
| Transform | Missing credential type | No | Ensure credential types exported first |
| Transform | Unmapped external credential type | No | Custom credential types need manual setup |
| Transform | Missing inventory | No | Inventory may have been pending deletion |
| Transform | Missing job template for schedule | No | Referenced template not exported |
| Import | Already migrated | No | Check state database for mapping |
| Import | Managed/built-in resource | No | These are mapped, not created |
| Cleanup | Non-deletable resource | No | Labels, system job templates |

---

## Understanding Count Differences

When comparing source and target counts, consider:

### Expected Differences

1. **Hosts**: If `skip_dynamic_hosts=true` (default), dynamic hosts won't be counted
2. **Inventories**: Smart inventories and pending deletion inventories are excluded
3. **Schedules**: Disabled schedules are not exported
4. **Credentials**: Installer-created defaults (`Ansible Galaxy`, `Default Execution Environment Registry Credential`) are skipped by default; others may be skipped due to unmapped external types

### Investigating Discrepancies

1. **Check export logs** for `skipped` entries:
   ```bash
   grep "skipped" logs/migration.log | jq '.resource_type, .reason'
   ```

2. **Check transform logs** for dependency failures:
   ```bash
   grep "required_dependency_missing" logs/migration.log
   ```

3. **Review configuration** in `config.yaml`:
   ```yaml
   export:
     skip_dynamic_hosts: true      # Are dynamic hosts being skipped?
     skip_smart_inventories: true  # Are smart inventories being skipped?
   ```

4. **Check state database** for import status:
   ```bash
   aap-bridge status --resource-type hosts
   ```

---

## Adjusting Filter Behavior

To include resources that are filtered by default:

```yaml
# config.yaml
export:
  # Include dynamic hosts (will be overwritten when inventory source syncs)
  skip_dynamic_hosts: false

  # Include smart inventories (may not work correctly on target)
  skip_smart_inventories: false

  # Include inventories pending deletion
  skip_pending_deletion_inventories: false

  # Include installer-created default credentials (normally recreated by the target installer)
  skip_credential_names: []
```

!!! warning "Changing Defaults"
    The default filters exist for good reasons. Dynamic hosts will be recreated (and potentially duplicated) when inventory sources sync. Smart inventories may not function correctly if their source inventories differ.
