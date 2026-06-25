# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic
Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Source Version Support**: AAP 1.0, 1.1, 1.2, 2.0, 2.1, 2.2, 2.5, and 2.6 are now
  supported as migration sources in addition to the original 2.3/2.4/2.5 paths
- **Survey Spec Migration**: Job template and workflow job template survey specs are now
  exported via `GET …/{id}/survey_spec/` and imported via `POST …/{id}/survey_spec/`
- **Notification Template Associations**: Notification template relationships for job
  templates (started/success/error) and workflow job templates (including approvals) are
  now exported and imported as part of the template migration
- **Nested Group Hierarchies**: Inventory group parent-child relationships are now fully
  exported and recreated on the target
- **Host-Group Associations**: Hosts are associated with their groups after bulk import
  rather than being left unattached
- **Constructed Inventory `input_inventories`**: The list of member inventories for
  constructed inventories is now exported and re-linked on the target
- **Inventory Source Auto-Sync**: After importing inventory sources the tool automatically
  triggers a sync and waits for completion before proceeding to constructed inventories
  and smart inventories, ensuring those depend on fresh host data
- **Classic RBAC Migration (Users)**: Direct user resource role grants are exported from
  `GET /users/{id}/roles/` and applied on the target AAP 2.5+ RBAC model
- **Classic RBAC Migration (Teams)**: Team resource role grants are exported from
  `GET /teams/{id}/roles/` and applied on the target AAP 2.5+ RBAC model
- **AAP 2.5+ RBAC Fully Implemented (2.5+ Sources)**: New-model RBAC resources are
  fully migrated and functional for AAP 2.5+ sources, including `role_definitions`,
  `role_user_assignments`, and `role_team_assignments`
- **`role_definitions` Cleanup**: Custom role definitions are now deleted during the
  cleanup phase; system-managed roles that return 400 are gracefully skipped
- **`skip_credential_names` Configuration**: New `export.skip_credential_names` option
  (defaults to `["Ansible Galaxy", "Default Execution Environment Registry Credential"]`)
  excludes installer-created credentials from export, import, and cleanup — the same
  pattern as `skip_execution_environment_names`
- **`skip_execution_environment_names` Configuration**: New
  `export.skip_execution_environment_names` option (defaults to the platform-managed EE names)
  excludes default execution environments from export, import, and cleanup
- **Configurable Inventory Source Sync**: New performance settings control the sync
  timeout, polling interval, concurrency, and failure behaviour for post-import
  inventory source updates
- **CI/CD Docs Workflow**: GitHub Actions workflow added to publish MkDocs documentation
  via `gh-deploy` on push to `main`
- **AAP Token Retrieval Docs**: `curl` commands with `jq` for retrieving API tokens from
  AAP 2.4 and earlier (`/api/v2/tokens/`) and AAP 2.5+ (`/api/gateway/v1/tokens/`) are
  now documented

### Changed

- **Export and Transform Order Aligned with Import**: Resource types are now exported
  and transformed in the same dependency order as the import phase (credential types and
  credentials before projects; users and teams deferred until after all content objects
  are in place). The export progress display reflects this order even when parallel
  export is enabled.
- **All Migration Paths Marked Fully Supported**: The 2.3 → 2.6, 2.4 → 2.6, and
  2.5 → 2.6 paths are all now marked as fully supported; messaging is standardised
- **`inventory_sources` Re-ordered**: Inventory sources are now imported before
  constructed inventories and smart inventories to satisfy sync dependencies
- **Smart Inventories Deferred**: Smart inventory import is now a dedicated phase that
  runs after inventory source sync completes, preventing membership lookup failures
- **Users and Teams Phase Re-ordered**: Users and teams are now processed in phase 2
  (immediately before `role_definitions`) so that job templates, workflows, and
  inventories are already mapped when role grants are applied
- **Error Output Simplified**: Console error output no longer renders full Rich
  tracebacks with local variable dumps; errors render as a single summary line
- **Version-Driven API Routing**: `SOURCE__URL` and `TARGET__URL` are host-only
  (`https://fqdn`); required `SOURCE__VERSION` and `TARGET__VERSION` select legacy
  (`/api/v2/`) or gateway + controller (`/api/gateway/v1/`, `/api/controller/v2/`)
  API bases. Path suffixes embedded in configured URLs are stripped automatically
