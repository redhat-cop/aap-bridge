"""Tests for dual-base custom role definition export."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.migration.exporter import RoleDefinitionExporter


@pytest.mark.asyncio
async def test_export_parallel_queries_controller_not_only_gateway() -> None:
    """CLI export uses export_parallel; custom roles must come from controller."""
    gateway_base = "https://aap.example.com/api/gateway/v1"
    controller_base = "https://aap.example.com/api/controller/v2"

    layout = MagicMock()
    layout.role_assignment_bases.return_value = (gateway_base, controller_base)

    client = MagicMock()
    client.api_layout = layout

    async def fake_get_on_base(base: str, endpoint: str, params: dict | None = None):
        if base == gateway_base:
            return {"count": 0, "results": [], "next": None}
        if base == controller_base:
            return {
                "count": 1,
                "results": [
                    {
                        "id": 38,
                        "name": "My Custom Role",
                        "managed": False,
                        "content_type": "awx.project",
                        "permissions": ["awx.view_project"],
                    }
                ],
                "next": None,
            }
        raise AssertionError(f"unexpected base {base}")

    client.get_on_base = AsyncMock(side_effect=fake_get_on_base)

    perf = MagicMock()
    perf.batch_sizes = {"role_definitions": 50}
    exporter = RoleDefinitionExporter(client, MagicMock(), perf)
    exported = [
        item
        async for item in exporter.export_parallel(
            resource_type="role_definitions",
            endpoint="role_definitions/",
        )
    ]

    assert len(exported) == 1
    assert exported[0]["name"] == "My Custom Role"
    assert exported[0]["_api_base"] == controller_base
