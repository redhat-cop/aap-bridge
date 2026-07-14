"""Unit tests for instance group name export helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.client.api_layout import ApiLayout, ApiMode
from aap_migration.migration.exporter import (
    _attach_instance_group_names,
    _fetch_instance_group_names,
)


@pytest.mark.asyncio
async def test_fetch_instance_group_names_preserves_order():
    client = MagicMock()
    client.api_layout = ApiLayout(host_url="https://aap", mode=ApiMode.LEGACY, aap_version="2.4", legacy_base="https://aap/api/v2")
    client.get_paginated = AsyncMock(
        return_value=[
            {"id": 3, "name": "Custom Instance Group 1"},
            {"id": 4, "name": "Custom Instance Group 2"},
            {"id": 5, "name": "Container Group 1"},
        ]
    )

    names = await _fetch_instance_group_names(client, "organizations", 2)

    assert names == [
        "Custom Instance Group 1",
        "Custom Instance Group 2",
        "Container Group 1",
    ]
    client.get_paginated.assert_called_once_with(
        "organizations/2/instance_groups/", page_size=200
    )


@pytest.mark.asyncio
async def test_fetch_instance_group_names_on_error_returns_empty():
    client = MagicMock()
    client.api_layout = ApiLayout(host_url="https://aap", mode=ApiMode.LEGACY, aap_version="2.4", legacy_base="https://aap/api/v2")
    client.get_paginated = AsyncMock(side_effect=RuntimeError("boom"))

    names = await _fetch_instance_group_names(client, "inventory", 23)

    assert names == []


@pytest.mark.asyncio
async def test_attach_instance_group_names():
    client = MagicMock()
    client.api_layout = ApiLayout(host_url="https://aap", mode=ApiMode.LEGACY, aap_version="2.4", legacy_base="https://aap/api/v2")
    client.get_paginated = AsyncMock(
        return_value=[{"id": 3, "name": "Custom Instance Group 1"}]
    )
    resource = {"id": 38, "name": "Demo JT"}

    await _attach_instance_group_names(client, resource, "job_templates")

    assert resource["_instance_group_names"] == ["Custom Instance Group 1"]


@pytest.mark.asyncio
async def test_fetch_organization_instance_groups_uses_controller_on_gateway():
    """Org capacity links are on controller, not gateway."""
    client = MagicMock()
    client.api_layout = ApiLayout(
        host_url="https://aap.example.com",
        mode=ApiMode.GATEWAY,
        aap_version="2.5",
        gateway_base="https://aap.example.com/api/gateway/v1",
        controller_base="https://aap.example.com/api/controller/v2",
    )
    client.get_paginated = AsyncMock()
    client.get_on_base = AsyncMock(
        side_effect=[
            # name lookup on controller
            {"count": 1, "results": [{"id": 2, "name": "Org With Instance Group"}]},
            # instance_groups page
            {
                "count": 2,
                "next": None,
                "results": [
                    {"id": 3, "name": "Custom Instance Group 1"},
                    {"id": 4, "name": "Custom Instance Group 2"},
                ],
            },
        ]
    )

    names = await _fetch_instance_group_names(
        client,
        "organizations",
        99,  # gateway org id
        resource_name="Org With Instance Group",
    )

    assert names == ["Custom Instance Group 1", "Custom Instance Group 2"]
    client.get_paginated.assert_not_called()
    assert client.get_on_base.await_count == 2
    client.get_on_base.assert_any_await(
        "https://aap.example.com/api/controller/v2",
        "organizations/",
        params={"name": "Org With Instance Group", "page_size": 1},
    )
    client.get_on_base.assert_any_await(
        "https://aap.example.com/api/controller/v2",
        "organizations/2/instance_groups/",
        params={"page": 1, "page_size": 200},
    )
