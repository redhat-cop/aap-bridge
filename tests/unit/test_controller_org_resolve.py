from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.client.api_layout import ApiLayout, ApiMode
from aap_migration.migration.importer import (
    CredentialImporter,
    ResourceImporter,
    _resolve_organization_id_for_controller,
)


@pytest.mark.asyncio
async def test_resolve_organization_uses_name_on_controller_base() -> None:
    state = MagicMock()
    state.get_mapped_id.return_value = 7
    state.get_mapping_source_name.return_value = "TestOrg-3"

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
        return_value={"results": [{"id": 36, "name": "TestOrg-3"}]},
    )

    resolved = await _resolve_organization_id_for_controller(
        state,
        client,
        4,
        layout.controller_base,
    )

    assert resolved == 36
    client.get_on_base.assert_awaited_once_with(
        layout.controller_base,
        "organizations/",
        params={"name": "TestOrg-3", "page_size": 1},
    )


@pytest.mark.asyncio
async def test_resolve_organization_legacy_uses_mapping() -> None:
    state = MagicMock()
    state.get_mapped_id.return_value = 5

    layout = ApiLayout(
        host_url="https://aap.example.com",
        mode=ApiMode.LEGACY,
        aap_version="1.0",
        legacy_base="https://aap.example.com/api/v2",
    )
    client = MagicMock()
    client.api_layout = layout

    resolved = await _resolve_organization_id_for_controller(
        state,
        client,
        3,
        layout.legacy_base,
    )

    assert resolved == 5
    state.get_mapping_source_name.assert_not_called()


@pytest.mark.asyncio
async def test_credential_importer_resolves_controller_org_by_name(
    mock_client, mock_state, performance_config
) -> None:
    layout = ApiLayout(
        host_url="https://aap.example.com",
        mode=ApiMode.GATEWAY,
        aap_version="2.6",
        gateway_base="https://aap.example.com/api/gateway/v1",
        controller_base="https://aap.example.com/api/controller/v2",
    )
    mock_client.api_layout = layout
    mock_client.get_on_base = AsyncMock(
        return_value={"results": [{"id": 36, "name": "TestOrg-3"}]},
    )
    mock_state.get_mapped_id.side_effect = lambda rt, sid: 7 if rt == "organizations" else None
    mock_state.get_mapping_source_name.return_value = "TestOrg-3"

    importer = CredentialImporter(mock_client, mock_state, performance_config)
    resolved = await importer._resolve_dependencies(
        "credentials",
        {
            "name": "cred-in-org3",
            "organization": 4,
            "credential_type": 1,
        },
    )

    assert resolved["organization"] == 36


@pytest.mark.asyncio
async def test_resource_importer_gateway_org_unchanged_for_teams(
    mock_client, mock_state, performance_config
) -> None:
    layout = ApiLayout(
        host_url="https://aap.example.com",
        mode=ApiMode.GATEWAY,
        aap_version="2.6",
        gateway_base="https://aap.example.com/api/gateway/v1",
        controller_base="https://aap.example.com/api/controller/v2",
    )
    mock_client.api_layout = layout
    mock_state.get_mapped_id.return_value = 7

    importer = ResourceImporter(mock_client, mock_state, performance_config)
    importer.DEPENDENCIES = {"organization": "organizations"}

    resolved = await importer._resolve_dependencies(
        "teams",
        {"name": "team-a", "organization": 4},
    )

    assert resolved["organization"] == 7
    mock_client.get_on_base.assert_not_called()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_on_base = AsyncMock()
    return client


@pytest.fixture
def mock_state():
    state = MagicMock()
    state.get_mapped_id = MagicMock(return_value=None)
    state.get_mapping_source_name = MagicMock(return_value=None)
    return state


@pytest.fixture
def performance_config():
    from aap_migration.config import PerformanceConfig

    return PerformanceConfig()
