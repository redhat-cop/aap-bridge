"""Phase 2 pauses between batches, not after the last one.

Regression test for three silent minutes added to every Phase 2 run. The pause
that keeps back-to-back SCM syncs from overwhelming the controller ran after
*every* batch, including the final one. At its original five seconds nobody
noticed; once it became the configurable ``project_patch_batch_interval``
(default 180s), a migration with fewer projects than one batch - the common
case - sat on a frozen progress display for three minutes with nothing left to
do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aap_migration.cli.commands import patch_projects
from aap_migration.reporting.live_progress import MigrationProgressDisplay


def _write_projects(input_dir: Path, count: int) -> None:
    """Write ``count`` transformed projects, each awaiting SCM activation."""
    projects_dir = input_dir / "projects"
    projects_dir.mkdir(parents=True)
    resources = [
        {
            "_source_id": i,
            "name": f"project_{i}",
            "_deferred_scm_details": {"scm_type": "git", "scm_url": "https://example.com/r.git"},
        }
        for i in range(1, count + 1)
    ]
    (projects_dir / "projects_0.json").write_text(json.dumps(resources))


def _context() -> MagicMock:
    """A migration context with the settings Phase 2 reads and a stub client."""
    ctx = MagicMock()
    performance = ctx.config.performance
    performance.project_sync_max_retries = 0
    performance.project_sync_fail_on_sync_failure = False
    performance.project_sync_poll_interval = 1
    performance.project_sync_timeout = 60
    ctx.migration_state.get_mapped_id.side_effect = lambda _type, source_id: source_id + 100
    ctx.target_client.patch = AsyncMock(return_value={})
    # Phase 2 inspects each target project before patching; a project whose SCM
    # does not match yet is the case these tests are about.
    ctx.target_client.get = AsyncMock(return_value={"scm_type": "", "status": "never updated"})
    return ctx


async def _run(tmp_path: Path, project_count: int, batch_size: int) -> list[Any]:
    """Run Phase 2 and return the arguments of each inter-batch pause."""
    _write_projects(tmp_path, project_count)
    pauses: list[Any] = []

    async def record_pause(_progress: Any, seconds: int, *_a: Any, **_kw: Any) -> None:
        pauses.append(seconds)

    with (
        patch.object(patch_projects, "_pause_between_batches", side_effect=record_pause),
        patch.object(
            patch_projects, "wait_for_project_sync", AsyncMock(return_value=(0, 0, [], []))
        ),
    ):
        await patch_projects.patch_project_scm_details(
            _context(),
            tmp_path,
            batch_size=batch_size,
            interval=180,
            # A disabled display keeps the test off the terminal.
            progress_display=MigrationProgressDisplay(enabled=False),
        )
    return pauses


@pytest.mark.asyncio
async def test_single_batch_does_not_pause(tmp_path: Path) -> None:
    """Fewer projects than one batch: nothing follows, so nothing to wait for."""
    assert await _run(tmp_path, project_count=3, batch_size=100) == []


@pytest.mark.asyncio
async def test_pause_happens_between_batches_only(tmp_path: Path) -> None:
    """Three batches means two gaps, not three."""
    assert await _run(tmp_path, project_count=3, batch_size=1) == [180, 180]


@pytest.mark.asyncio
async def test_final_batch_never_pauses_when_it_is_partial(tmp_path: Path) -> None:
    """A trailing partial batch is still the last one."""
    assert await _run(tmp_path, project_count=5, batch_size=2) == [180, 180]


@pytest.mark.asyncio
async def test_pause_counts_down_on_the_progress_row() -> None:
    """The wait says what it is waiting for, so it cannot be read as a hang."""
    display = MigrationProgressDisplay(enabled=False)
    notes: list[str] = []
    display.set_phase_note = lambda _phase, note: notes.append(note)  # type: ignore[method-assign]

    with patch.object(patch_projects.asyncio, "sleep", AsyncMock()):
        await patch_projects._pause_between_batches(display, 12)

    assert notes[0] == "next batch in 12s"
    assert notes[-1] == "", "the note must be cleared once the wait is over"
    assert len(notes) > 2, "a countdown, not a single message"
