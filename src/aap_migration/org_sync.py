"""Add/update synchronization for an explicitly selected organization.

This experimental path covers ordinary inventories, static hosts, Git projects,
and credential-free job templates. It is separate from migration checkpoints.
"""

import asyncio
import time
from collections import Counter
from copy import deepcopy
from typing import Any

import yaml

from aap_migration.client.api_layout import ApiMode
from aap_migration.client.base_client import BaseAPIClient

Row = dict[str, Any]

ENDPOINTS = {
    "inventories": "inventories",
    "hosts": "hosts",
    "projects": "projects",
    "job_templates": "job_templates",
}
FIELDS = {
    "organizations": ("name", "description"),
    "inventories": ("name", "description", "variables"),
    "hosts": ("name", "description", "variables", "enabled"),
    "projects": (
        "name",
        "description",
        "scm_type",
        "scm_url",
        "scm_branch",
        "scm_refspec",
        "scm_clean",
        "scm_delete_on_update",
        "scm_update_on_launch",
    ),
    "job_templates": (
        "name",
        "description",
        "job_type",
        "playbook",
        "extra_vars",
        "limit",
        "verbosity",
        "forks",
        "timeout",
        "ask_variables_on_launch",
    ),
}


class SyncError(Exception):
    """A scope or supported-resource constraint prevented synchronization."""


async def list_all(
    client: BaseAPIClient, endpoint: str, *, api_base: str | None = None, **filters: Any
) -> list[Row]:
    rows, page = [], 1
    while True:
        params = {**filters, "page_size": 200, "page": page}
        response = (
            await client.get_on_base(api_base, endpoint, params=params)
            if api_base is not None
            else await client.get(endpoint, params=params)
        )
        batch = response.get("results")
        if not isinstance(batch, list):
            raise SyncError(f"Expected paginated results from {endpoint}.")
        rows.extend(batch)
        if not response.get("next"):
            return rows
        if not batch:
            raise SyncError(f"Pagination stopped unexpectedly at {endpoint}.")
        page += 1


def unique(rows: list[Row], kind: str) -> dict[Any, Row]:
    result = {}
    for row in rows:
        key = (row["inventory"], row["name"]) if kind == "hosts" else row["name"]
        if key in result:
            raise SyncError(f"Ambiguous {kind} name {row['name']!r}; resolve duplicates first.")
        result[key] = row
    return result


async def controller_organization_id(
    client: BaseAPIClient, organization: Row, *, wait_seconds: float = 0
) -> int:
    """Resolve Controller foreign keys independently of Gateway organization IDs."""
    layout = getattr(client, "api_layout", None)
    if layout is None or layout.mode is not ApiMode.GATEWAY:
        return int(organization["id"])
    deadline = time.monotonic() + wait_seconds
    while True:
        matches = [
            row
            for row in await list_all(
                client, "organizations/", api_base=layout.controller_base, name=organization["name"]
            )
            if row.get("name") == organization["name"]
        ]
        if len(matches) > 1:
            raise SyncError("Ambiguous Controller organization; refusing to map Gateway IDs.")
        if matches:
            return int(matches[0]["id"])
        if time.monotonic() >= deadline:
            raise SyncError(
                "Organization is not visible on the Controller API; wait for Gateway "
                "synchronization and rerun. No Gateway ID will be used as a Controller foreign key."
            )
        await asyncio.sleep(1)


def validate(snapshot: Row, allow_missing_inventory: bool = False) -> None:
    """Validate the entire source graph before making any writes."""
    if not snapshot.get("organizations"):
        raise SyncError("Snapshot has no organization.")
    for kind in ENDPOINTS:
        unique(snapshot[kind], kind)
        ids = [row["id"] for row in snapshot[kind]]
        if len(ids) != len(set(ids)):
            raise SyncError(f"Duplicate source IDs in {kind}.")
    org_id = snapshot.get("controller_organization_id", snapshot["organizations"]["id"])
    for kind in ("inventories", "projects"):
        if any(row.get("organization") != org_id for row in snapshot[kind]):
            raise SyncError(f"{kind} references an organization outside the selected scope.")
    inventories = {row["id"] for row in snapshot["inventories"]}
    projects = {row["id"] for row in snapshot["projects"]}
    for row in snapshot["inventories"]:
        if row.get("kind") or row.get("has_inventory_sources") or row.get("total_groups", 0):
            raise SyncError(
                "This sync path supports static inventories without groups or inventory sources."
            )
    for row in snapshot["hosts"]:
        if row["inventory"] not in inventories or row.get("has_inventory_sources"):
            raise SyncError("Host belongs to an external or dynamically managed inventory.")
    for row in snapshot["projects"]:
        if row.get("credential") or row.get("scm_type") != "git":
            raise SyncError("This sync path supports credential-free Git projects only.")
        if row.get("default_environment"):
            raise SyncError(
                "Project execution-environment mapping is not implemented in this sync path."
            )
    for row in snapshot["job_templates"]:
        inventory_missing = row.get("inventory") is None and allow_missing_inventory
        if row.get("project") not in projects or (
            row.get("inventory") not in inventories and not inventory_missing
        ):
            raise SyncError(
                "Job template references a project or inventory outside the selected organization."
            )
        if row.get("execution_environment") or (row.get("_has_credentials")):
            raise SyncError(
                "Credential/execution-environment mapping is not implemented in this sync path."
            )
        if row.get("survey_enabled"):
            raise SyncError("Survey synchronization is not implemented in this sync path.")


