# Resource Support Matrix (AAP 2.3 → 2.6)

This document lists all resources supported by the AAP Bridge migration tool, their
classification, and any caveats associated with their migration.

## Migration Categories

- **Migrate**: Business resources with durable value that are recreated on the target AAP 2.6
  instance.
- **Export-Only**: Resources exported from the source for audit, reporting, or analysis
  purposes, but **not recreated** on the target.
- **Never Migrate**: Endpoints intentionally excluded from both export and import (read-only,
  runtime data, or operational endpoints).

## Support Matrix

| Canonical Name | API Endpoint | Category | Aliases | Caveats / Reason |
|:---|:---|:---|:---|:---|
| `organizations` | `organizations/` | Migrate | - | Foundation resource |
| `labels` | `labels/` | Migrate | - | - |
| `credential_types` | `credential_types/` | Migrate | - | - |
| `credentials` | `credentials/` | Migrate | - | Encrypted values require Vault for migration |
| `credential_input_sources` | `credential_input_sources/` | Migrate | - | - |
| `execution_environments` | `execution_environments/` | Migrate | - | - |
| `projects` | `projects/` | Migrate | - | - |
| `inventory` | `inventories/` | Migrate | `inventories` | Canonical name aligns with API root |
| `inventory_sources` | `inventory_sources/` | Migrate | - | - |
| `constructed_inventories` | `constructed_inventories/` | Migrate | `constructed_inventory` | Transitional canonical name |
| `groups` | `groups/` | Migrate | `inventory_groups` | Canonical name aligns with API root |
| `hosts` | `hosts/` | Migrate | - | Uses Bulk API for high performance |
| `notification_templates` | `notification_templates/` | Migrate | - | - |
| `job_templates` | `job_templates/` | Migrate | - | - |
| `workflow_job_templates` | `workflow_job_templates/` | Migrate | - | Nodes handled as embedded sub-resources |
| `system_job_templates` | `system_job_templates/` | Migrate | - | Target-side mapping only, not created |
| `schedules` | `schedules/` | Migrate | - | - |
| `users` | `users/` | Migrate | - | Passwords are not migrated |
| `teams` | `teams/` | Migrate | - | - |
| `role_definitions` | `role_definitions/` | Migrate | - | Custom roles on 2.5+ sources; legacy sources use classic grants on users/teams |
| `role_user_assignments` | `role_user_assignments/` | Migrate | - | 2.5+ sources; legacy sources via classic grant conversion |
| `role_team_assignments` | `role_team_assignments/` | Migrate | - | 2.5+ sources; legacy sources via classic grant conversion |
| `jobs` | `jobs/` | Export-Only | - | Historical runtime data, not imported |
| `activity_stream` | `activity_stream/` | Never Migrate | - | Audit log, historical (auto-generated on target) |
| `ad_hoc_commands` | `ad_hoc_commands/` | Never Migrate | - | Ad-hoc command records (historical) |
| `analytics` | `analytics/` | Never Migrate | - | Analytics data, read-only (2.6 only) |
| `applications` | `applications/` | Never Migrate | - | OAuth applications, deferred from current phase |
| `bulk` | `bulk/` | Never Migrate | - | Bulk API operational endpoint, not a resource |
| `config` | `config/` | Never Migrate | - | System configuration, read-only |
| `dashboard` | `dashboard/` | Never Migrate | - | Dashboard aggregation, read-only |
| `host_metric_summary_monthly` | `host_metric_summary_monthly/` | Never Migrate | - | Monthly usage summary, auto-expires (2.6 only) |
| `host_metrics` | `host_metrics/` | Never Migrate | - | Host usage metrics, auto-generated (2.6 only) |
| `instance_groups` | `instance_groups/` | Never Migrate | - | Must exist on target with same name; resolved by name during RBAC import |
| `instances` | `instances/` | Never Migrate | - | Controller infrastructure, not migrated |
| `inventory_updates` | `inventory_updates/` | Never Migrate | - | Inventory source sync logs (historical) |
| `me` | `me/` | Never Migrate | - | Current user session, read-only |
| `mesh_visualizer` | `mesh_visualizer/` | Never Migrate | - | Receptor mesh visualization, read-only |
| `metrics` | `metrics/` | Never Migrate | - | Prometheus metrics, read-only |
| `notifications` | `notifications/` | Never Migrate | - | Runtime notification instances (historical) |
| `ping` | `ping/` | Never Migrate | - | Read-only health check |
| `project_updates` | `project_updates/` | Never Migrate | - | Project SCM sync logs (historical) |
| `receptor_addresses` | `receptor_addresses/` | Never Migrate | - | Receptor mesh addresses, infrastructure (2.6 only) |
| `roles` | `roles/` | Never Migrate | - | Deprecated; replaced by RBAC |
| `service_index` | `service_index/` | Never Migrate | - | Service discovery index, read-only (2.6 only) |
| `settings` | `settings/` | Never Migrate | - | Global system settings, requires manual review |
| `system_jobs` | `system_jobs/` | Never Migrate | - | System job records (historical) |
| `tokens` | `tokens/` | Never Migrate | - | OAuth tokens, short-lived, must be recreated manually |
| `unified_job_templates` | `unified_job_templates/` | Never Migrate | - | Virtual meta-endpoint aggregating all templates |
| `unified_jobs` | `unified_jobs/` | Never Migrate | - | Virtual meta-endpoint aggregating all jobs |
| `workflow_approvals` | `workflow_approvals/` | Never Migrate | - | Workflow approval records (historical) |
| `workflow_job_nodes` | `workflow_job_nodes/` | Never Migrate | - | Per-run execution node records (historical); template nodes are embedded in `workflow_job_templates` |
| `workflow_jobs` | `workflow_jobs/` | Never Migrate | - | Workflow execution records (historical) |

## Special Handling

### Workflow Nodes

Workflow job template nodes (`workflow_job_template_nodes/`) are not migrated as standalone
resources. They are embedded within their parent `workflow_job_templates`.

### System Job Templates

System job templates are auto-created by the target AAP 2.6 instance. The migration tool only
creates ID mappings so that schedules referencing these templates can be correctly linked on
the target.
