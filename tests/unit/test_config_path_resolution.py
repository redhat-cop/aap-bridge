"""Tests for configuration path resolution."""

from pathlib import Path

from aap_migration.config import find_project_root, resolve_config_path


def test_find_project_root_from_repo() -> None:
    root = find_project_root(Path(__file__).resolve().parents[2])
    assert (root / "pyproject.toml").is_file()


def test_resolve_config_path_from_subdirectory() -> None:
    repo_root = find_project_root(Path(__file__).resolve().parents[2])
    resolved = resolve_config_path("config/config.yaml")
    assert resolved == (repo_root / "config" / "config.yaml").resolve()
