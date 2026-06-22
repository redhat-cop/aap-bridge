"""Tests for organization-scoped migration helpers."""

from pathlib import Path

import pytest

from aap_migration.config import ExportConfig
from aap_migration.migration.organization_scope import (
    OrganizationScope,
    build_resource_export_filters,
    build_run_context_filters,
    get_effective_organization_name,
    load_exported_source_ids,
    organization_scope_from_metadata,
    resource_passes_org_scope,
    should_include_user_for_org,
)


@pytest.fixture
def org_scope() -> OrganizationScope:
    return OrganizationScope(name="Acme", source_id=42)


def test_get_effective_organization_name_precedence() -> None:
    assert get_effective_organization_name("CLI", "CTX", "CFG") == "CLI"
    assert get_effective_organization_name(None, "CTX", "CFG") == "CTX"
    assert get_effective_organization_name(None, None, "CFG") == "CFG"
    assert get_effective_organization_name(None, "  ", None) is None


def test_build_resource_export_filters_org_scoped(org_scope: OrganizationScope) -> None:
    export_config = ExportConfig()
    project_filters = build_resource_export_filters("projects", export_config, org_scope)
    assert project_filters["organization"] == "42"

    host_filters = build_resource_export_filters("hosts", export_config, org_scope)
    assert host_filters["inventory__organization"] == "42"

    org_filters = build_resource_export_filters("organizations", export_config, org_scope)
    assert org_filters["name__iexact"] == "Acme"


def test_build_resource_export_filters_without_org() -> None:
    export_config = ExportConfig(skip_dynamic_hosts=True)
    host_filters = build_resource_export_filters("hosts", export_config, None)
    assert host_filters["inventory_sources__isnull"] == "true"
    assert "organization" not in host_filters


def test_build_run_context_filters_includes_org(org_scope: OrganizationScope) -> None:
    export_config = ExportConfig(filters={"name__icontains": "test"})
    filters = build_run_context_filters(export_config, org_scope)
    assert ("organization", "Acme") in filters
    assert ("organization_id", "42") in filters
    assert ("name__icontains", "test") in filters


def test_resource_passes_org_scope_credential_types(org_scope: OrganizationScope) -> None:
    assert resource_passes_org_scope(
        "credential_types",
        {"organization": None},
        org_scope,
    )
    assert resource_passes_org_scope(
        "credential_types",
        {"organization": 42},
        org_scope,
    )
    assert not resource_passes_org_scope(
        "credential_types",
        {"organization": 99},
        org_scope,
    )


def test_should_include_user_for_org() -> None:
    exported_ids = {
        "teams": {10},
        "projects": {100},
    }
    user_in_team = {"_team_source_ids": [10], "_user_role_grants": []}
    user_with_grant = {
        "_team_source_ids": [],
        "_user_role_grants": [{"content_source_id": 100}],
    }
    user_unrelated = {"_team_source_ids": [99], "_user_role_grants": []}

    assert should_include_user_for_org(user_in_team, exported_ids)
    assert should_include_user_for_org(user_with_grant, exported_ids)
    assert not should_include_user_for_org(user_unrelated, exported_ids)


def test_organization_scope_from_metadata() -> None:
    metadata = {
        "run_context": {
            "organization_scope": {"name": "Acme", "source_id": 42},
        }
    }
    scope = organization_scope_from_metadata(metadata)
    assert scope is not None
    assert scope.name == "Acme"
    assert scope.source_id == 42

    legacy_metadata = {
        "run_context": {
            "filters": {"organization": "Acme", "organization_id": "42"},
        }
    }
    legacy_scope = organization_scope_from_metadata(legacy_metadata)
    assert legacy_scope is not None
    assert legacy_scope.source_id == 42


def test_load_exported_source_ids(tmp_path: Path) -> None:
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    with open(teams_dir / "teams_0001.json", "w") as f:
        f.write('[{"id": 1, "name": "ops"}, {"id": 2, "name": "dev"}]')

    ids = load_exported_source_ids(tmp_path)
    assert ids["teams"] == {1, 2}
