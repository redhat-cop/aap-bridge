import pytest
from pydantic import ValidationError

from aap_migration.api.schemas import ConnectionCreate, ConnectionUpdate


def test_connection_create_requires_https_url():
    with pytest.raises(ValidationError, match="URL should use HTTPS for security"):
        ConnectionCreate(
            name="Source",
            role="source",
            url="http://aap.example.com",
            version="2.4",
            token="token",
        )


def test_connection_update_rejects_blank_name():
    with pytest.raises(ValidationError):
        ConnectionUpdate(name="")


def test_connection_update_allows_https_url():
    update = ConnectionUpdate(url="https://aap.example.com/api/controller/v2")

    assert update.url == "https://aap.example.com/api/controller/v2"


def test_connection_create_accepts_source_or_destination_role():
    source = ConnectionCreate(
        name="Source",
        role="source",
        url="https://aap.example.com",
        version="2.4",
        token="token",
    )
    destination = ConnectionCreate(
        name="Destination",
        role="destination",
        url="https://aap26.example.com",
        version="2.6",
        token="token",
    )

    assert source.role == "source"
    assert destination.role == "destination"
