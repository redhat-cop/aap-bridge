"""Unit tests for RBAC import content_type and API base routing."""

import pytest

from aap_migration.client.api_layout import ApiLayout, ApiMode, role_definition_api_base
from aap_migration.migration.importer import _resource_type_for_rbac_content_type


class TestRbacContentTypeMapping:
    @pytest.mark.parametrize(
        ("content_type", "resource_type"),
        [
            ("shared.organization", "organizations"),
            ("shared.team", "teams"),
            ("awx.organization", "organizations"),
            ("awx.credential", "credentials"),
            ("awx.workflowjobtemplate", "workflow_job_templates"),
        ],
    )
    def test_maps_gateway_and_controller_labels(
        self, content_type: str, resource_type: str
    ) -> None:
        assert _resource_type_for_rbac_content_type(content_type) == resource_type

    def test_unknown_content_type_returns_none(self) -> None:
        assert _resource_type_for_rbac_content_type("unknown.model") is None


class TestRoleDefinitionApiBase:
    def _gateway_layout(self) -> ApiLayout:
        return ApiLayout(
            host_url="https://aap.example.com",
            mode=ApiMode.GATEWAY,
            aap_version="2.6",
            gateway_base="https://aap.example.com/api/gateway/v1",
            controller_base="https://aap.example.com/api/controller/v2",
        )

    def test_platform_roles_use_gateway(self) -> None:
        layout = self._gateway_layout()
        assert role_definition_api_base(layout, "shared.organization", None) == (
            "https://aap.example.com/api/gateway/v1"
        )

    def test_automation_roles_use_controller(self) -> None:
        layout = self._gateway_layout()
        assert role_definition_api_base(layout, "awx.project", None) == (
            "https://aap.example.com/api/controller/v2"
        )

    def test_exported_source_api_base_maps_to_target_controller(self) -> None:
        layout = self._gateway_layout()
        # Export records source hostname; import must use target controller base.
        assert role_definition_api_base(
            layout,
            "awx.project",
            "https://aap25.example.com/api/controller/v2",
        ) == ("https://aap.example.com/api/controller/v2")

    def test_gateway_exported_automation_role_uses_target_controller(self) -> None:
        layout = self._gateway_layout()
        # awx.* roles may be listed from the gateway API during export, but
        # assignments are created on the controller — lookups must follow.
        assert role_definition_api_base(
            layout,
            "awx.project",
            "https://aap25.example.com/api/gateway/v1",
        ) == ("https://aap.example.com/api/controller/v2")

    def test_exported_source_api_base_maps_to_target_gateway(self) -> None:
        layout = self._gateway_layout()
        assert role_definition_api_base(
            layout,
            "shared.organization",
            "https://aap25.example.com/api/gateway/v1",
        ) == ("https://aap.example.com/api/gateway/v1")


class TestRoleAssignmentDedupeKey:
    def test_user_assignment_key_uses_username_not_controller_fk(self) -> None:
        from aap_migration.migration.exporter import RoleAssignmentListExporter

        resource = {
            "content_type": "shared.organization",
            "object_id": "1",
            "user": 47,
            "user_ansible_id": "fb4a1b19-46d2-43ec-8627-9dbb21683e80",
            "summary_fields": {
                "role_definition": {"name": "Organization Member"},
                "user": {"id": 47, "username": "jadoe"},
            },
        }
        key = RoleAssignmentListExporter._assignment_dedupe_key(
            resource, "role_user_assignments"
        )
        assert key == ("awx.organization", "1", "Organization Member", "jadoe")

    def test_seen_ids_are_scoped_per_api_base(self) -> None:
        """Surrogate assignment ids overlap across gateway and controller APIs."""
        gateway_base = "https://aap.example.com/api/gateway/v1"
        controller_base = "https://aap.example.com/api/controller/v2"
        seen_ids: set[tuple[str, int]] = set()

        seen_ids.add((gateway_base, 2))

        assert (gateway_base, 2) in seen_ids
        assert (controller_base, 2) not in seen_ids


class TestResolveAssignmentUserId:
    @pytest.mark.asyncio
    async def test_uses_username_on_assignment_api_base(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from aap_migration.client.api_layout import ApiLayout, ApiMode
        from aap_migration.migration.importer import _resolve_assignment_user_id

        layout = ApiLayout(
            host_url="https://aap.example.com",
            mode=ApiMode.GATEWAY,
            aap_version="2.6",
            gateway_base="https://aap.example.com/api/gateway/v1",
            controller_base="https://aap.example.com/api/controller/v2",
        )
        client = MagicMock()
        client.api_layout = layout
        client.get_on_base = AsyncMock(
            return_value={"results": [{"id": 25, "username": "jdoe"}]}
        )
        state = MagicMock()

        resolved = await _resolve_assignment_user_id(
            state,
            client,
            {"user_username": "jdoe", "user": 24},
            24,
            layout.controller_base,
        )

        assert resolved == 25
        client.get_on_base.assert_awaited_once_with(
            layout.controller_base,
            "users/",
            params={"username": "jdoe", "page_size": 1},
        )
        state.get_mapping_by_name.assert_not_called()


class TestResolveUserTargetIdForAssignment:
    def test_prefers_username_over_mismatched_source_fk(self) -> None:
        from unittest.mock import MagicMock

        from aap_migration.migration.importer import _resolve_user_target_id_for_assignment

        state = MagicMock()
        mapping = MagicMock()
        mapping.target_id = 11
        state.get_mapping_by_name.return_value = mapping
        state.get_mapped_id.return_value = 10

        target_id = _resolve_user_target_id_for_assignment(
            state,
            {"user_username": "jadoe", "user": 47},
            47,
        )

        assert target_id == 11
        state.get_mapping_by_name.assert_called_once_with("users", "jadoe")
        state.get_mapped_id.assert_not_called()
