"""Convert classic AWX principal role grants to AAP 2.5+ role assignments.

Legacy sources (AAP <=2.4) export grants from ``GET /users/{id}/roles/`` and
``GET /teams/{id}/roles/``. Gateway targets (AAP 2.5+) require
``role_user_assignments`` / ``role_team_assignments`` instead of the deprecated
principal role POST APIs.
"""

from __future__ import annotations

from typing import Any

from aap_migration.resources import normalize_resource_type
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

# Canonical resource type -> RBAC content_type for role assignment import.
_RESOURCE_TYPE_TO_CONTENT_TYPE: dict[str, str] = {
    "credentials": "awx.credential",
    "execution_environments": "awx.executionenvironment",
    "instance_groups": "awx.instancegroup",
    "inventory": "awx.inventory",
    "job_templates": "awx.jobtemplate",
    "notification_templates": "awx.notificationtemplate",
    "organizations": "awx.organization",
    "projects": "awx.project",
    "teams": "awx.team",
    "workflow_job_templates": "awx.workflowjobtemplate",
}

# Managed role_definition names on AAP 2.5+ keyed by (resource_type, role_name).
_MANAGED_ROLE_DEFINITION_NAMES: dict[tuple[str, str], str] = {
    ("credentials", "use"): "Credential Use",
    ("credentials", "admin"): "Credential Admin",
    ("execution_environments", "use"): "ExecutionEnvironment Use",
    ("execution_environments", "admin"): "ExecutionEnvironment Admin",
    ("instance_groups", "use"): "InstanceGroup Use",
    ("instance_groups", "admin"): "InstanceGroup Admin",
    ("inventory", "use"): "Inventory Use",
    ("inventory", "admin"): "Inventory Admin",
    ("inventory", "ad hoc"): "Inventory Ad Hoc",
    ("job_templates", "execute"): "JobTemplate Execute",
    ("job_templates", "admin"): "JobTemplate Admin",
    ("job_templates", "read"): "JobTemplate Read",
    ("notification_templates", "admin"): "NotificationTemplate Admin",
    ("notification_templates", "read"): "NotificationTemplate Read",
    ("organizations", "member"): "Organization Member",
    ("organizations", "admin"): "Organization Admin",
    ("organizations", "read"): "Organization Read",
    ("projects", "use"): "Project Use",
    ("projects", "admin"): "Project Admin",
    ("projects", "update"): "Project Update",
    ("projects", "read"): "Project Read",
    ("teams", "member"): "Team Member",
    ("teams", "admin"): "Team Admin",
    ("teams", "read"): "Team Read",
    ("workflow_job_templates", "execute"): "WorkflowJobTemplate Execute",
    ("workflow_job_templates", "admin"): "WorkflowJobTemplate Admin",
    ("workflow_job_templates", "read"): "WorkflowJobTemplate Read",
}

# Singular model names used to build role_definition names from classic labels.
_RESOURCE_SINGULAR: dict[str, str] = {
    "credentials": "Credential",
    "execution_environments": "ExecutionEnvironment",
    "instance_groups": "InstanceGroup",
    "inventory": "Inventory",
    "job_templates": "JobTemplate",
    "notification_templates": "NotificationTemplate",
    "organizations": "Organization",
    "projects": "Project",
    "teams": "Team",
    "workflow_job_templates": "WorkflowJobTemplate",
}


def _norm_role_name(name: str | None) -> str:
    return (name or "").strip().casefold()


def classic_role_definition_name(resource_type: str, role_name: str) -> str | None:
    """Map a classic object role label to a target role_definition name."""
    role_name = (role_name or "").strip()
    if not role_name:
        return None

    canonical = normalize_resource_type(resource_type)
    mapped = _MANAGED_ROLE_DEFINITION_NAMES.get((canonical, _norm_role_name(role_name)))
    if mapped:
        return mapped

    singular = _RESOURCE_SINGULAR.get(canonical)
    if singular:
        return f"{singular} {role_name}"

    return role_name


def _grant_to_assignment_fields(
    grant: dict[str, Any],
) -> tuple[str, str, int] | None:
    """Return (content_type, role_definition_name, content_source_id) or None."""
    raw_ct = grant.get("content_resource_type")
    role_name = str(grant.get("role_name", "")).strip()
    if raw_ct is None or not str(raw_ct).strip() or not role_name:
        return None

    resource_type = normalize_resource_type(str(raw_ct).strip())
    content_type = _RESOURCE_TYPE_TO_CONTENT_TYPE.get(resource_type)
    if not content_type:
        logger.debug(
            "classic_grant_unknown_resource_type",
            content_resource_type=raw_ct,
            role_name=role_name,
        )
        return None

    try:
        content_source_id = int(grant.get("content_source_id"))
    except (TypeError, ValueError):
        return None

    role_definition_name = classic_role_definition_name(resource_type, role_name)
    if not role_definition_name:
        return None

    return content_type, role_definition_name, content_source_id


def classic_user_grant_to_assignment(
    grant: dict[str, Any],
    *,
    user_source_id: int,
    assignment_source_id: int,
) -> dict[str, Any] | None:
    """Build a role_user_assignments import row from a classic user grant."""
    fields = _grant_to_assignment_fields(grant)
    if not fields:
        return None
    content_type, role_definition_name, content_source_id = fields
    return {
        "_source_id": assignment_source_id,
        "content_type": content_type,
        "object_id": content_source_id,
        "role_definition_name": role_definition_name,
        "user": user_source_id,
    }


def classic_team_grant_to_assignment(
    grant: dict[str, Any],
    *,
    team_source_id: int,
    assignment_source_id: int,
) -> dict[str, Any] | None:
    """Build a role_team_assignments import row from a classic team grant."""
    fields = _grant_to_assignment_fields(grant)
    if not fields:
        return None
    content_type, role_definition_name, content_source_id = fields
    return {
        "_source_id": assignment_source_id,
        "content_type": content_type,
        "object_id": content_source_id,
        "role_definition_name": role_definition_name,
        "team": team_source_id,
    }
