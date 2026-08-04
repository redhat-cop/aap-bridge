"""Regression: Phase 2 patching must report patched counts (#116)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aap_migration.cli.commands.patch_projects import (
    _empty_patch_stats,
    patch_project_scm_details,
)


def test_empty_patch_stats_shape() -> None:
    assert _empty_patch_stats() == {
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "total": 0,
    }


@pytest.mark.asyncio
async def test_patch_returns_zeros_when_no_projects_dir(tmp_path: Path) -> None:
    ctx = MagicMock()
    stats = await patch_project_scm_details(ctx, tmp_path, batch_size=1, interval=0)
    assert stats == _empty_patch_stats()


@pytest.mark.asyncio
async def test_patch_returns_patched_count(tmp_path: Path) -> None:
    """Successful patches must populate run_stats-compatible imported count."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "projects_001.json").write_text(
        """[
          {
            "name": "demo",
            "_source_id": 10,
            "_deferred_scm_details": {
              "scm_type": "git",
              "scm_url": "https://example.com/repo.git",
              "scm_branch": "main"
            }
          }
        ]"""
    )

    ctx = MagicMock()
    ctx.migration_state.get_mapped_id = MagicMock(return_value=99)
    ctx.target_client.patch = AsyncMock(return_value={})
    ctx.config.performance.project_sync_max_retries = 0
    ctx.config.performance.project_sync_fail_on_sync_failure = False
    ctx.config.performance.project_sync_poll_interval = 0
    ctx.config.performance.project_sync_timeout = 1

    with (
        patch(
            "aap_migration.cli.commands.patch_projects.wait_for_project_sync",
            new_callable=AsyncMock,
            return_value=(1, 0, []),
        ),
        patch("aap_migration.cli.commands.patch_projects.asyncio.sleep", new_callable=AsyncMock),
        patch("aap_migration.cli.commands.patch_projects.MigrationProgressDisplay"),
    ):
        stats = await patch_project_scm_details(ctx, tmp_path, batch_size=1, interval=0)

    assert stats["imported"] == 1
    assert stats["failed"] == 0
    assert stats["skipped"] == 0
    assert stats["total"] == 1
    ctx.target_client.patch.assert_awaited_once()
