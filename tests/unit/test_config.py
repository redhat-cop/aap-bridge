"""Unit tests for configuration module."""

import pytest
from pydantic import ValidationError

from aap_migration.config import (
    AAPInstanceConfig,
    MigrationConfig,
    VaultConfig,
    load_config_tuning_from_yaml,
    normalize_aap_version,
)


class TestAAPInstanceConfig:
    """Tests for AAPInstanceConfig."""

    def test_valid_config_token_only(self):
        """Test valid AAP instance configuration with plain token."""
        config = AAPInstanceConfig(
            url="https://aap.example.com",
            token="test-token",
            verify_ssl=True,
            timeout=30,
        )

        assert config.url == "https://aap.example.com"
        assert config.token == "test-token"
        assert config.token_vault_path is None
        assert config.verify_ssl is True
        assert config.timeout == 30

    def test_valid_config_vault_path_only(self):
        """Test valid AAP instance configuration with Vault path."""
        config = AAPInstanceConfig(
            url="https://aap.example.com",
            token_vault_path="source/token",
            verify_ssl=True,
            timeout=30,
        )

        assert config.url == "https://aap.example.com"
        assert config.token is None
        assert config.token_vault_path == "source/token"

    def test_valid_config_both_token_and_vault(self):
        """Test valid configuration with both provided."""
        config = AAPInstanceConfig(
            url="https://aap.example.com",
            token="test-token",
            token_vault_path="source/token",
        )
        assert config.token == "test-token"
        assert config.token_vault_path == "source/token"

    def test_invalid_config_neither_token_nor_vault(self):
        """Test validation fails when neither is provided."""
        with pytest.raises(
            ValidationError, match="Either 'token' or 'token_vault_path' must be provided"
        ):
            AAPInstanceConfig(
                url="https://aap.example.com",
            )

    def test_url_validation_no_scheme(self):
        """Test URL validation rejects URLs without scheme."""
        with pytest.raises(ValidationError, match="must start with"):
            AAPInstanceConfig(
                url="aap.example.com",
                token="test-token",
            )

    def test_url_validation_http(self):
        """Test URL validation requires HTTPS."""
        with pytest.raises(ValidationError, match="should use HTTPS"):
            AAPInstanceConfig(
                url="http://aap.example.com",
                token="test-token",
            )

    def test_url_normalization(self):
        """Test URL trailing slash is removed."""
        config = AAPInstanceConfig(
            url="https://aap.example.com/",
            token="test-token",
        )

        assert config.url == "https://aap.example.com"

    def test_url_strips_legacy_api_path(self):
        """Test legacy API path suffixes are stripped from configured URLs."""
        config = AAPInstanceConfig(
            url="https://aap.example.com/api/controller/v2",
            token="test-token",
        )

        assert config.url == "https://aap.example.com"

    def test_version_normalization(self):
        """Test AAP version is normalized to major.minor."""
        config = AAPInstanceConfig(
            url="https://aap.example.com",
            token="test-token",
            version="2.5.1",
        )

        assert config.version == "2.5"

    def test_invalid_version_rejected(self):
        """Test placeholder or malformed versions are rejected."""
        with pytest.raises(ValidationError, match="Invalid AAP version"):
            AAPInstanceConfig(
                url="https://aap.example.com",
                token="test-token",
                version="2.x",
            )


class TestNormalizeAapVersion:
    def test_valid_versions(self):
        assert normalize_aap_version("2.6") == "2.6"
        assert normalize_aap_version("2.6.20260325") == "2.6"

    def test_invalid_version(self):
        with pytest.raises(ValueError, match="Invalid AAP version"):
            normalize_aap_version("2.x")


def _minimal_migration_config(**overrides) -> MigrationConfig:
    source = AAPInstanceConfig(
        url="https://source.example.com",
        token="source-token",
        version="2.4",
    )
    target = AAPInstanceConfig(
        url="https://target.example.com",
        token="target-token",
        version="2.6",
    )
    data = {"source": source, "target": target}
    data.update(overrides)
    return MigrationConfig(**data)


class TestMigrationConfigVersions:
    def test_requires_source_version(self):
        source = AAPInstanceConfig(
            url="https://source.example.com",
            token="source-token",
        )
        target = AAPInstanceConfig(
            url="https://target.example.com",
            token="target-token",
            version="2.6",
        )
        with pytest.raises(ValidationError, match="Source AAP version is required"):
            MigrationConfig(source=source, target=target)

    def test_requires_target_version(self):
        source = AAPInstanceConfig(
            url="https://source.example.com",
            token="source-token",
            version="2.4",
        )
        target = AAPInstanceConfig(
            url="https://target.example.com",
            token="target-token",
        )
        with pytest.raises(ValidationError, match="Target AAP version is required"):
            MigrationConfig(source=source, target=target)

    def test_accepts_valid_versions(self):
        config = _minimal_migration_config()
        assert config.source.version == "2.4"
        assert config.target.version == "2.6"


class TestVaultConfig:
    """Tests for VaultConfig."""

    def test_valid_config(self):
        """Test valid Vault configuration."""
        config = VaultConfig(
            url="https://vault.example.com:8200",
            role_id="test-role",
            secret_id="test-secret",
            namespace="test",
            mount_point="aap",
            path_prefix="credentials",
            verify_ssl=False,
        )

        assert config.url == "https://vault.example.com:8200"
        assert config.role_id == "test-role"
        assert config.secret_id == "test-secret"
        assert config.namespace == "test"
        assert config.mount_point == "aap"
        assert config.path_prefix == "credentials"
        assert config.verify_ssl is False

    def test_defaults(self):
        """Test Vault default configuration."""
        config = VaultConfig(
            url="https://vault.example.com:8200",
            role_id="test-role",
            secret_id="test-secret",
        )

        assert config.mount_point == "secret"
        assert config.path_prefix == "aap"
        assert config.verify_ssl is True

    def test_path_prefix_normalization(self):
        """Test path prefix removes leading/trailing slashes."""
        config = VaultConfig(
            url="https://vault.example.com:8200",
            role_id="test-role",
            secret_id="test-secret",
            path_prefix="/secret/aap/",
        )

        assert config.path_prefix == "secret/aap"


def test_load_config_tuning_from_yaml_omits_instances(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
source:
  url: ${SOURCE__URL}
  token: ${SOURCE__TOKEN}
  version: ${SOURCE__VERSION}
target:
  url: ${TARGET__URL}
  token: ${TARGET__TOKEN}
  version: ${TARGET__VERSION}
paths:
  base_dir: .
  export_dir: exports
export:
  skip_credential_names:
    - demo
""".strip()
    )

    tuning = load_config_tuning_from_yaml(config_file)

    assert "source" not in tuning
    assert "target" not in tuning
    assert tuning["paths"]["export_dir"] == "exports"
    assert tuning["export"]["skip_credential_names"] == ["demo"]

