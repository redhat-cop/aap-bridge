"""Tests for connection URL normalization and encrypted token handling."""

from datetime import UTC, datetime

import pytest
from aap_migration.api.models import Connection
from aap_migration.api.schemas import ConnectionCreate, ConnectionUpdate
from aap_migration.api.services.connection_service import (
    MASKED_TOKEN,
    ConnectionService,
    normalize_connection_url,
    split_connection_url,
)
from aap_migration.api.services.engine_adapter import connection_to_aap_config
from aap_migration.api.services.platform_adapter import PlatformAdapter
from aap_migration.api.services.token_crypto import (
    ENCRYPTED_TOKEN_PREFIX,
    TOKEN_ENCRYPTION_KEY_ENV,
    decrypt_token,
    encrypt_token,
)
from aap_migration.migration.models import Base
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class TestNormalizeConnectionUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://localhost:20947", "https://localhost:20947"),
            ("https://localhost:20947/", "https://localhost:20947"),
            (
                "https://localhost:20947/api/controller/v2",
                "https://localhost:20947",
            ),
            (
                "https://localhost:20947/api/controller/v2/",
                "https://localhost:20947",
            ),
            ("https://awx.example.com/api/v2", "https://awx.example.com"),
            (
                "https://aap.example.com/gateway/api/controller/v2/",
                "https://aap.example.com/gateway",
            ),
        ],
    )
    def test_strips_known_api_suffixes(self, url: str, expected: str):
        assert normalize_connection_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected_url", "expected_prefix"),
    [
        ("https://localhost:20947", "https://localhost:20947", None),
        (
            "https://localhost:20947/api/controller/v2",
            "https://localhost:20947",
            "/api/controller/v2",
        ),
        ("https://awx.example.com/api/v2", "https://awx.example.com", "/api/v2"),
    ],
)
def test_split_connection_url_preserves_explicit_api_prefix(
    url: str, expected_url: str, expected_prefix: str | None
):
    assert split_connection_url(url) == (expected_url, expected_prefix)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_encrypt_decrypt_round_trip(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())

    encrypted = encrypt_token("super-secret-token")

    assert encrypted is not None
    assert encrypted.startswith(ENCRYPTED_TOKEN_PREFIX)
    assert decrypt_token(encrypted) == "super-secret-token"


def test_legacy_plaintext_token_passthrough():
    assert decrypt_token("legacy-plaintext-token") == "legacy-plaintext-token"


def test_create_preserves_explicit_api_prefix(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)

    conn = service.create(
        ConnectionCreate(
            name="AAP gateway",
            type="aap",
            role="destination",
            url="https://localhost:20947/api/v2",
            token="token",
            verify_ssl=False,
        )
    )

    assert conn.url == "https://localhost:20947"
    assert conn.api_prefix == "/api/v2"


def test_create_stores_encrypted_token(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)

    conn = service.create(
        ConnectionCreate(
            name="AAP gateway",
            type="aap",
            role="destination",
            url="https://localhost:20947/api/v2",
            token="token",
            verify_ssl=False,
        )
    )

    assert conn.token is not None
    assert conn.token != "token"
    assert conn.token.startswith(ENCRYPTED_TOKEN_PREFIX)
    assert service.get_token(conn) == "token"
    assert conn.url == "https://localhost:20947"
    assert conn.api_prefix == "/api/v2"


def test_update_clears_stale_discovery_metadata(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)
    conn = service.create(
        ConnectionCreate(
            name="AAP gateway",
            type="aap",
            role="destination",
            url="https://localhost:20947/api/controller/v2",
            token="token",
            verify_ssl=False,
        )
    )
    conn.version = "2.5"
    conn.ping_status = "ok"
    conn.auth_status = "ok"
    conn.last_checked = datetime.now(UTC)
    db_session.commit()

    updated = service.update(
        conn.id,
        ConnectionUpdate(
            type="awx",
            role="source",
            url="https://awx.example.com/api/v2",
        ),
    )

    assert updated is not None
    assert updated.url == "https://awx.example.com"
    assert updated.api_prefix == "/api/v2"
    assert updated.version is None
    assert updated.ping_status == "unknown"
    assert updated.auth_status == "unknown"
    assert updated.last_checked is None


