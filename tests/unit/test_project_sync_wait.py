from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.migration.importer import wait_for_project_sync


@pytest.mark.asyncio
async def test_wait_for_project_sync_ignores_stale_failed_until_active() -> None:
    """After POST update/, project status may still show the previous failed job."""
    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            {"id": 1, "name": "proj-a", "scm_type": "git", "status": "failed"},
            {"id": 1, "name": "proj-a", "scm_type": "git", "status": "running"},
            {"id": 1, "name": "proj-a", "scm_type": "git", "status": "successful"},
        ]
    )

    synced, failed, failed_ids = await wait_for_project_sync(
        client,
        [1],
        timeout=60,
        poll_interval=0,
        ignore_stale_failure=True,
    )

    assert synced == 1
    assert failed == 0
    assert failed_ids == []
    assert client.get.await_count == 3


@pytest.mark.asyncio
async def test_wait_for_project_sync_stale_failed_without_ignore_is_immediate() -> None:
    client = MagicMock()
    client.get = AsyncMock(
        return_value={"id": 2, "name": "proj-b", "scm_type": "git", "status": "failed"},
    )

    synced, failed, failed_ids = await wait_for_project_sync(
        client,
        [2],
        timeout=60,
        poll_interval=0,
    )

    assert synced == 0
    assert failed == 1
    assert failed_ids == [2]


@pytest.mark.asyncio
async def test_wait_for_project_sync_timeout_uses_sync_timeout_not_batch_interval() -> None:
    """Projects still running when timeout expires count as failed."""
    client = MagicMock()
    client.get = AsyncMock(
        return_value={"id": 3, "name": "proj-c", "scm_type": "git", "status": "running"},
    )

    synced, failed, failed_ids = await wait_for_project_sync(
        client,
        [3],
        timeout=0,
        poll_interval=0,
        ignore_stale_failure=True,
    )

    assert synced == 0
    assert failed == 1
    assert failed_ids == [3]
