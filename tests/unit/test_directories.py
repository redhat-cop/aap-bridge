"""Tests for migration artifact directory helpers."""

from pathlib import Path

from aap_migration.utils.directories import (
    clear_directory_contents,
    clear_export_transform_directories,
    directory_has_contents,
)


def test_directory_has_contents_false_for_missing_or_empty(tmp_path: Path) -> None:
    assert not directory_has_contents(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not directory_has_contents(empty)


def test_directory_has_contents_true_when_populated(tmp_path: Path) -> None:
    populated = tmp_path / "exports"
    populated.mkdir()
    (populated / "metadata.json").write_text("{}")
    assert directory_has_contents(populated)


def test_clear_directory_contents_preserves_mount_point(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    nested = export_dir / "organizations"
    nested.mkdir()
    (nested / "organizations_0001.json").write_text("[]")
    (export_dir / "metadata.json").write_text("{}")

    clear_directory_contents(export_dir)

    assert export_dir.is_dir()
    assert not directory_has_contents(export_dir)


def test_clear_export_transform_directories_honors_skip(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    xformed = tmp_path / "xformed"
    exports.mkdir()
    xformed.mkdir()
    (exports / "metadata.json").write_text("{}")
    (xformed / "metadata.json").write_text("{}")

    cleared = clear_export_transform_directories(
        exports,
        xformed,
        skip=frozenset({"exports"}),
    )

    assert cleared == ["xformed"]
    assert directory_has_contents(exports)
    assert not directory_has_contents(xformed)


def test_clear_export_transform_directories_skips_empty_dirs(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    xformed = tmp_path / "xformed"
    exports.mkdir()
    xformed.mkdir()

    assert clear_export_transform_directories(exports, xformed) == []
