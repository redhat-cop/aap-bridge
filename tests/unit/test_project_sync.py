"""Unit tests for project SCM sync waiting and follow-up behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.cli.commands.patch_projects import _retry_project_sync
from aap_migration.cli.context import MigrationContext
from aap_migration.migration.importer import wait_for_project_sync


@pytest.mark.asyncio
async def test_wait_for_project_sync_timeout_keeps_in_progress_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    client.get.return_value = {
        "scm_type": "git",
        "status": "running",
        "name": "demo",
    }

    times = iter([0.0, 0.0, 11.0])
    monkeypatch.setattr("time.time", lambda: next(times))

    async def immediate_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "aap_migration.migration.importer.asyncio.sleep",
        immediate_sleep,
    )

    synced, failed_count, failed_ids, in_progress_ids = await wait_for_project_sync(
        client=client,
        project_ids=[42],
        timeout=10,
        poll_interval=10,
    )

    assert synced == 0
    assert failed_count == 0
    assert failed_ids == []
    assert in_progress_ids == [42]


@pytest.mark.asyncio
async def test_retry_project_sync_does_not_trigger_update_when_running() -> None:
    ctx = MagicMock(spec=MigrationContext)
    ctx.target_client = AsyncMock()
    ctx.target_client.get.return_value = {
        "scm_type": "git",
        "status": "running",
        "name": "demo",
    }

    still_unfinished, recovered = await _retry_project_sync(
        ctx=ctx,
        failed_ids=[42],
        timeout=1,
        poll_interval=1,
    )

    ctx.target_client.post.assert_not_called()
    assert recovered == []
    assert still_unfinished == [42]