async def snapshot_org(
    client: BaseAPIClient,
    organization: str,
    required: bool = True,
    allow_missing_inventory: bool = False,
) -> Row:
    matches = [
        row
        for row in await list_all(client, "organizations/", name=organization)
        if row.get("name") == organization
    ]
    if len(matches) > 1:
        raise SyncError(f"Multiple organizations named {organization!r}.")
    empty: dict[str, list[Row]] = {kind: [] for kind in ENDPOINTS}
    if not matches:
        if required:
            raise SyncError(f"Source organization {organization!r} does not exist.")
        return {"organizations": None, **empty}
    org = matches[0]
    content_org_id = await controller_organization_id(client, org)
    snapshot: Row = {"organizations": org, "controller_organization_id": content_org_id, **empty}
    for kind in ("inventories", "projects", "job_templates"):
        rows = await list_all(client, f"{ENDPOINTS[kind]}/", organization=content_org_id)
        if any(row.get("organization") != content_org_id for row in rows):
            raise SyncError(
                f"API returned {kind} outside the requested organization; refusing to continue."
            )
        snapshot[kind] = rows
    for inventory in snapshot["inventories"]:
        rows = await list_all(client, f"inventories/{inventory['id']}/hosts/")
        if any(row.get("inventory") != inventory["id"] for row in rows):
            raise SyncError("API returned hosts outside the requested inventory.")
        snapshot["hosts"].extend(rows)
    for template in snapshot["job_templates"]:
        credentials = await list_all(client, f"job_templates/{template['id']}/credentials/")
        template["_has_credentials"] = bool(credentials)
        template["_credential_ids"] = [row["id"] for row in credentials]
    validate(
        snapshot,
        allow_missing_inventory=allow_missing_inventory,
    )
    return snapshot


def equal(left: Any, right: Any, field: str) -> bool:
    if field in ("variables", "extra_vars"):
        try:
            return bool(yaml.safe_load(left or "{}") == yaml.safe_load(right or "{}"))
        except yaml.YAMLError:
            pass
    return bool(left == right)


async def reconcile(
    snapshot: Row,
    target: BaseAPIClient,
    organization: str,
    apply: bool = False,
    project_timeout: float = 300,
) -> Row:
    validate(snapshot)
    if not snapshot["organizations"] or snapshot["organizations"]["name"] != organization:
        raise SyncError("Snapshot does not match the selected organization.")
    existing = await snapshot_org(
        target,
        organization,
        required=False,
        allow_missing_inventory=True,
    )
    changes: list[Row] = []
    mappings: dict[str, dict[int, int]] = {kind: {} for kind in ENDPOINTS}

    async def upsert(
        kind: str, source: Row, current: Row | None, parents: Row | None = None
    ) -> Row:
        payload = {field: deepcopy(source[field]) for field in FIELDS[kind] if field in source}
        payload.update(parents or {})
        endpoint = "organizations" if kind == "organizations" else ENDPOINTS[kind]
        delta = {
            field: value
            for field, value in payload.items()
            if current is None or not equal(current.get(field), value, field)
        }
        action = "create" if current is None else ("update" if delta else "unchanged")
        # Store field names only; variables might contain sensitive information.
        changes.append(
            {"resource": kind, "name": source["name"], "action": action, "fields": sorted(delta)}
        )
        if apply and action == "create":
            return await target.post(endpoint + "/", json_data=payload)
        if apply and current is not None and delta:
            return await target.patch(f"{endpoint}/{current['id']}/", json_data=delta)
        return current or {**payload, "id": -len(changes)}

    org = await upsert("organizations", snapshot["organizations"], existing["organizations"])
    content_org_id = (
        await controller_organization_id(target, org, wait_seconds=30)
        if apply
        else existing.get("controller_organization_id", org["id"])
    )
    for kind in ("inventories", "projects", "hosts", "job_templates"):
        index = unique(existing[kind], kind)
        for row in sorted(
            snapshot[kind], key=lambda item: (item.get("inventory", 0), item["name"])
        ):
            parents = {}
            if kind in ("inventories", "projects"):
                parents["organization"] = content_org_id
            if kind in ("hosts", "job_templates"):
                parents["inventory"] = mappings["inventories"][row["inventory"]]
            if kind == "job_templates":
                parents["project"] = mappings["projects"][row["project"]]
            key = (parents["inventory"], row["name"]) if kind == "hosts" else row["name"]
            current = index.get(key)
            result = await upsert(kind, row, current, parents)
            mappings[kind][row["id"]] = result["id"]
        # Newly created Git projects must finish syncing before playbook validation.
        if kind == "projects" and apply and snapshot["job_templates"]:
            wait_ids = set(mappings[kind].values())
            for project_id in wait_ids:
                deadline = time.monotonic() + project_timeout
                while True:
                    project = await target.get(f"projects/{project_id}/")
                    if project.get("status") == "successful":
                        break
                    if project.get("status") not in (
                        "pending",
                        "waiting",
                        "running",
                        "new",
                        "updating",
                    ):
                        raise SyncError(
                            "Project sync is not successful; inspect it in AAP and rerun."
                        )
                    if time.monotonic() >= deadline:
                        raise SyncError(
                            "Timed out waiting for project sync; inspect it in AAP and rerun."
                        )
                    await asyncio.sleep(2)
    report = {
        "organization": organization,
        "applied": apply,
        "summary": dict(Counter(change["action"] for change in changes)),
        "changes": changes,
    }
    return report


async def synchronize(
    source: BaseAPIClient, target: BaseAPIClient, organization: str, apply: bool = False
) -> Row:
    snapshot = await snapshot_org(source, organization)
    return await reconcile(
        snapshot,
        target,
        organization,
        apply=apply,
    )
