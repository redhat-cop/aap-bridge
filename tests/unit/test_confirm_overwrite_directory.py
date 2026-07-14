"""Tests for CLI directory overwrite confirmation."""

from pathlib import Path
from unittest.mock import patch

from aap_migration.cli.utils import confirm_overwrite_directory


def test_confirm_overwrite_directory_skips_empty_mount_point(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    assert confirm_overwrite_directory(export_dir, force=False, yes=False) is True


def test_confirm_overwrite_directory_prompts_when_populated(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    (export_dir / "metadata.json").write_text("{}")

    with patch("click.confirm", return_value=False) as confirm:
        assert confirm_overwrite_directory(export_dir) is False
        confirm.assert_called_once()


def test_confirm_overwrite_directory_yes_skips_prompt(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    (export_dir / "metadata.json").write_text("{}")

    with patch("click.confirm") as confirm:
        assert confirm_overwrite_directory(export_dir, yes=True) is True
        confirm.assert_not_called()
