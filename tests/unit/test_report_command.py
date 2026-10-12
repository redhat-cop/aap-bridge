"""`aap-bridge report` writes a real report, into the workspace's reports/.

Two regressions in one command. The statistics block was a literal of zeros -
the state database was opened and then never asked anything - so every report
described a migration of nothing, in three formats. And ``--output`` was
required, so ``paths.report_dir`` was read by no code at all and the
workspace's reports/ stayed empty however many migrations ran.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from aap_migration.cli.commands.validate import report


def _context(tmp_path: Path) -> MagicMock:
    """A context whose state reports a small but non-empty migration."""
    ctx = MagicMock()
    ctx.config.paths.report_dir = str(tmp_path / "reports")
    ctx.config.source.url = "https://source.example.com"
    ctx.config.target.url = "https://target.example.com"

    state = ctx.migration_state
    state.migration_id = "test-migration"
    state.get_overall_stats.return_value = {
        "total_mappings": 9,
        "total_progress": 7,
        "total_completed": 6,
        "total_failed": 1,
        "resource_counts": {"hosts": 4, "inventory": 2},
    }
    state.get_all_resource_types.return_value = ["hosts", "inventory", "untouched"]
    state.get_migration_stats.side_effect = lambda rtype: {
        "hosts": {"total": 5, "completed": 4, "failed": 1, "skipped": 0},
        "inventory": {"total": 2, "completed": 2, "failed": 0, "skipped": 0},
        "untouched": {"total": 0, "completed": 0, "failed": 0, "skipped": 0},
    }[rtype]
    state.get_failures.return_value = [
        {
            "resource_type": "hosts",
            "source_id": 42,
            "source_name": "web-01",
            "phase": "import",
            "error": "duplicate name",
            "retry_count": 1,
        }
    ]
    state.get_all_mappings.return_value = [
        {
            "resource_type": "inventory",
            "source_id": 1,
            "target_id": 101,
            "source_name": "Prod",
            "target_name": "Prod",
        }
    ]
    return ctx


def _run(ctx: MagicMock, *args: str) -> Any:
    result = CliRunner().invoke(report, list(args), obj=ctx)
    assert result.exit_code == 0, result.output
    return result


def test_default_output_lands_in_the_workspace_reports_directory(tmp_path: Path) -> None:
    ctx = _context(tmp_path)

    _run(ctx)

    written = list((tmp_path / "reports").glob("migration-report-*.html"))
    assert len(written) == 1, "one report, named for when it was generated"


def test_explicit_output_still_wins(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    destination = tmp_path / "elsewhere.json"

    _run(ctx, "--output", str(destination))

    assert destination.is_file()
    assert not (tmp_path / "reports").exists()


def test_statistics_come_from_the_state_database(tmp_path: Path) -> None:
    """The numbers that used to be hardcoded zeros."""
    ctx = _context(tmp_path)
    destination = tmp_path / "report.json"

    _run(ctx, "--output", str(destination))

    data = json.loads(destination.read_text())
    assert data["statistics"] == {
        "total_resources_migrated": 6,
        "total_resources_tracked": 7,
        "resource_types": 2,
        "id_mappings": 9,
        "failed": 1,
    }
    assert data["generated_at"], "a report has to say when it was generated"


def test_resource_types_with_nothing_tracked_are_left_out(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    destination = tmp_path / "report.json"

    _run(ctx, "--output", str(destination))

    by_type = json.loads(destination.read_text())["resources_by_type"]
    assert set(by_type) == {"hosts", "inventory"}
    assert by_type["hosts"]["failed"] == 1


@pytest.mark.parametrize("fmt,suffix", [("json", "json"), ("markdown", "md"), ("html", "html")])
def test_failures_and_mappings_are_rendered_when_asked_for(
    tmp_path: Path, fmt: str, suffix: str
) -> None:
    ctx = _context(tmp_path)
    destination = tmp_path / f"report.{suffix}"

    _run(ctx, "--output", str(destination), "--format", fmt, "--include-mappings")

    body = destination.read_text()
    assert "web-01" in body, "the failed resource is named"
    assert "duplicate name" in body, "and so is the reason"
    assert "Prod" in body, "requested mappings appear"


def test_mappings_are_left_out_unless_requested(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    destination = tmp_path / "report.json"

    _run(ctx, "--output", str(destination))

    assert json.loads(destination.read_text())["mappings"] is None
    ctx.migration_state.get_all_mappings.assert_not_called()
