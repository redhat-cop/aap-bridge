"""Tests for configuration path resolution."""

import os
from pathlib import Path

import pytest

from aap_migration.config import (
    _drop_missing_env_keys,
    _expand_env_vars,
    _unwrap_env_results,
    find_env_file,
    find_project_root,
    find_workspace_root,
    resolve_config_path,
)


def test_find_project_root_from_repo() -> None:
    root = find_project_root(Path(__file__).resolve().parents[2])
    assert (root / "pyproject.toml").is_file()


def test_resolve_config_path_from_subdirectory() -> None:
    repo_root = find_project_root(Path(__file__).resolve().parents[2])
    resolved = resolve_config_path("config/config.yaml")
    assert resolved == (repo_root / "config" / "config.yaml").resolve()


# ---------------------------------------------------------------------------
# Workspace discovery (source-free installs)
# ---------------------------------------------------------------------------


def test_find_workspace_root_matches_repo_checkout() -> None:
    """A source checkout is still anchored by pyproject.toml."""
    repo_root = find_project_root(Path(__file__).resolve().parents[2])
    assert find_workspace_root(Path(__file__).resolve().parent) == repo_root


def test_find_workspace_root_anchors_on_env_file(tmp_path: Path) -> None:
    """A directory holding only .env is a valid workspace."""
    (tmp_path / ".env").write_text("SOURCE__URL=https://example.com\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_workspace_root(nested) == tmp_path


def test_find_workspace_root_anchors_on_generated_config(tmp_path: Path) -> None:
    """A workspace created by `aap-bridge init` is found from a subdirectory."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("source: {}\n")
    nested = tmp_path / "exports"
    nested.mkdir()
    assert find_workspace_root(nested) == tmp_path


def test_find_workspace_root_falls_back_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty directory is still usable; init populates it in place."""
    # Isolate HOME so a real ~/aap-migration on the machine running the tests
    # cannot win the default-workspace fallback ahead of the start directory.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AAP_BRIDGE_WORKSPACE", raising=False)
    assert find_workspace_root(tmp_path) == tmp_path.resolve()


def test_find_workspace_root_uses_default_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """$HOME/aap-migration is found from an unrelated directory.

    This is what lets `aap-bridge` run without a `cd` into the workspace.
    """
    home = tmp_path / "home"
    workspace = home / "aap-migration"
    (workspace / "config").mkdir(parents=True)
    (workspace / "config" / "config.yaml").write_text("source: {}\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AAP_BRIDGE_WORKSPACE", raising=False)
    assert find_workspace_root(elsewhere) == workspace


def test_find_workspace_root_honours_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AAP_BRIDGE_WORKSPACE wins over both the walk and the default."""
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    monkeypatch.setenv("AAP_BRIDGE_WORKSPACE", str(chosen))
    assert find_workspace_root(tmp_path) == chosen.resolve()


def test_find_env_file_prefers_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "custom.env"
    explicit.write_text("SOURCE__URL=https://example.com\n")
    (tmp_path / ".env").write_text("SOURCE__URL=https://wrong.example.com\n")
    monkeypatch.setenv("AAP_BRIDGE_ENV", str(explicit))
    assert find_env_file(tmp_path) == explicit


def test_find_env_file_returns_none_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AAP_BRIDGE_ENV", raising=False)
    monkeypatch.delenv("AAP_BRIDGE_WORKSPACE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert find_env_file(tmp_path) is None


# ---------------------------------------------------------------------------
# Unset ${VAR} references must fall back to model defaults
# ---------------------------------------------------------------------------


def _render(data: dict[str, object]) -> object:
    """Run a config fragment through the expand -> drop -> unwrap pipeline."""
    return _unwrap_env_results(_drop_missing_env_keys(_expand_env_vars(data)))


def test_missing_env_key_is_dropped_not_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset ${VAR} must be removed so Pydantic applies the field default.

    Passing None instead would override the default and fail validation.
    """
    monkeypatch.delenv("SOURCE__VERIFY_SSL", raising=False)
    monkeypatch.setenv("SOURCE__URL", "https://source.example.com")

    result = _render({"source": {"url": "${SOURCE__URL}", "verify_ssl": "${SOURCE__VERIFY_SSL}"}})

    assert result == {"source": {"url": "https://source.example.com"}}


def test_resolved_env_keys_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE__URL", "https://source.example.com")
    monkeypatch.setenv("SOURCE__TIMEOUT", "45")

    result = _render({"source": {"url": "${SOURCE__URL}", "timeout": "${SOURCE__TIMEOUT}"}})

    assert result == {"source": {"url": "https://source.example.com", "timeout": "45"}}


def test_yaml_literals_survive_dropping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain YAML values are untouched; only unset ${VAR} keys are removed."""
    monkeypatch.delenv("VAULT__URL", raising=False)

    result = _render({"vault": {"url": "${VAULT__URL}", "mount_point": "aap"}})

    assert result == {"vault": {"mount_point": "aap"}}


def test_minimal_env_produces_valid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A workspace config with only source/target/state loads successfully.

    This is what `aap-bridge init` writes. Before unset keys were dropped, the
    absence of SOURCE__VERIFY_SSL / SOURCE__TIMEOUT failed validation.
    """
    from aap_migration.config import load_config_from_yaml

    for var in ("SOURCE__VERIFY_SSL", "SOURCE__TIMEOUT", "TARGET__VERIFY_SSL", "TARGET__TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SOURCE__URL", "https://source.example.com")
    monkeypatch.setenv("SOURCE__VERSION", "2.4")
    monkeypatch.setenv("SOURCE__TOKEN", "xxxxx")
    monkeypatch.setenv("TARGET__URL", "https://target.example.com")
    monkeypatch.setenv("TARGET__VERSION", "2.6")
    monkeypatch.setenv("TARGET__TOKEN", "xxxxx")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "source:\n"
        "  url: ${SOURCE__URL}\n"
        "  version: ${SOURCE__VERSION}\n"
        "  verify_ssl: ${SOURCE__VERIFY_SSL}\n"
        "  timeout: ${SOURCE__TIMEOUT}\n"
        "target:\n"
        "  url: ${TARGET__URL}\n"
        "  version: ${TARGET__VERSION}\n"
        "  verify_ssl: ${TARGET__VERIFY_SSL}\n"
        "  timeout: ${TARGET__TIMEOUT}\n"
    )

    config = load_config_from_yaml(config_file)

    assert config.source.url == "https://source.example.com"
    assert config.source.verify_ssl is True  # model default, not None
    assert config.source.timeout == 30
    assert config.target.url == "https://target.example.com"


def test_env_var_expansion_unaffected_by_os_environ_pollution() -> None:
    """Sanity check that the helpers read os.environ at expansion time."""
    key = "AAP_BRIDGE_TEST_ONLY_VAR"
    os.environ[key] = "present"
    try:
        assert _render({"k": f"${{{key}}}"}) == {"k": "present"}
    finally:
        del os.environ[key]
