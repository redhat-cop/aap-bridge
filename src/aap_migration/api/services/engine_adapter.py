import os

from aap_migration.api.models import Connection
from aap_migration.api.services.token_crypto import decrypt_token
from aap_migration.client.api_layout import normalize_host_url
from aap_migration.config import (
    AAPInstanceConfig,
    MigrationConfig,
    StateConfig,
    load_config_tuning_from_yaml,
    normalize_aap_version,
)


def connection_to_aap_config(conn: Connection) -> AAPInstanceConfig:
    """Map a saved Web UI connection to runtime AAP instance settings."""
    if not conn.version or not conn.version.strip():
        raise ValueError(
            f"Connection '{conn.name}' has no AAP version. "
            "Set the AAP version on the connection."
        )

    return AAPInstanceConfig(
        url=normalize_host_url(conn.url),
        token=decrypt_token(conn.token),
        version=normalize_aap_version(conn.version),
        verify_ssl=conn.verify_ssl,
        timeout=30,
    )


def load_runtime_config(source: Connection, dest: Connection, db_url: str) -> MigrationConfig:
    """Build ``MigrationConfig`` for Web UI workflows.

    Instance URLs, tokens, and AAP versions come from saved connections, not
    from ``SOURCE__*`` / ``TARGET__*`` in ``.env``. Export/transform tuning and
    other non-instance settings are still loaded from ``AAP_BRIDGE_CONFIG`` when
    set. CLI and TUI commands continue to use ``load_config_from_yaml`` instead.
    """
    tuning: dict = {}
    config_path = os.environ.get("AAP_BRIDGE_CONFIG")
    if config_path:
        tuning = load_config_tuning_from_yaml(config_path)

    config = MigrationConfig(
        source=connection_to_aap_config(source),
        target=connection_to_aap_config(dest),
        **tuning,
    )
    config.state = StateConfig(db_path=db_url)
    return config


def build_migration_config(source: Connection, dest: Connection, db_url: str) -> MigrationConfig:
    return load_runtime_config(source, dest, db_url)
