"""Unit tests for MigrationContext token resolution."""

from unittest.mock import MagicMock, patch

import pytest

from aap_migration.cli.context import MigrationContext
from aap_migration.config import AAPInstanceConfig, MigrationConfig, VaultConfig


@pytest.fixture
def mock_config():
    """Create a mock MigrationConfig."""
    source = AAPInstanceConfig(
        url="https://source.example.com",
        token="plain-source-token",
        version="2.4",
    )
    target = AAPInstanceConfig(
        url="https://target.example.com",
        token="plain-target-token",
        version="2.6",
    )
    vault = VaultConfig(
        url="https://vault.example.com:8200",
        role_id="role",
        secret_id="secret",
    )

    config = MagicMock(spec=MigrationConfig)
    config.source = source
    config.target = target
    config.vault = vault
    config.performance = MagicMock()
    config.performance.rate_limit = 20
    config.performance.http_max_connections = 50
    config.performance.http_max_keepalive_connections = 20
    config.logging = MagicMock()
    config.logging.log_payloads = False
    config.logging.max_payload_size = 10000

    return config


class TestMigrationContext:
    """Tests for MigrationContext."""

    def test_resolve_token_plain(self, mock_config):
        """Test resolving a plain token."""
        ctx = MigrationContext()
        ctx._config = mock_config

        token = ctx._resolve_token(mock_config.source, "source")
        assert token == "plain-source-token"

    @patch("aap_migration.cli.context.VaultClient")
    def test_resolve_token_vault(self, mock_vault_class, mock_config):
        """Test resolving a token from Vault."""
        mock_vault = mock_vault_class.return_value
        mock_vault.read_secret.return_value = {"token": "vault-resolved-token"}

        mock_config.source.token_vault_path = "source/token"

        ctx = MigrationContext()
        ctx._config = mock_config

        token = ctx._resolve_token(mock_config.source, "source")

        assert token == "vault-resolved-token"
        mock_vault.read_secret.assert_called_once_with("source/token")

    @patch("aap_migration.cli.context.VaultClient")
    def test_resolve_token_vault_missing_key(self, mock_vault_class, mock_config):
        """Test resolution fails if 'token' key is missing in Vault secret."""
        mock_vault = mock_vault_class.return_value
        mock_vault.read_secret.return_value = {"something": "else"}

        mock_config.source.token_vault_path = "source/token"

        ctx = MigrationContext()
        ctx._config = mock_config

        with pytest.raises(ValueError, match="does not contain a 'token' key"):
            ctx._resolve_token(mock_config.source, "source")

    def test_resolve_token_no_vault_config(self, mock_config):
        """Test resolution fails if vault_path is set but no vault config exists."""
        mock_config.vault = None
        mock_config.source.token_vault_path = "source/token"

        ctx = MigrationContext()
        ctx._config = mock_config

        with pytest.raises(ValueError, match="Vault configuration is required"):
            ctx._resolve_token(mock_config.source, "source")

    @patch("aap_migration.cli.context.AAPSourceClient")
    def test_source_client_lazy_initialization_with_vault(self, mock_source_class, mock_config):
        """Test source client initialization resolves token from Vault."""
        mock_config.source.token_vault_path = "source/token"

        ctx = MigrationContext()
        ctx._config = mock_config

        # Mock _resolve_token to return a specific token
        with patch.object(ctx, "_resolve_token", return_value="vault-token") as mock_resolve:
            client = ctx.source_client

            mock_resolve.assert_called_once_with(mock_config.source, "source")
            # Verify super().__init__ (via AAPSourceClient) would get the resolved token
            # We check the config passed to the constructor
            args, kwargs = mock_source_class.call_args
            passed_config = kwargs["config"]
            assert passed_config.token == "vault-token"
            assert client == mock_source_class.return_value
