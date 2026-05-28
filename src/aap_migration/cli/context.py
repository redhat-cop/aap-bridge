"""
CLI context manager for AAP Bridge.

This module provides the context object that is passed to all CLI commands,
containing configuration, clients, and state management.
"""

from dataclasses import dataclass, field
from pathlib import Path

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.client.vault_client import VaultClient
from aap_migration.config import AAPInstanceConfig, MigrationConfig, load_config_from_yaml
from aap_migration.migration.state import MigrationState
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MigrationContext:
    """
    Context object for CLI commands.

    This object holds configuration, clients, and state that is shared
    across CLI commands. It is passed via Click's context mechanism.

    Attributes:
        config_path: Path to configuration file
        log_level: Logging level
        log_file: Optional log file path
        config: Loaded migration configuration
        source_client: Client for source AAP instance
        target_client: Client for target AAP instance
        migration_state: State tracker for migration
    """

    config_path: Path | None = None
    log_level: str = "INFO"
    log_file: Path | None = None

    # Version information
    source_version: str | None = None
    target_version: str | None = None

    # Optional single-organization migration scope (CLI or config)
    organization: str | None = None

    # Lazy-loaded attributes
    _config: MigrationConfig | None = field(default=None, init=False, repr=False)
    _source_client: AAPSourceClient | None = field(default=None, init=False, repr=False)
    _target_client: AAPTargetClient | None = field(default=None, init=False, repr=False)
    _vault_client: VaultClient | None = field(default=None, init=False, repr=False)
    _migration_state: MigrationState | None = field(default=None, init=False, repr=False)

    @property
    def config(self) -> MigrationConfig:
        """Get or load migration configuration."""
        if self._config is None:
            if self.config_path is None:
                raise ValueError(
                    "Configuration file path not provided. "
                    "Use --config option or set AAP_MIGRATE_CONFIG environment variable."
                )

            logger.debug("Loading configuration", config_path=str(self.config_path))
            self._config = load_config_from_yaml(self.config_path)
            logger.debug("Configuration loaded successfully")

        return self._config

    @property
    def vault_client(self) -> VaultClient:
        """Get or create Vault client."""
        if self._vault_client is None:
            if self.config.vault is None:
                raise ValueError(
                    "Vault configuration is required when token_vault_path is set. "
                    "Add a [vault] section to your configuration."
                )
            logger.debug("Creating Vault client", url=self.config.vault.url)
            self._vault_client = VaultClient(self.config.vault)
            logger.debug("Vault client created")

        return self._vault_client

    def _resolve_token(self, instance_config: AAPInstanceConfig, label: str) -> str:
        """Resolve API token for an AAP instance.

        Precedence: token_vault_path (fail-fast) > plain token.
        """
        if instance_config.token_vault_path:
            logger.info(
                "resolving_token_from_vault",
                instance=label,
                path=instance_config.token_vault_path,
            )
            secret = self.vault_client.read_secret(instance_config.token_vault_path)
            token = secret.get("token")
            if not token:
                raise ValueError(
                    f"Vault secret at '{instance_config.token_vault_path}' "
                    f"does not contain a 'token' key. "
                    f"Available keys: {list(secret.keys())}"
                )
            logger.info("token_resolved_from_vault", instance=label)
            return str(token)

        if instance_config.token:
            return instance_config.token

        # Should not reach here due to model validator, but defensive
        raise ValueError(f"No token source configured for {label}")

    @property
    def source_client(self) -> AAPSourceClient:
        """Get or create source AAP client."""
        if self._source_client is None:
            logger.debug("Creating source client", url=self.config.source.url)
            resolved_token = self._resolve_token(self.config.source, "source")
            # Create a copy of the config with the resolved token
            source_config = self.config.source.model_copy(update={"token": resolved_token})
            self._source_client = AAPSourceClient(
                config=source_config,
                rate_limit=self.config.performance.rate_limit,
                log_payloads=self.config.logging.log_payloads,
                max_payload_size=self.config.logging.max_payload_size,
                max_connections=self.config.performance.http_max_connections,
                max_keepalive_connections=self.config.performance.http_max_keepalive_connections,
            )
            logger.debug("Source client created")

        return self._source_client

    @property
    def target_client(self) -> AAPTargetClient:
        """Get or create target AAP client."""
        if self._target_client is None:
            logger.debug("Creating target client", url=self.config.target.url)
            resolved_token = self._resolve_token(self.config.target, "target")
            # Create a copy of the config with the resolved token
            target_config = self.config.target.model_copy(update={"token": resolved_token})
            self._target_client = AAPTargetClient(
                config=target_config,
                rate_limit=self.config.performance.rate_limit,
                log_payloads=self.config.logging.log_payloads,
                max_payload_size=self.config.logging.max_payload_size,
                max_connections=self.config.performance.http_max_connections,
                max_keepalive_connections=self.config.performance.http_max_keepalive_connections,
            )
            logger.debug("Target client created")

        return self._target_client

    @property
    def migration_state(self) -> MigrationState:
        """Get or create migration state tracker."""
        if self._migration_state is None:
            logger.debug(
                "Initializing migration state",
                db_path=str(self.config.state.db_path),
            )
            self._migration_state = MigrationState(
                config=self.config.state,
            )
            logger.debug("Migration state initialized")

        return self._migration_state

    def cleanup(self) -> None:
        """Clean up resources."""
        logger.debug("Cleaning up context resources")

        # Close clients if created
        if self._source_client is not None:
            logger.debug("Closing source client")
            # Add cleanup if needed

        if self._target_client is not None:
            logger.debug("Closing target client")
            # Add cleanup if needed

        if self._vault_client is not None:
            logger.debug("Closing Vault client")
            self._vault_client.close()

        # Migration state cleanup handled by context manager
        logger.debug("Context cleanup complete")

    def __enter__(self) -> "MigrationContext":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.cleanup()
