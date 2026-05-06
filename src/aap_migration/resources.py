"""Central resource type definitions - single source of truth.

This module provides the definitive registry of all supported resource types
in the AAP migration tool. All other modules should import from here rather
than defining their own hardcoded lists.

This ensures consistency across:
- CLI commands (export, import, migrate, cleanup)
- Migration phases
- Exporter/Importer factories
- API endpoint mappings

DYNAMIC DISCOVERY (NEW):
If `schemas/source_endpoints.json` exists (created by `aap-bridge prep`),
functions will use discovered endpoints dynamically. Otherwise, falls back
to the hardcoded RESOURCE_REGISTRY below.
"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ResourceCategory(str, Enum):
    """Resource migration categories."""

    MIGRATE = "migrate"
    EXPORT_ONLY = "export-only"
    NEVER_MIGRATE = "never-migrate"


@dataclass(frozen=True, slots=True)
class VersionPath:
    source: str
    target: str
    status: str  # "supported", "partial", "unsupported"
    notes: str
    known_exceptions: list[str]


COMPATIBILITY_MATRIX: list[VersionPath] = [
    VersionPath(
        source="1.0",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="1.1",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="1.2",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="2.0",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="2.1",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="2.2",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="2.3",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="2.4",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
    VersionPath(
        source="2.5",
        target="2.6",
        status="supported",
        notes="Primary migration path. Fully tested.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
            "Instance groups referenced by RBAC assignments must exist on the target with the same name",
        ],
    ),
    VersionPath(
        source="2.6",
        target="2.6",
        status="supported",
        notes="Same-version migration path. Schema fully compatible.",
        known_exceptions=[
            "Encrypted credentials cannot be extracted from source API",
        ],
    ),
]


def get_version_path(source_version: str, target_version: str) -> VersionPath | None:
    """Look up compatibility info for a source→target version pair.

    Matches on major.minor (ignores patch).
    """
    if not source_version or not target_version:
        return None

    src_minor = ".".join(source_version.split(".")[:2])
    tgt_minor = ".".join(target_version.split(".")[:2])
    for path in COMPATIBILITY_MATRIX:
        if path.source == src_minor and path.target == tgt_minor:
            return path
    return None


@dataclass(frozen=True)
class ResourceTypeInfo:
    """Metadata for a resource type."""

    name: str
    endpoint: str
    description: str
    migration_order: int  # Lower = earlier in migration (dependency order)
    cleanup_order: int  # Lower = earlier in cleanup (reverse dependency)
    category: ResourceCategory = ResourceCategory.MIGRATE
    has_exporter: bool = True
    has_importer: bool = False
    has_transformer: bool = False
    batch_size: int = 100
    use_bulk_api: bool = False


# Complete registry of all supported resource types
# This is the SINGLE SOURCE OF TRUTH for the entire application
RESOURCE_REGISTRY: dict[str, ResourceTypeInfo] = {
    # Foundation resources (migrate first, delete last)
    "organizations": ResourceTypeInfo(
        name="organizations",
        endpoint="organizations/",
        description="Organizations",
        migration_order=20,
        cleanup_order=140,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
        batch_size=50,
    ),
    "labels": ResourceTypeInfo(
        name="labels",
        endpoint="labels/",
        description="Labels",
        migration_order=30,
        cleanup_order=130,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
    ),
    "users": ResourceTypeInfo(
        name="users",
        endpoint="users/",
        description="Users",
        migration_order=40,
        cleanup_order=120,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
    ),
    "teams": ResourceTypeInfo(
        name="teams",
        endpoint="teams/",
        description="Teams",
        migration_order=50,
        cleanup_order=110,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
    ),
    "credential_types": ResourceTypeInfo(
        name="credential_types",
        endpoint="credential_types/",
        description="Credential Types",
        migration_order=60,
        cleanup_order=100,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
        batch_size=50,
    ),
    "credentials": ResourceTypeInfo(
        name="credentials",
        endpoint="credentials/",
        description="Credentials",
        migration_order=70,
        cleanup_order=90,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=50,
    ),
    "credential_input_sources": ResourceTypeInfo(
        name="credential_input_sources",
        endpoint="credential_input_sources/",
        description="Credential Input Sources",
        migration_order=80,
        cleanup_order=85,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=100,
    ),
    "execution_environments": ResourceTypeInfo(
        name="execution_environments",
        endpoint="execution_environments/",
        description="Execution Environments",
        migration_order=90,
        cleanup_order=135,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
    ),
    "instance_groups": ResourceTypeInfo(
        name="instance_groups",
        endpoint="instance_groups/",
        description="Instance Groups",
        migration_order=117,
        cleanup_order=87,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
        batch_size=50,
    ),
    "projects": ResourceTypeInfo(
        name="projects",
        endpoint="projects/",
        description="Projects",
        migration_order=120,
        cleanup_order=80,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
    ),
    "inventory": ResourceTypeInfo(
        name="inventory",
        endpoint="inventories/",
        description="Inventories",
        migration_order=100,
        cleanup_order=60,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
    ),
    "constructed_inventories": ResourceTypeInfo(
        name="constructed_inventories",
        endpoint="constructed_inventories/",
        description="Constructed Inventories",
        migration_order=102,
        cleanup_order=58,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=100,
    ),
    "inventory_sources": ResourceTypeInfo(
        name="inventory_sources",
        endpoint="inventory_sources/",
        description="Inventory Sources",
        migration_order=101,
        cleanup_order=70,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
    ),
    "groups": ResourceTypeInfo(
        name="groups",
        endpoint="groups/",
        description="Inventory Groups",
        migration_order=110,
        cleanup_order=50,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
    ),
    "hosts": ResourceTypeInfo(
        name="hosts",
        endpoint="hosts/",
        description="Hosts",
        migration_order=115,
        cleanup_order=40,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
        batch_size=200,
        use_bulk_api=True,
    ),
    "instances": ResourceTypeInfo(
        name="instances",
        endpoint="instances/",
        description="Instances (AAP Controller Nodes)",
        migration_order=116,
        cleanup_order=88,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
        batch_size=50,
    ),
    "job_templates": ResourceTypeInfo(
        name="job_templates",
        endpoint="job_templates/",
        description="Job Templates",
        migration_order=150,
        cleanup_order=20,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
    ),
    "workflow_job_templates": ResourceTypeInfo(
        name="workflow_job_templates",
        endpoint="workflow_job_templates/",
        description="Workflow Job Templates",
        migration_order=160,
        cleanup_order=10,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=50,
    ),
    "system_job_templates": ResourceTypeInfo(
        name="system_job_templates",
        endpoint="system_job_templates/",
        description="System Job Templates",
        migration_order=165,
        cleanup_order=15,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=50,
    ),
    "schedules": ResourceTypeInfo(
        name="schedules",
        endpoint="schedules/",
        description="Schedules",
        migration_order=170,
        cleanup_order=30,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
    ),
    "notification_templates": ResourceTypeInfo(
        name="notification_templates",
        endpoint="notification_templates/",
        description="Notification Templates",
        migration_order=140,
        cleanup_order=25,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=False,
        batch_size=100,
    ),
    "role_definitions": ResourceTypeInfo(
        name="role_definitions",
        endpoint="role_definitions/",
        description="Role Definitions",
        migration_order=175,
        cleanup_order=8,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=50,
    ),
    "role_user_assignments": ResourceTypeInfo(
        name="role_user_assignments",
        endpoint="role_user_assignments/",
        description="User Role Assignments",
        migration_order=180,
        cleanup_order=6,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=100,
    ),
    "role_team_assignments": ResourceTypeInfo(
        name="role_team_assignments",
        endpoint="role_team_assignments/",
        description="Team Role Assignments",
        migration_order=185,
        cleanup_order=5,
        category=ResourceCategory.MIGRATE,
        has_exporter=True,
        has_importer=True,
        has_transformer=True,
        batch_size=100,
    ),
    "jobs": ResourceTypeInfo(
        name="jobs",
        endpoint="jobs/",
        description="Job Execution Records",
        migration_order=175,
        cleanup_order=5,
        category=ResourceCategory.EXPORT_ONLY,
        has_exporter=True,
        has_importer=False,
        has_transformer=True,
        batch_size=100,
    ),
}


# ============================================
# Never Migrate Resources (REQ-008)
# ============================================

# Endpoints intentionally excluded from migration with reasons
NEVER_MIGRATE_RESOURCES: dict[str, str] = {
    # Read-Only / Meta
    "ping": "Read-only health check",
    "config": "System configuration, read-only",
    "dashboard": "Dashboard aggregation, read-only",
    "me": "Current user session, read-only",
    "metrics": "Prometheus metrics, read-only",
    "mesh_visualizer": "Receptor mesh visualization, read-only",
    "analytics": "Analytics data, read-only (2.6 only)",
    "service_index": "Service discovery index, read-only (2.6 only)",
    # Virtual / Aggregation
    "unified_job_templates": "Virtual meta-endpoint aggregating all template types",
    "unified_jobs": "Virtual meta-endpoint aggregating all job types",
    # Runtime / Historical
    "workflow_jobs": "Workflow execution records (historical)",
    "project_updates": "Project SCM sync logs (historical)",
    "inventory_updates": "Inventory source sync logs (historical)",
    "ad_hoc_commands": "Ad-hoc command records (historical)",
    "system_jobs": "System job records (historical)",
    "workflow_job_nodes": "Workflow execution node logs (historical)",
    "notifications": "Runtime notification instances (historical)",
    "workflow_approvals": "Workflow approval records (historical)",
    # Infrastructure / Operational
    "receptor_addresses": "Receptor mesh addresses, infrastructure (2.6 only)",
    "host_metrics": "Host usage metrics, auto-generated (2.6 only)",
    "host_metric_summary_monthly": "Monthly usage summary, auto-expires (2.6 only)",
    "bulk": "Bulk API operational endpoint, not a resource",
    "activity_stream": "Audit log, historical (auto-generated on target)",
    # Manual / Deferred (REQ-002)
    "settings": "Global system settings, requires manual review",
    "roles": "Deprecated direct-role model; replaced by DAB RBAC",
    "applications": "OAuth applications, deferred from current product phase",
    "tokens": "OAuth tokens, short-lived, must be recreated manually",
}


# ============================================
# Endpoint Name Mapping (REQ-005)
# ============================================

# Maps discovered endpoint names and legacy aliases to canonical resource type names
ENDPOINT_TO_RESOURCE_TYPE = {
    # Alias (non-canonical) -> Canonical name
    "inventories": "inventory",  # Legacy internal alias
    "inventory_groups": "groups",  # Legacy internal alias
    "constructed_inventory": "constructed_inventories",  # API discovery name
    "workflow_job_template_nodes": "workflow_job_template_nodes",  # Embedded sub-resource
    "workflow_nodes": "workflow_job_template_nodes",  # Legacy internal alias
}


# ============================================
# Job Status Constants
# ============================================

# Job status states based on AAP API and AWX implementation
# See: docs/JOB_CANCEL_503_FIX_PLAN.md for detailed explanations

# Active job statuses that can be cancelled
JOB_ACTIVE_STATUSES = ["new", "pending", "waiting", "running"]

# Terminal job statuses (job completed, cannot be cancelled)
JOB_TERMINAL_STATUSES = ["successful", "failed", "error", "canceled"]

# Transient statuses (cancellation in progress)
JOB_TRANSIENT_STATUSES = ["canceling"]

# All valid job statuses
JOB_ALL_STATUSES = JOB_ACTIVE_STATUSES + JOB_TERMINAL_STATUSES + JOB_TRANSIENT_STATUSES

# Job types that CAN be deleted during clean wipe scenarios
# These are runtime/historical data - safe to delete when doing a full cleanup
# See: docs/JOB_CLEANUP_BEFORE_IMPORT.md for detailed explanations
JOB_DELETABLE_TYPES = [
    "jobs",  # Job template execution records
    "workflow_jobs",  # Workflow execution records
    "project_updates",  # Project SCM sync jobs
    "inventory_updates",  # Inventory source sync jobs
    "system_jobs",  # System cleanup/management jobs
    "ad_hoc_commands",  # Ad-hoc command execution records
]


# ============================================
# Resource Uniqueness Scope
# ============================================

# Organization-scoped resources: unique per (name, organization)
# These resources can have the same name in different organizations
ORGANIZATION_SCOPED_RESOURCES = {
    "projects",
    "inventory",
    "constructed_inventories",
    "credentials",
    "job_templates",
    "workflow_job_templates",
    "teams",
}

# Parent-scoped resources: unique within parent resource
# Format: {resource_type: parent_field_name}
PARENT_SCOPED_RESOURCES = {
    "hosts": "inventory",
    "groups": "inventory",
    "inventory_sources": "inventory",
}


# All other resources are globally unique by name (organizations, users, labels, etc.)


# ============================================
# Dynamic Endpoint Discovery (NEW)
# ============================================


def _load_discovered_endpoints() -> dict[str, str] | None:
    """Load discovered endpoints from prep output.

    Returns:
        Dict mapping resource_type -> endpoint_url, or None if not available
    """
    endpoints_file = Path("schemas/source_endpoints.json")
    if not endpoints_file.exists():
        return None

    try:
        with open(endpoints_file) as f:
            data = json.load(f)
        return {name: info["url"] for name, info in data.get("endpoints", {}).items()}
    except Exception:
        return None


def has_discovered_endpoints() -> bool:
    """Check if discovered endpoints are available.

    Returns:
        True if schemas/source_endpoints.json exists
    """
    return Path("schemas/source_endpoints.json").exists()


def get_discovered_types() -> list[str]:
    """Get all resource types discovered by prep phase.

    Returns:
        List of discovered resource type names, or empty list if prep not run
    """
    endpoints = _load_discovered_endpoints()
    return list(endpoints.keys()) if endpoints else []


# ============================================
# Helper Functions - Derived from Registry
# ============================================


def get_all_types() -> list[str]:
    """Get all supported resource types.

    Returns:
        List of all resource type names
    """
    return list(RESOURCE_REGISTRY.keys())


def get_migration_order() -> list[str]:
    """Get resource types in migration dependency order.

    Resources are ordered so dependencies are migrated first.

    Returns:
        List of resource type names in migration order
    """
    return sorted(
        RESOURCE_REGISTRY.keys(),
        key=lambda x: RESOURCE_REGISTRY[x].migration_order,
    )


def get_cleanup_order() -> list[str]:
    """Get resource types in cleanup/deletion order.

    Resources are ordered in reverse dependency order to avoid FK conflicts.

    Returns:
        List of resource type names in cleanup order
    """
    return sorted(
        RESOURCE_REGISTRY.keys(),
        key=lambda x: RESOURCE_REGISTRY[x].cleanup_order,
    )


def get_exportable_types(use_discovered: bool = False) -> list[str]:
    """Get resource types that can be exported.

    Args:
        use_discovered: If True and discovered endpoints exist, return ALL
                       discovered types (not just those with exporters).
                       If False, return only types from registry with has_exporter=True.

    Returns:
        List of resource type names available for export
    """
    if use_discovered:
        discovered = get_discovered_types()
        if discovered:
            return discovered

    # Fall back to hardcoded registry
    return [name for name, info in RESOURCE_REGISTRY.items() if info.has_exporter]


def get_importable_types(use_discovered: bool = False) -> list[str]:
    """Get resource types that can be imported.

    Args:
        use_discovered: If True and discovered endpoints exist, return ALL
                       discovered types from target (not just those with importers).
                       If False, return only types from registry with has_importer=True.

    Returns:
        List of resource type names available for import
    """
    if use_discovered:
        # Load target endpoints (for import)
        target_file = Path("schemas/target_endpoints.json")
        if target_file.exists():
            try:
                with open(target_file) as f:
                    data = json.load(f)
                return list(data.get("endpoints", {}).keys())
            except Exception:
                pass

    # Fall back to hardcoded registry
    return [name for name, info in RESOURCE_REGISTRY.items() if info.has_importer]


def get_transformable_types() -> list[str]:
    """Get resource types that have specialized transformers.

    Returns:
        List of resource type names with transformers
    """
    return [name for name, info in RESOURCE_REGISTRY.items() if info.has_transformer]


def get_fully_supported_types() -> list[str]:
    """Get resource types that support full migration (export + import).

    These are the types that can be used in migrate all command.

    Returns:
        List of resource type names with both exporter and importer
    """
    types = [
        name for name, info in RESOURCE_REGISTRY.items() if info.has_exporter and info.has_importer
    ]
    # Return in migration order
    return sorted(types, key=lambda x: RESOURCE_REGISTRY[x].migration_order)


def get_endpoint(resource_type: str) -> str:
    """Get API endpoint for a resource type.

    If discovered endpoints exist (from `aap-bridge prep`), uses those.
    Otherwise, falls back to hardcoded RESOURCE_REGISTRY.

    Args:
        resource_type: Name of the resource type

    Returns:
        API endpoint path (e.g., "organizations/" or "/api/v2/organizations/")

    Raises:
        KeyError: If resource type is not in registry or discovered endpoints
    """
    # Normalize before lookup
    resource_type = normalize_resource_type(resource_type)

    # Try discovered endpoints first
    discovered = _load_discovered_endpoints()
    if discovered and resource_type in discovered:
        return discovered[resource_type]

    # Fall back to hardcoded registry
    if resource_type in RESOURCE_REGISTRY:
        return RESOURCE_REGISTRY[resource_type].endpoint

    # Not found in either
    raise KeyError(f"Unknown resource type: {resource_type}")


def get_info(resource_type: str) -> ResourceTypeInfo:
    """Get full metadata for a resource type.

    Args:
        resource_type: Name of the resource type

    Returns:
        ResourceTypeInfo object with all metadata

    Raises:
        KeyError: If resource type is not in registry
    """
    resource_type = normalize_resource_type(resource_type)
    return RESOURCE_REGISTRY[resource_type]


def normalize_resource_type(name: str) -> str:
    """Normalize discovered endpoint name or legacy alias to canonical name.

    Args:
        name: Name discovered from API or legacy internal name.

    Returns:
        Canonical resource type name.
    """
    return ENDPOINT_TO_RESOURCE_TYPE.get(name, name)


def get_resource_category(resource_type: str) -> ResourceCategory:
    """Get the category for a resource type.

    Args:
        resource_type: Canonical name or alias.

    Returns:
        ResourceCategory for the resource.
    """
    canonical_name = normalize_resource_type(resource_type)

    if canonical_name in RESOURCE_REGISTRY:
        return RESOURCE_REGISTRY[canonical_name].category

    if canonical_name in NEVER_MIGRATE_RESOURCES:
        return ResourceCategory.NEVER_MIGRATE

    return ResourceCategory.NEVER_MIGRATE


def get_resource_category_reason(resource_type: str) -> str | None:
    """Get the reason for a resource category (primarily for never-migrate).

    Args:
        resource_type: Canonical name or alias.

    Returns:
        Reason string or None if not applicable.
    """
    canonical_name = normalize_resource_type(resource_type)

    if canonical_name in NEVER_MIGRATE_RESOURCES:
        return NEVER_MIGRATE_RESOURCES[canonical_name]

    if canonical_name == "jobs":
        return "Historical runtime data, not imported"

    return None


def get_batch_size(resource_type: str) -> int:
    """Get recommended batch size for a resource type.

    Args:
        resource_type: Name of the resource type

    Returns:
        Recommended batch size for the resource type

    Raises:
        KeyError: If resource type is not in registry
    """
    resource_type = normalize_resource_type(resource_type)
    return RESOURCE_REGISTRY[resource_type].batch_size


def is_valid_type(resource_type: str) -> bool:
    """Check if a resource type is valid.

    Args:
        resource_type: Name of the resource type

    Returns:
        True if resource type is in registry
    """
    resource_type = normalize_resource_type(resource_type)
    return resource_type in RESOURCE_REGISTRY


def get_description(resource_type: str) -> str:
    """Get human-readable description of a resource type.

    Args:
        resource_type: Name of the resource type

    Returns:
        Description string

    Raises:
        KeyError: If resource type is not in registry
    """
    resource_type = normalize_resource_type(resource_type)
    return RESOURCE_REGISTRY[resource_type].description


# ============================================
# Convenience Constants (derived from registry)
# ============================================

# All types in migration order
ALL_RESOURCE_TYPES = get_migration_order()

# Types that support full export->transform->import cycle
FULLY_SUPPORTED_TYPES = get_fully_supported_types()

# Types that can be exported
EXPORTABLE_TYPES = get_exportable_types()

# Types that can be imported
IMPORTABLE_TYPES = get_importable_types()

# Types in cleanup order (reverse dependency)
CLEANUP_ORDER = get_cleanup_order()
