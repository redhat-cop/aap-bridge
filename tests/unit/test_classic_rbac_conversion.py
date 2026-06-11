"""Tests for classic AWX RBAC grant conversion."""

import pytest

from aap_migration.migration.classic_rbac_conversion import (
    classic_role_definition_name,
    classic_team_grant_to_assignment,
    classic_user_grant_to_assignment,
)


class TestClassicRoleDefinitionName:
    @pytest.mark.parametrize(
        ("resource_type", "role_name", "expected"),
        [
            ("job_templates", "Execute", "JobTemplate Execute"),
            ("projects", "Use", "Project Use"),
            ("organizations", "Member", "Organization Member"),
            ("teams", "Admin", "Team Admin"),
            ("credentials", "Use", "Credential Use"),
        ],
    )
    def test_maps_managed_roles(
        self, resource_type: str, role_name: str, expected: str
    ) -> None:
        assert classic_role_definition_name(resource_type, role_name) == expected


class TestClassicGrantConversion:
    def test_user_grant_to_assignment(self) -> None:
        grant = {
            "role_name": "Execute",
            "content_resource_type": "job_templates",
            "content_source_id": 7,
        }
        row = classic_user_grant_to_assignment(
            grant, user_source_id=4, assignment_source_id=1
        )
        assert row == {
            "_source_id": 1,
            "content_type": "awx.jobtemplate",
            "object_id": 7,
            "role_definition_name": "JobTemplate Execute",
            "user": 4,
        }

    def test_team_grant_to_assignment(self) -> None:
        grant = {
            "role_name": "Use",
            "content_resource_type": "projects",
            "content_source_id": 6,
        }
        row = classic_team_grant_to_assignment(
            grant, team_source_id=2, assignment_source_id=9
        )
        assert row == {
            "_source_id": 9,
            "content_type": "awx.project",
            "object_id": 6,
            "role_definition_name": "Project Use",
            "team": 2,
        }

    def test_org_member_user_grant(self) -> None:
        grant = {
            "role_name": "Member",
            "content_resource_type": "organizations",
            "content_source_id": 1,
        }
        row = classic_user_grant_to_assignment(
            grant, user_source_id=3, assignment_source_id=2
        )
        assert row is not None
        assert row["role_definition_name"] == "Organization Member"
        assert row["content_type"] == "awx.organization"
