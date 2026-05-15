import pytest
from pydantic import ValidationError

from aap_migration.api.schemas import ConnectionCreate, ConnectionUpdate


def test_connection_create_requires_https_url():
    with pytest.raises(ValidationError, match="URL should use HTTPS for security"):
        ConnectionCreate(
            name="Source",
            type="awx",
            role="source",
            url="http://awx.example.com",
            token="token",
        )


def test_connection_update_rejects_blank_name():
    with pytest.raises(ValidationError):
        ConnectionUpdate(name="")


def test_connection_update_allows_https_url():
    update = ConnectionUpdate(url="https://aap.example.com/api/controller/v2")

    assert update.url == "https://aap.example.com/api/controller/v2"


def test_connection_create_rejects_awx_destination():
    with pytest.raises(ValidationError, match="AWX connections can only use the source role"):
        ConnectionCreate(
            name="AWX dest",
            type="awx",
            role="destination",
            url="https://awx.example.com",
            token="token",
        )


def test_connection_update_rejects_awx_destination_when_type_and_role_are_set():
    with pytest.raises(ValidationError, match="AWX connections can only use the source role"):
        ConnectionUpdate(type="awx", role="destination")
