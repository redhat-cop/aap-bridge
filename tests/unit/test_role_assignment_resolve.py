from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.client.api_layout import ApiLayout, ApiMode
from aap_migration.migration.importer import _resolve_rbac_principal_id_for_assignment


@pytest.mark.asyncio
async def test_resolve_rbac_principal_uses_username_on_controller_base() -> None:
    state = MagicMock()
    state.get_mapped_id.return_value = 2
    state.get_mapping_source_name.return_value = "demo-user"

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
        side_effect=[
            {"results": [{"id": 7, "username": "demo-user"}]},
        ]
    )

    resolved = await _resolve_rbac_principal_id_for_assignment(
        state,
        client,
        "users",
        4,
        layout.controller_base,
    )

    assert resolved == 7
    client.get_on_base.assert_awaited_once_with(
        layout.controller_base,
        "users/",
        params={"username": "demo-user", "page_size": 1},
    )


@pytest.mark.asyncio
async def test_resolve_rbac_principal_legacy_uses_mapping() -> None:
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

    resolved = await _resolve_rbac_principal_id_for_assignment(
        state,
        client,
        "users",
        3,
        layout.legacy_base,
    )

    assert resolved == 5
    state.get_mapping_source_name.assert_not_called()
