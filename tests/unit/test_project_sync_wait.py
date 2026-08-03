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

    synced, failed, failed_ids, in_progress_ids = await wait_for_project_sync(
        client,
        [1],
        timeout=60,
        poll_interval=0,
        ignore_stale_failure=True,
    )

    assert synced == 1
    assert failed == 0
    assert failed_ids == []
    assert in_progress_ids == []
    assert client.get.await_count == 3


@pytest.mark.asyncio
async def test_wait_for_project_sync_stale_failed_without_ignore_is_immediate() -> None:
    client = MagicMock()
    client.get = AsyncMock(
        return_value={"id": 2, "name": "proj-b", "scm_type": "git", "status": "failed"},
    )

    synced, failed, failed_ids, in_progress_ids = await wait_for_project_sync(
        client,
        [2],
        timeout=60,
        poll_interval=0,
    )

    assert synced == 0
    assert failed == 1
    assert failed_ids == [2]
    assert in_progress_ids == []


@pytest.mark.asyncio
async def test_wait_for_project_sync_timeout_keeps_running_as_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Projects still running when timeout expires stay in-progress, not failed."""
    client = MagicMock()
    client.get = AsyncMock(
        return_value={"id": 3, "name": "proj-c", "scm_type": "git", "status": "running"},
    )

    times = iter([0.0, 0.0, 11.0])
    monkeypatch.setattr("time.time", lambda: next(times))

    async def immediate_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "aap_migration.migration.importer.asyncio.sleep",
        immediate_sleep,
    )

    synced, failed, failed_ids, in_progress_ids = await wait_for_project_sync(
        client,
        [3],
        timeout=10,
        poll_interval=10,
        ignore_stale_failure=True,
    )

    assert synced == 0
    assert failed == 0
    assert failed_ids == []
    assert in_progress_ids == [3]