def test_update_token_resets_only_auth_metadata(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)
    conn = service.create(
        ConnectionCreate(
            name="AAP gateway",
            type="aap",
            role="destination",
            url="https://localhost:20947/api/controller/v2",
            token="token",
            verify_ssl=False,
        )
    )
    conn.version = "2.5"
    conn.ping_status = "ok"
    conn.auth_status = "ok"
    conn.auth_error = "old-auth-error"
    conn.last_checked = datetime.now(UTC)
    db_session.commit()

    updated = service.update(conn.id, ConnectionUpdate(token="new-token"))

    assert updated is not None
    assert updated.version == "2.5"
    assert updated.ping_status == "ok"
    assert updated.auth_status == "unknown"
    assert updated.auth_error is None
    assert updated.last_checked is None


def test_update_preserves_masked_token(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)
    conn = service.create(
        ConnectionCreate(
            name="AAP gateway",
            type="aap",
            role="destination",
            url="https://localhost:20947/api/controller/v2",
            token="super-secret-token",
            verify_ssl=False,
        )
    )
    original_token = conn.token

    updated = service.update(
        conn.id,
        ConnectionUpdate(
            name="AAP renamed",
            token=MASKED_TOKEN,
        ),
    )

    assert updated is not None
    assert updated.name == "AAP renamed"
    assert updated.token == original_token
    assert service.get_token(updated) == "super-secret-token"


def test_update_encrypts_replaced_token(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)
    conn = service.create(
        ConnectionCreate(
            name="AAP gateway",
            type="aap",
            role="destination",
            url="https://localhost:20947/api/controller/v2",
            token="old-token",
            verify_ssl=False,
        )
    )
    original_token = conn.token

    updated = service.update(
        conn.id,
        ConnectionUpdate(token="new-token"),
    )

    assert updated is not None
    assert updated.token is not None
    assert updated.token != original_token
    assert updated.token.startswith(ENCRYPTED_TOKEN_PREFIX)
    assert service.get_token(updated) == "new-token"


def test_failed_connection_test_preserves_existing_api_prefix(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)
    conn = service.create(
        ConnectionCreate(
            name="AAP gateway",
            type="aap",
            role="destination",
            url="https://localhost:20947/api/controller/v2",
            token="token",
            verify_ssl=False,
        )
    )

    class FakeResponse:
        status_code = 503

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr("aap_migration.api.services.connection_service.httpx.get", lambda *args, **kwargs: FakeResponse())

    result = service.test_connection(conn)

    assert result.ok is False
    assert conn.api_prefix == "/api/controller/v2"


def test_engine_adapter_decrypts_encrypted_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    conn = Connection(
        name="AAP gateway",
        type="aap",
        role="destination",
        url="https://localhost:20947/api/controller/v2",
        token=encrypt_token("token"),
        verify_ssl=False,
        api_prefix="",
    )

    config = connection_to_aap_config(conn)

    assert config.url == "https://localhost:20947/api/controller/v2"
    assert config.token == "token"


def test_platform_adapter_decrypts_encrypted_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    conn = Connection(
        name="AAP gateway",
        type="aap",
        role="destination",
        url="https://localhost:20947/api/controller/v2",
        token=encrypt_token("token"),
        verify_ssl=False,
        api_prefix="",
    )

    adapter = PlatformAdapter(conn)

    assert adapter.base_url == "https://localhost:20947/api/controller/v2"
    assert adapter.headers["Authorization"] == "Bearer token"


class DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_test_connection_uses_decrypted_token(db_session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(TOKEN_ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    service = ConnectionService(db_session)
    conn = Connection(
        name="AAP gateway",
        type="aap",
        role="destination",
        url="https://localhost:20947",
        token=encrypt_token("token"),
        verify_ssl=False,
    )
    auth_headers: list[dict[str, str]] = []

    def fake_get(url: str, **kwargs) -> DummyResponse:
        if url.endswith("/ping/"):
            return DummyResponse(200, {"version": "2.6"})
        auth_headers.append(kwargs["headers"])
        return DummyResponse(200, {})

    monkeypatch.setattr("aap_migration.api.services.connection_service.httpx.get", fake_get)

    result = service.test_connection(conn)

    assert result.ok is True
    assert auth_headers == [{"Authorization": "Bearer token"}]
