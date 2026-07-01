"""Unit tests for web connection AAP client helpers."""

from aap_migration.api.models import Connection
from aap_migration.api.services.connection_client import (
    create_connection_client,
)
from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.client.api_layout import CONTROLLER_API_PREFIX, GATEWAY_API_PREFIX


def _connection(**kwargs) -> Connection:
    defaults = {
        "name": "AAP",
        "type": "aap",
        "url": "https://aap.example.com",
        "token": "token",
        "verify_ssl": True,
        "version": "2.6",
    }
    defaults.update(kwargs)
    return Connection(**defaults)


def test_create_connection_client_uses_target_for_destination() -> None:
    client = create_connection_client(_connection(role="destination"))

    assert isinstance(client, AAPTargetClient)
    assert client._build_url("organizations/") == (
        f"https://aap.example.com{GATEWAY_API_PREFIX}/organizations/"
    )
    assert client._build_url("projects/") == (
        f"https://aap.example.com{CONTROLLER_API_PREFIX}/projects/"
    )


def test_create_connection_client_uses_source_for_source_role() -> None:
    client = create_connection_client(_connection(role="source", version="2.4"))

    assert isinstance(client, AAPSourceClient)
    assert client._build_url("organizations/").endswith("/api/v2/organizations/")


