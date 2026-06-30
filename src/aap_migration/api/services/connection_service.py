from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from aap_migration.api.models import Connection
from aap_migration.api.schemas import ConnectionCreate, ConnectionUpdate, TestResult
from aap_migration.api.services.connection_layout import (
    me_probe_url,
    normalize_connection_url,
    ping_probe_candidates,
    resolve_connection_version,
    split_connection_url,
    validate_connection_version,
)

__all__ = [
    "ConnectionService",
    "MASKED_TOKEN",
    "normalize_connection_url",
    "split_connection_url",
]
from aap_migration.api.services.token_crypto import decrypt_token, encrypt_token
from aap_migration.client.api_layout import parse_aap_major_minor

MASKED_TOKEN = "********"
CONNECTION_TYPE_AAP = "aap"


class ConnectionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, data: ConnectionCreate) -> Connection:
        normalized_url, api_prefix = split_connection_url(data.url)
        version = validate_connection_version(data.role, data.version)
        conn = Connection(
            name=data.name,
            type=CONNECTION_TYPE_AAP,
            role=data.role,
            url=normalized_url,
            token=encrypt_token(data.token),
            verify_ssl=data.verify_ssl,
            api_prefix=api_prefix,
            version=version,
        )
        self.db.add(conn)
        self.db.commit()
        self.db.refresh(conn)
        return conn

    def list_all(self) -> list[Connection]:
        return self.db.query(Connection).order_by(Connection.name).all()

    def get(self, connection_id: str) -> Connection | None:
        return self.db.query(Connection).filter(Connection.id == connection_id).first()

    @staticmethod
    def get_token(conn: Connection) -> str | None:
        return decrypt_token(conn.token)

    def update(self, connection_id: str, data: ConnectionUpdate) -> Connection | None:
        conn = self.get(connection_id)
        if not conn:
            return None
        update_data = data.model_dump(exclude_unset=True)
        if update_data.get("token") in ("", MASKED_TOKEN):
            update_data.pop("token", None)
        elif "token" in update_data:
            update_data["token"] = encrypt_token(update_data["token"])
        discovery_needs_reset = False
        if "url" in update_data and update_data["url"]:
            normalized_url, api_prefix = split_connection_url(update_data["url"])
            update_data["url"] = normalized_url
            update_data["api_prefix"] = api_prefix
            discovery_needs_reset = True

        if discovery_needs_reset:
            update_data.update(
                {
                    "ping_status": "unknown",
                    "ping_error": None,
                    "auth_status": "unknown",
                    "auth_error": None,
                    "last_checked": None,
                }
            )

        role = update_data.get("role", conn.role)
        if "version" in update_data and update_data["version"] is not None:
            update_data["version"] = validate_connection_version(role, update_data["version"])
        elif "role" in update_data and conn.version:
            update_data["version"] = validate_connection_version(role, conn.version)
        for key, value in update_data.items():
            setattr(conn, key, value)
        self.db.commit()
        self.db.refresh(conn)
        return conn

    def delete(self, connection_id: str) -> bool:
        conn = self.get(connection_id)
        if not conn:
            return False
        self.db.delete(conn)
        self.db.commit()
        return True

    def test_connection(self, conn: Connection) -> TestResult:
        ping_status = "error"
        auth_status = "error"
        ping_error = None
        auth_error = None
        detected_version = None
        api_prefix = None
        bearer_token = self.get_token(conn)
        configured_version = conn.version
        if configured_version:
            try:
                major, minor = parse_aap_major_minor(configured_version)
                configured_version = f"{major}.{minor}"
            except ValueError:
                pass

        for ping_url, prefix in ping_probe_candidates(conn):
            try:
                resp = httpx.get(
                    ping_url,
                    verify=conn.verify_ssl,
                    timeout=10,
                )
                if resp.status_code == 200:
                    ping_status = "ok"
                    api_prefix = prefix
                    data = resp.json()
                    detected_version = data.get("version", data.get("active_node", None))
                    break
                ping_error = f"HTTP {resp.status_code}"
            except Exception as e:
                ping_error = str(e)

        if ping_status == "ok" and api_prefix is not None:
            probe_version = configured_version or resolve_connection_version(conn)
            if detected_version:
                try:
                    major, minor = parse_aap_major_minor(detected_version)
                    detected_version = f"{major}.{minor}"
                except ValueError:
                    pass
            try:
                resp = httpx.get(
                    me_probe_url(conn, probe_version),
                    headers={"Authorization": f"Bearer {bearer_token}"},
                    verify=conn.verify_ssl,
                    timeout=10,
                )
                if resp.status_code == 200:
                    auth_status = "ok"
                else:
                    auth_status = "error"
                    auth_error = f"HTTP {resp.status_code}"
            except Exception as e:
                auth_error = str(e)

        conn.ping_status = ping_status
        conn.ping_error = ping_error
        conn.auth_status = auth_status
        conn.auth_error = auth_error
        conn.api_prefix = api_prefix
        conn.last_checked = datetime.now(UTC)
        self.db.commit()

        error = ping_error or auth_error
        return TestResult(
            ok=(ping_status == "ok" and auth_status == "ok"),
            ping_status=ping_status,
            auth_status=auth_status,
            version=conn.version,
            api_prefix=api_prefix,
            error=error,
        )
