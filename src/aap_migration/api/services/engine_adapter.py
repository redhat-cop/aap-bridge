import os
from collections.abc import Iterator
from contextlib import contextmanager

from aap_migration.api.models import Connection
from aap_migration.api.services.token_crypto import decrypt_token
from aap_migration.config import (
    AAPInstanceConfig,
    MigrationConfig,
    StateConfig,
    load_config_from_yaml,
)


def connection_to_aap_config(conn: Connection) -> AAPInstanceConfig:
    api_prefix = (
        conn.api_prefix
        if conn.api_prefix is not None
        else ("/api/v2" if conn.type == "awx" else "/api/controller/v2")
    )
    url = conn.url.rstrip("/") + api_prefix

    return AAPInstanceConfig(
        url=url,
        token=decrypt_token(conn.token),
        verify_ssl=conn.verify_ssl,
        timeout=30,
    )


def _connection_env(prefix: str, conn: Connection) -> dict[str, str]:
    return {
        f"{prefix}__URL": connection_to_aap_config(conn).url,
        f"{prefix}__TOKEN": decrypt_token(conn.token) or "",
        f"{prefix}__VERIFY_SSL": str(conn.verify_ssl).lower(),
        f"{prefix}__TIMEOUT": "30",
    }


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    original: dict[str, str | None] = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, original_value in original.items():
            saved_value = original_value
            if saved_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved_value


def load_runtime_config(source: Connection, dest: Connection, db_url: str) -> MigrationConfig:
    config_path = os.environ.get("AAP_BRIDGE_CONFIG")
    if config_path:
        overrides = {}
        overrides.update(_connection_env("SOURCE", source))
        overrides.update(_connection_env("TARGET", dest))
        with _temporary_env(overrides):
            config = load_config_from_yaml(config_path)
    else:
        config = MigrationConfig(
            source=connection_to_aap_config(source),
            target=connection_to_aap_config(dest),
        )

    config.source = connection_to_aap_config(source)
    config.target = connection_to_aap_config(dest)
    config.state = StateConfig(db_path=db_url)
    return config


def build_migration_config(source: Connection, dest: Connection, db_url: str) -> MigrationConfig:
    return load_runtime_config(source, dest, db_url)
