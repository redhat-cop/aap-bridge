# Changelog

All notable changes to AAP Bridge are documented here.

For the complete changelog, see
[CHANGELOG.md](https://github.com/redhat-cop/aap-bridge/blob/main/CHANGELOG.md)
in the repository.

## Version History

### Unreleased (since v0.1.0)

**New Features:**

- AAP 2.7 supported as a migration source and target
- Source version support expanded to AAP 1.0 through 2.7 (sources) and AAP 2.6 and 2.7 (targets)
- Survey spec migration for job templates and workflow job templates
- Notification template association migration (started/success/error/approvals)
- Nested inventory group hierarchy export and import
- Host-to-group associations applied after bulk import
- Constructed inventory `input_inventories` exported and re-linked on target
- Automatic inventory source sync after import (with configurable timeout/polling)
- Smart inventory import deferred until after inventory source sync
- Classic RBAC migration for user and team resource role grants to the target AAP 2.5+ RBAC model
- For AAP 2.5+ sources, new-model RBAC migration is fully implemented and functional for
  `role_definitions`, `role_user_assignments`, and `role_team_assignments`
- Version-driven API routing: host-only URLs with required `SOURCE__VERSION` /
  `TARGET__VERSION` select legacy or gateway + controller API bases
- `role_definitions` included in cleanup phase
- `skip_credential_names` configuration option (defaults exclude installer-created credentials)
- `skip_execution_environment_names` configuration option (defaults exclude platform-managed EEs)
- MkDocs GitHub Actions deployment workflow

**Improvements:**

- Export and transform phase order now matches the import dependency order (credential
  types and credentials before projects; users and teams after all content objects).
  Export progress display reflects this order even with parallel export enabled.

**Bug Fixes:**

- Credential deduplication: same-name/different-type and non-unique name+org+type cases
  handled correctly
- Batch precheck scoping fixed for org-scoped, parent-scoped, notification template, and
  schedule resources
- Project sync failure detection with retry and configurable abort
- System-job schedules excluded from export/import/cleanup
- Managed credential types matched by namespace when name differs between versions
- User team memberships exported and re-applied on import
- Vault configuration is now optional
- Cleanup: inventory sources excluded, job history preserved, groups/hosts skipped
- Managed execution environments always protected from deletion (including in `--full` mode)
- Import dispatch table corrected for `notification_templates`, `credential_input_sources`,
  `rbac`, and `workflow_job_templates`
- Instance group RBAC API exception handling is now scoped to AAP 2.5+ sources only
- 400 "pending deletion" responses treated as idempotent skips
- Credential type reruns now map "already exists" conflicts and mark completed state
- Host bulk import reruns now skip already-mapped hosts and persist host progress state
- Gateway RBAC routing for 2.5+ sources (dual-base role definitions/assignments,
  `shared.*` content types, target `_api_base` remapping)
- Gateway RBAC assignment dedupe and principal resolution when gateway and
  controller APIs use different surrogate IDs for the same user, team, or assignment
- Legacy source RBAC (1.0–2.4) converted to role assignments on AAP 2.6 targets
- Role definitions export via parallel path on AAP 2.5+ sources
- Team member sync when team create is skipped on rerun
- Config path resolution when running from a subdirectory

### v0.1.0

Initial release of AAP Bridge.

**Features:**

- Full ETL pipeline for AAP migration
- Bulk operations support for hosts
- PostgreSQL-backed state management
- Checkpoint/resume capability
- Rich progress display
- Split-file export/import for large datasets
- Interactive CLI menu

**Supported Resources:**

- Organizations
- Labels
- Users
- Teams
- Credential Types
- Credentials
- Credential Input Sources
- Execution Environments
- Inventories
- Inventory Sources
- Inventory Groups
- Hosts
- Projects
- Notification Templates
- Job Templates
- Workflow Job Templates
- System Job Templates
- Schedules
- Role Definitions
- User Role Assignments
- Team Role Assignments

**Known Limitations:**

- Encrypted credentials cannot be migrated via API (use HashiCorp Vault or manual entry)
- Workflow approval nodes require manual review after migration

---

## Versioning

AAP Bridge follows [Semantic Versioning](https://semver.org/):

- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality (backwards compatible)
- **PATCH**: Bug fixes (backwards compatible)

## Upgrade Notes

When upgrading AAP Bridge:

1. Review the changelog for breaking changes
2. Backup your state database
3. Test in a staging environment first
4. Update configuration if needed
