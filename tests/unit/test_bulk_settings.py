"""Tests for target bulk settings helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.client.bulk_settings import (
    BULK_HOST_MAX_CREATE_DEFAULT,
    effective_host_batch_size,
    fetch_bulk_host_max_create,
)


class TestEffectiveHostBatchSize:
    def test_respects_configured_size(self):
        assert effective_host_batch_size(50) == 50

    def test_caps_at_api_max(self):
        assert effective_host_batch_size(500) == 200

    def test_caps_at_target_setting(self):
        assert effective_host_batch_size(200, target_bulk_max=100) == 100

    def test_target_cap_wins_over_config_when_lower(self):
        assert effective_host_batch_size(150, target_bulk_max=100) == 100

    def test_minimum_is_one(self):
        assert effective_host_batch_size(0, target_bulk_max=0) == 1


@pytest.mark.asyncio
async def test_fetch_bulk_host_max_create_reads_setting():
    client = MagicMock()
    client.get = AsyncMock(return_value={"BULK_HOST_MAX_CREATE": 100})
    assert await fetch_bulk_host_max_create(client) == 100
    client.get.assert_awaited_once_with("settings/bulk/")


@pytest.mark.asyncio
async def test_fetch_bulk_host_max_create_defaults_when_missing():
    client = MagicMock()
    client.get = AsyncMock(return_value={})
    assert await fetch_bulk_host_max_create(client) == BULK_HOST_MAX_CREATE_DEFAULT


@pytest.mark.asyncio
async def test_fetch_bulk_host_max_create_returns_none_on_error():
    client = MagicMock()
    client.get = AsyncMock(side_effect=ConnectionError("unavailable"))
    assert await fetch_bulk_host_max_create(client) is None