- **Documentation – Token and URL Guidance**: Clarified read-only source vs
  read/write target API tokens, version-driven API routing, and corrected
  `SECURITY.md` to use `SOURCE__TOKEN`/`TARGET__TOKEN`

### Fixed

- **Credentials – Same-Name Different Types**: Credentials sharing a name but with
  different credential types were silently collapsed to one entry; the precheck and
  importer now key on `(name, credential_type)` so both survive
- **Credentials – Non-Unique Name/Org/Type**: Sources that contain multiple credentials
  with an identical `(name, org, credential_type)` composite key are handled by always
  CREATing a new credential; idempotency is guaranteed by `MigrationProgress` rather
  than name matching
- **Credentials – Duplicate Key on Import (400)**: When the target returns a 400
  "duplicate key / already exists" error during credential import, the duplicate is
  renamed to `<name> [src:<source_id>]` and retried so every source credential gets
  its own distinct target entry; previous behaviour mapped all duplicates to a single
  target credential, breaking downstream dependency resolution
- **Precheck – Org-Scoped Resource Collisions**: Resources such as projects,
  inventories, and job templates that share a name across different organizations were
  silently deduplicated during the batch precheck; they are now keyed on
  `(name, org_id)` so all entries are preserved
- **Precheck – Parent-Scoped Resources**: Inventory sources, hosts, and groups that
  share a name across different inventories were treated as globally unique; the
  precheck now keys them on `(name, source_parent_id)` and resolves the parent ID
  mapping before the existence check
- **Precheck – Notification Templates and Schedules Scoping**: Both resource types were
  treated as globally unique, causing same-name entries in different parent scopes to
  be dropped; notification templates are now org-scoped and schedules are keyed by
  `(name, unified_job_template)`
- **Project Sync – Failure Detection**: Project SCM sync failures are now detected,
  automatically retried up to `project_sync_max_retries` times, and the run is aborted
  if the failure persists (configurable via `project_sync_fail_on_sync_failure`)
- **Schedules – System-Job Schedules Excluded**: `system_job` type schedules are now
  skipped during export, import, and cleanup to avoid 400 errors on the target
- **Credential Types – Namespace Fallback**: Built-in credential types that were renamed
  between AAP versions (e.g. the CyberArk lookup type) are now matched by stable
  `namespace` when the name lookup fails, preventing spurious 404 errors
- **User Team Memberships**: User-to-team memberships are now exported via
  `users/<id>/teams/` and re-applied on import; a post-teams resync step ensures
  membership is consistent even when users were imported before teams
- **Vault Configuration Optional**: The `vault:` block in `config.yaml` is now
  entirely optional; omitting it no longer raises a validation error at startup
- **Cleanup – Inventory Sources Excluded**: Inventory sources are no longer deleted
  during cleanup (they are managed by the parent inventory)
- **Cleanup – Preserve Job History**: The cleanup status filter query is fixed so that
  running jobs are correctly cancelled and historical job records are preserved
- **Cleanup – Groups and Hosts Excluded**: Groups and hosts are skipped during the
  cleanup phase; they are removed when their parent inventory is deleted
- **Cleanup – Execution Environments Always Protected**: Managed EEs (e.g. Control
  Plane Execution Environment) are now protected from deletion in `--full` mode as well
  as the default mode; previously the `is_managed` guard only applied outside `--full`
- **Cleanup – False Warning for Cascade-Deleted Phases**: The spurious warning for
  phases that were already removed by cascade deletion is suppressed in the cleanup TUI
- **Import – `notification_templates`, `credential_input_sources`, `rbac` Dispatch**:
  These resource types were unreachable in the CLI method map and were silently skipped;
  the dispatch table is corrected so all three are importable
- **Import – Workflow Job Templates Dispatch**: `workflow_job_templates` was not
  dispatching to `WorkflowImporter`; fixed so the importer is always called
- **Client – 400 Pending Deletion Treated as Idempotent**: A `400` response indicating
  that a resource is pending deletion is now treated as a skip rather than an error
