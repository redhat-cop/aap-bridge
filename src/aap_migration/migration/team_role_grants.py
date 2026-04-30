"""Parse and apply principal (user / team) role grants on other resources."""

from __future__ import annotations

from typing import Any

from aap_migration.resources import normalize_resource_type
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

# Built-in roles on the team object itself; recreated with the team on target.
_TEAM_SELF_ROLE_NAMES = frozenset({"member", "admin", "read"})

# Resource types whose role grants are NOT migrated.
# Organization roles changed semantics in AAP 2.5 and cannot be applied directly.
_SKIP_GRANT_RESOURCE_TYPES = frozenset({"organizations"})

# Singular resource_type strings → canonical plural names
_TYPE_MAP: dict[str, str] = {
    "job_template": "job_templates",
    "project": "projects",
    "workflow_job_template": "workflow_job_templates",
    "credential": "credentials",
    "inventory": "inventory",
    "organization": "organizations",
    "team": "teams",
    "instance_group": "instance_groups",
    "execution_environment": "execution_environments",
    "notification_template": "notification_templates",
    # display-name variants (space-separated, from resource_type_display_name)
    "job template": "job_templates",
    "workflow job template": "workflow_job_templates",
    "instance group": "instance_groups",
    "execution environment": "execution_environments",
    "notification template": "notification_templates",
}


def _norm_role_name(s: str | None) -> str:
    return (s or "").strip().casefold()


def _is_self_team_role(
    canonical: str,
    rid: int,
    role_name: str,
    *,
    skip_self_type: str | None,
    skip_self_id: int | None,
) -> bool:
    """True when a role is a built-in team self-role that should not be re-exported."""
    return (
        skip_self_type is not None
        and skip_self_id is not None
        and canonical == skip_self_type
        and rid == skip_self_id
        and _norm_role_name(role_name) in _TEAM_SELF_ROLE_NAMES
    )


def _parse_role_grant(
    role: dict[str, Any],
    *,
    skip_self_type: str | None = None,
    skip_self_id: int | None = None,
) -> dict[str, str | int] | None:
    """Shared parser for a Role row from ``GET /<principal>/{id}/roles/``.

    Returns ``{role_name, content_resource_type, content_source_id}`` or ``None`` to skip.

    ``skip_self_type`` / ``skip_self_id``: if the resolved resource matches this type+id
    AND the role name is one of the built-in self-role names (Member/Admin/Read), skip it.
    Used for teams to avoid re-exporting the team's own built-in roles.
    """
    if not role:
        return None

    name = role.get("name")
    if not name:
        return None

    summary = role.get("summary_fields") or {}

    # 1) unified_job_template (job template vs workflow – some AWX versions)
    ujt = summary.get("unified_job_template")
    if isinstance(ujt, dict) and ujt.get("id") is not None:
        uj_type = (ujt.get("unified_job_type") or ujt.get("type") or "").lower()
        rtype = "workflow_job_templates" if "workflow" in uj_type else "job_templates"
        return {
            "role_name": str(name).strip(),
            "content_resource_type": rtype,
            "content_source_id": int(ujt["id"]),
        }

    # 2) Nested summary_fields keys (AWX / some AAP versions)
    field_to_type: list[tuple[str, str]] = [
        ("project", "projects"),
        ("organization", "organizations"),
        ("inventory", "inventory"),
        ("credential", "credentials"),
        ("job_template", "job_templates"),
        ("workflow_job_template", "workflow_job_templates"),
        ("instance_group", "instance_groups"),
        ("execution_environment", "execution_environments"),
        ("notification_template", "notification_templates"),
        ("team", "teams"),
    ]

    for field, rtype in field_to_type:
        obj = summary.get(field)
        if not isinstance(obj, dict) or obj.get("id") is None:
            continue
        rid = int(obj["id"])
        canonical = normalize_resource_type(rtype)
        if canonical in _SKIP_GRANT_RESOURCE_TYPES:
            return None
        if _is_self_team_role(canonical, rid, str(name), skip_self_type=skip_self_type, skip_self_id=skip_self_id):
            return None
        return {
            "role_name": str(name).strip(),
            "content_resource_type": canonical,
            "content_source_id": rid,
        }

    # 3) Flat resource_type + resource_id (AAP 2.3 GET /{principal}/{id}/roles/ format)
    rtype_str = (summary.get("resource_type") or summary.get("resource_type_display_name") or "")
    if isinstance(rtype_str, dict):
        rtype_str = rtype_str.get("name", "") or rtype_str.get("type", "")
    rtype_str = str(rtype_str).strip().lower()

    flat_rid = summary.get("resource_id")

    # 3b) AAP 1.0 omits resource_id from summary_fields; fall back to the
    # related URL for the same resource type key (e.g. related["organization"]
    # = "/api/v2/organizations/1/") and extract the trailing numeric ID.
    if rtype_str and flat_rid is None:
        related = role.get("related") or {}
        rel_url = related.get(rtype_str)
        if rel_url:
            parts = str(rel_url).rstrip("/").split("/")
            for part in reversed(parts):
                if part.isdigit():
                    flat_rid = int(part)
                    break

    if rtype_str and flat_rid is not None:
        canonical_raw = _TYPE_MAP.get(rtype_str)
        if canonical_raw:
            canonical = normalize_resource_type(canonical_raw)
            rid = int(flat_rid)
            if canonical in _SKIP_GRANT_RESOURCE_TYPES:
                return None
            if _is_self_team_role(canonical, rid, str(name), skip_self_type=skip_self_type, skip_self_id=skip_self_id):
                return None
            return {
                "role_name": str(name).strip(),
                "content_resource_type": canonical,
                "content_source_id": rid,
            }

    # 4) Nested "resource" dict (some older AWX versions)
    res = summary.get("resource")
    if rtype_str and isinstance(res, dict) and res.get("id") is not None:
        canonical_raw = _TYPE_MAP.get(rtype_str)
        if canonical_raw:
            rid = int(res["id"])
            canonical = normalize_resource_type(canonical_raw)
            if canonical in _SKIP_GRANT_RESOURCE_TYPES:
                return None
            if _is_self_team_role(canonical, rid, str(name), skip_self_type=skip_self_type, skip_self_id=skip_self_id):
                return None
            return {
                "role_name": str(name).strip(),
                "content_resource_type": canonical,
                "content_source_id": rid,
            }

    logger.debug(
        "role_grant_unparsed",
        role_id=role.get("id"),
        role_name=name,
    )
    return None


def parse_team_role_from_api(
    role: dict[str, Any],
    *,
    team_source_id: int,
) -> dict[str, str | int] | None:
    """Extract grant info from a Role row in ``GET /teams/{id}/roles/``.

    Filters out built-in Member/Admin/Read roles on the team itself.
    """
    return _parse_role_grant(
        role,
        skip_self_type="teams",
        skip_self_id=team_source_id,
    )


def parse_user_role_from_api(
    role: dict[str, Any],
) -> dict[str, str | int] | None:
    """Extract grant info from a Role row in ``GET /users/{id}/roles/``.

    Users have no built-in self-roles to filter; all grants are included.
    """
    return _parse_role_grant(role)
