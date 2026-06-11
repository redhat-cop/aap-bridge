"""Unit tests for configuration module."""

import pytest
from pydantic import ValidationError

from aap_migration.config import (
    AAPInstanceConfig,
    VaultConfig,
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
