"""Unit tests for web connection api_layout helpers."""

import pytest

from aap_migration.api.models import Connection
from aap_migration.api.services.connection_layout import resolve_connection_version
from aap_migration.client.api_layout import (
    CONTROLLER_API_PREFIX,
    GATEWAY_API_PREFIX,
)


@pytest.mark.parametrize(
    ("conn_kwargs", "expected_version"),
    [
        ({"type": "aap", "role": "source", "version": "2.3.5"}, "2.3"),
        ({"type": "aap", "role": "destination", "version": "2.6.1"}, "2.6"),
        ({"type": "aap", "role": "source", "api_prefix": "/api/v2"}, "2.4"),
        (
            {"type": "aap", "role": "destination", "api_prefix": CONTROLLER_API_PREFIX},
            "2.6",
        ),
    ],
)
def test_resolve_connection_version(conn_kwargs: dict, expected_version: str) -> None:
    conn = Connection(
        name="test",
        url="https://aap.example.com",
        token="token",
        verify_ssl=True,
        **conn_kwargs,
    )
    assert resolve_connection_version(conn) == expected_version
