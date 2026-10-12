"""Artifact paths resolve against the workspace, not the working directory.

Regression tests for a migration whose exports, schemas, and transformed files
landed in whichever directory the command happened to be run from, while its
configuration was read from the workspace. One migration ended up split across
the disk, and ``doctor`` reported empty artifact directories that were empty
only because the real ones were somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aap_migration.config import PathConfig

_DIR_FIELDS = ("export_dir", "transform_dir", "schema_dir", "report_dir", "backup_dir")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workspace directory, with the process running somewhere else entirely."""
    root = tmp_path / "workspace"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("source: {}\n")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("AAP_BRIDGE_WORKSPACE", str(root))
    return root


def test_relative_directories_anchor_to_the_workspace(workspace: Path) -> None:
    paths = PathConfig()

    for field in _DIR_FIELDS:
        value = Path(getattr(paths, field))
        assert value.is_absolute()
        assert value.parent == workspace, f"{field} escaped the workspace"


def test_relative_files_anchor_to_the_workspace(workspace: Path) -> None:
    paths = PathConfig()

    assert Path(paths.mappings_file) == workspace / "config" / "mappings.yaml"
    assert Path(paths.ignored_endpoints_file) == workspace / "config" / "ignored_endpoints.yaml"


def test_absolute_paths_are_left_alone(workspace: Path) -> None:
    """An explicit absolute path means what it says, workspace or not."""
    paths = PathConfig(export_dir="/mnt/big/exports")

    assert paths.export_dir == "/mnt/big/exports"


def test_base_dir_redirects_everything_below_it(workspace: Path, tmp_path: Path) -> None:
    """base_dir is the anchor for the rest, and can point outside the workspace."""
    elsewhere = tmp_path / "scratch"
    paths = PathConfig(base_dir=str(elsewhere))

    assert Path(paths.export_dir) == elsewhere / "exports"
    assert Path(paths.schema_dir) == elsewhere / "schemas"


def test_a_later_chdir_does_not_move_the_migration(workspace: Path, tmp_path: Path) -> None:
    """Resolution happens once, at load, so a command that changes directory
    mid-run cannot start writing somewhere else."""
    paths = PathConfig()
    before = paths.export_dir

    moved = tmp_path / "moved"
    moved.mkdir()
    os.chdir(moved)

    assert paths.export_dir == before
