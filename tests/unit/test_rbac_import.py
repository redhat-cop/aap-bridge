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

    def test_exported_source_api_base_maps_to_target_gateway(self) -> None:
        layout = self._gateway_layout()
        assert role_definition_api_base(
            layout,
            "shared.organization",
            "https://aap25.example.com/api/gateway/v1",
        ) == ("https://aap.example.com/api/gateway/v1")