- **Instance Groups Exception Scoped to 2.5+**: The instance groups API exception
  handling that was applied to all source versions is now scoped to AAP 2.5+ only
- **Credential Types – Rerun Idempotency**: Phase 1 reruns now treat "already exists"
  create responses as a skip by resolving the existing credential type, saving the ID
  mapping, and marking migration progress as completed
- **Hosts – Bulk Import Rerun Idempotency**: Phase 2 reruns now skip hosts that already
  have state mappings and persist host migration progress during bulk import so
  subsequent runs do not attempt duplicate host creates
- **RBAC – Gateway Topology (2.5+ Sources)**: Role assignments and custom role
  definitions route to the correct gateway vs controller API; platform assignments
  honour `shared.*` content types; dual-base export/import for `role_definitions`
  and role assignments; `_api_base` from export is remapped to the target host on
  import
- **RBAC – Gateway Assignment Dedupe and Principal Resolution**: Role assignment
  export no longer duplicates records listed on both gateway and controller APIs;
  dedupe keeps the copy from the API surface where each assignment is created
  (`shared.*` → gateway, `awx.*` → controller). Import resolves users and teams by
  username/name when surrogate principal IDs differ between APIs, and custom role
  definitions are looked up on the controller for `awx.*` assignments
- **RBAC – Legacy Sources (1.0–2.4 → 2.6)**: Classic `users/{id}/roles/` and
  `teams/{id}/roles/` grants are converted to `role_user_assignments` and
  `role_team_assignments` on gateway targets instead of being skipped
- **Role Definitions Export**: Custom roles on the controller API are included when
  export uses the parallel code path (previously reported a non-zero count but
  wrote no files on AAP 2.5+ sources)
- **Team Membership on Rerun**: Member sync runs when a team import is skipped but
  the team already has a target ID mapping
- **Config Path Resolution**: `config/config.yaml` is resolved relative to the
  repository root when the CLI or TUI is started from a subdirectory

## [0.1.0] - 2025-12-05

### Added

- Initial release of AAP Bridge
- **Migration Framework**
  - ETL pipeline for source-to-target AAP migrations
  - Support for all major AAP resource types: organizations, users, teams,
    credentials, credential types, execution environments, projects,
    inventories, inventory sources, inventory groups, hosts, job templates,
    workflow job templates, notification templates, and schedules
  - RBAC role assignment migration
  - Bulk API operations for high-performance host and inventory imports
- **State Management**
  - PostgreSQL-backed state tracking with checkpoint/resume capability
  - ID mapping persistence for cross-system resource references
  - Idempotent operations to prevent duplicate creation
- **Export/Import Operations**
  - Split-file export for large datasets (configurable records per file)
  - Automatic file discovery and ordered import
  - Metadata tracking for export sessions
- **Validation**
  - Statistical sampling validation (configurable confidence level and margin of
    error)
  - Count reconciliation between source and target
  - Phase-by-phase validation support
- **CLI Interface**
  - `aap-bridge` - Single command with a menu-driven interface
  - `aap-bridge migrate` - Full migration with phase control
  - `aap-bridge export` - Export resources from source AAP
  - `aap-bridge import` - Import resources to target AAP
  - `aap-bridge validate` - Validate migration completeness
  - `aap-bridge state` - View and manage migration state
  - `aap-bridge cleanup` - Clean up target resources or local data
- **Progress Display**
  - Rich-based live progress display with real-time metrics
  - Multiple output modes: normal, quiet, CI/CD, and detailed
  - Rate tracking, success/failure counts, and timing information
- **Logging**
  - Structured logging with structlog
  - Separate console (human-readable) and file (JSON) output
  - Automatic sensitive data redaction
  - Configurable log levels for console and file
- **Configuration**
  - YAML-based configuration with environment variable substitution
  - Resource renaming via mappings.yaml (e.g., credential type name changes
    between versions)
  - Endpoint filtering via ignored_endpoints.yaml
  - Extensive performance tuning options

### Security

- Automatic redaction of sensitive fields in logs (tokens, passwords, SSH keys)
- Environment variable support for all credentials
- No hardcoded secrets in configuration files

[Unreleased]: https://github.com/redhat-cop/aap-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/redhat-cop/aap-bridge/releases/tag/v0.1.0
