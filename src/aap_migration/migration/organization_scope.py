"""Organization-scoped migration helpers.

Supports exporting and migrating resources belonging to a single AAP organization,
including global assets (users, custom role definitions) required by that org.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.exceptions import ConfigurationError
from aap_migration.config import ExportConfig
from aap_migration.resources import normalize_resource_type
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

# Direct organization FK on the resource record (AAP query: organization=<id>).
ORGANIZATION_ID_FILTER_RESOURCES = frozenset(
    {
        "teams",
        "projects",
        "inventory",
        "constructed_inventories",
        "credentials",
        "job_templates",
        "workflow_job_templates",
        "notification_templates",
        "labels",
        "execution_environments",
    }
)

# Org scope via inventory parent (AAP query: inventory__organization=<id>).
INVENTORY_ORG_FILTER_RESOURCES = frozenset(
    {
        "hosts",
        "groups",
        "inventory_sources",
    }
)

# Org scope via unified job template parent.
SCHEDULE_ORG_FILTER_RESOURCES = frozenset({"schedules"})

# Org scope via credential parent.
CREDENTIAL_INPUT_SOURCE_ORG_FILTER_RESOURCES = frozenset({"credential_input_sources"})

# Client-side filter after API fetch (supports null/global org on credential types).
CLIENT_ORG_FILTER_RESOURCES = frozenset({"credential_types"})

# Post-filter during transform (no reliable org list API filter).
TRANSFORM_ORG_FILTER_RESOURCES = frozenset({"users"})


@dataclass(frozen=True, slots=True)
class OrganizationScope:
    """Resolved source organization for scoped migration."""

    name: str
    source_id: int

    def to_metadata(self) -> dict[str, Any]:
        return {"name": self.name, "source_id": self.source_id}

    @classmethod
    def from_metadata(cls, data: dict[str, Any] | None) -> OrganizationScope | None:
        if not data:
            return None
        name = data.get("name")
        source_id = data.get("source_id")
        if not name or source_id is None:
            return None
        return cls(name=str(name), source_id=int(source_id))


async def resolve_organization(client: AAPSourceClient, name: str) -> OrganizationScope:
    """Look up a source organization by exact name (case-insensitive)."""
    trimmed = name.strip()
    if not trimmed:
        raise ConfigurationError("Organization name cannot be empty")

    orgs = await client.get_organizations(params={"name__iexact": trimmed, "page_size": 1})
    if not orgs:
        raise ConfigurationError(
            f"Organization '{trimmed}' was not found on the source AAP instance."
        )

    org = orgs[0]
    org_id = org.get("id")
    org_name = org.get("name", trimmed)
    if org_id is None:
        raise ConfigurationError(f"Organization '{trimmed}' returned no id from the API.")

    logger.info(
        "organization_scope_resolved",
        organization_name=org_name,
        organization_id=org_id,
    )
    return OrganizationScope(name=str(org_name), source_id=int(org_id))


def build_run_context_filters(
    export_config: ExportConfig,
    org_scope: OrganizationScope | None,
) -> tuple[tuple[str, str], ...]:
    """Build sorted filter pairs for export run identity / resume fingerprint."""
    merged: dict[str, str] = dict(export_config.filters)
    if org_scope:
        merged["organization"] = org_scope.name
        merged["organization_id"] = str(org_scope.source_id)
    return tuple(sorted(merged.items()))


def build_resource_export_filters(
    resource_type: str,
    export_config: ExportConfig,
    org_scope: OrganizationScope | None = None,
) -> dict[str, str]:
    """Build API query filters for a resource type export."""
    rtype = normalize_resource_type(resource_type)
    filters: dict[str, str] = dict(export_config.filters)

    if org_scope:
        if rtype == "organizations":
            filters["name__iexact"] = org_scope.name
        elif rtype in ORGANIZATION_ID_FILTER_RESOURCES:
            filters["organization"] = str(org_scope.source_id)
        elif rtype in INVENTORY_ORG_FILTER_RESOURCES:
            filters["inventory__organization"] = str(org_scope.source_id)
        elif rtype in SCHEDULE_ORG_FILTER_RESOURCES:
            filters["unified_job_template__organization"] = str(org_scope.source_id)
        elif rtype in CREDENTIAL_INPUT_SOURCE_ORG_FILTER_RESOURCES:
            filters["credential__organization"] = str(org_scope.source_id)

    if rtype == "hosts" and export_config.skip_dynamic_hosts:
        filters["inventory_sources__isnull"] = "true"
    if rtype == "inventory":
        filters["pending_deletion"] = "false"
    if rtype == "role_definitions":
        filters["managed"] = "false"

    return filters


def resource_passes_org_scope(
    resource_type: str,
    resource: dict[str, Any],
    org_scope: OrganizationScope,
) -> bool:
    """Client-side org filter for resources that cannot be fully scoped via API."""
    rtype = normalize_resource_type(resource_type)
    org_id = org_scope.source_id

    if rtype == "credential_types":
        resource_org = resource.get("organization")
        summary_org = (resource.get("summary_fields") or {}).get("organization") or {}
        if resource_org is None and summary_org.get("id") is not None:
            resource_org = summary_org.get("id")
        # Include org-specific custom types and global custom types (null org).
        return resource_org is None or int(resource_org) == org_id

    if rtype == "organizations":
        return int(resource.get("id", -1)) == org_id

    return True


def load_exported_source_ids(
    input_dir: Path,
    resource_types: list[str] | None = None,
) -> dict[str, set[int]]:
    """Load source IDs from exported JSON files grouped by resource type."""
    ids_by_type: dict[str, set[int]] = {}
    if not input_dir.exists():
        return ids_by_type

    for type_dir in input_dir.iterdir():
        if not type_dir.is_dir():
            continue
        rtype = normalize_resource_type(type_dir.name)
        if resource_types and rtype not in {normalize_resource_type(t) for t in resource_types}:
            continue

        type_ids: set[int] = ids_by_type.setdefault(rtype, set())
        for json_file in sorted(type_dir.glob("*.json")):
            try:
                with open(json_file) as f:
                    resources = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(resources, list):
                continue
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                source_id = resource.get("_source_id") or resource.get("id")
                if source_id is not None:
                    type_ids.add(int(source_id))

    return ids_by_type


def should_include_user_for_org(
    user: dict[str, Any],
    exported_ids: dict[str, set[int]],
) -> bool:
    """Return True if a user should migrate as part of an org-scoped run."""
    exported_team_ids = exported_ids.get("teams", set())
    team_ids = user.get("_team_source_ids") or []
    if any(int(tid) in exported_team_ids for tid in team_ids):
        return True

    exported_flat_ids: set[int] = set()
    for rtype, ids in exported_ids.items():
        if rtype in {"users", "organizations", "role_definitions"}:
            continue
        exported_flat_ids.update(ids)

    for grant in user.get("_user_role_grants") or []:
        content_id = grant.get("content_source_id")
        if content_id is not None and int(content_id) in exported_flat_ids:
            return True

    return False


def get_effective_organization_name(
    cli_organization: str | None,
    ctx_organization: str | None,
    config_organization: str | None,
) -> str | None:
    """Resolve organization name with CLI > context > config precedence."""
    for value in (cli_organization, ctx_organization, config_organization):
        if value and str(value).strip():
            return str(value).strip()
    return None


def organization_scope_from_metadata(metadata: dict[str, Any]) -> OrganizationScope | None:
    """Extract organization scope from export metadata.json."""
    run_context = metadata.get("run_context") or {}
    org_data = run_context.get("organization_scope")
    if org_data:
        return OrganizationScope.from_metadata(org_data)

    filters = run_context.get("filters") or {}
    org_name = filters.get("organization")
    org_id = filters.get("organization_id")
    if org_name and org_id is not None:
        return OrganizationScope(name=str(org_name), source_id=int(org_id))
    return None
