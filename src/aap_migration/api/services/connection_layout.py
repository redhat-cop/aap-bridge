"""Map saved web connections onto api_layout for routing and migration config."""

from __future__ import annotations

from aap_migration.api.models import Connection
from aap_migration.config import normalize_aap_version
from aap_migration.resources import SUPPORTED_SOURCE_VERSIONS, SUPPORTED_TARGET_VERSIONS
from aap_migration.client.api_layout import (
    CONTROLLER_API_PREFIX,
    GATEWAY_API_PREFIX,
    LEGACY_API_PREFIX,
    API_VERSIONED_PREFIXES,
    ApiLayout,
    build_api_layout,
    join_api_base,
    normalize_host_url,
    parse_aap_major_minor,
)


def split_connection_url(url: str) -> tuple[str, str | None]:
    """Split a connection URL into host URL and an explicit API prefix, if present."""
    normalized = url.strip().rstrip("/")
    for suffix in API_VERSIONED_PREFIXES:
        if normalized.endswith(suffix):
            host = normalized[: -len(suffix)].rstrip("/") or normalized
            return host, suffix
    return normalized, None


def normalize_connection_url(url: str) -> str:
    """Normalize a connection URL to scheme + host (no API path suffix)."""
    return normalize_host_url(url.strip())


def validate_connection_version(role: str, version: str) -> str:
    """Normalize and validate an AAP version for a Web UI connection role."""
    normalized = normalize_aap_version(version)
    allowed = SUPPORTED_SOURCE_VERSIONS if role == "source" else SUPPORTED_TARGET_VERSIONS
    if normalized not in allowed:
        raise ValueError(
            f"Invalid AAP version '{version}' for role '{role}'. "
            f"Valid versions: {', '.join(allowed)}"
        )
    return normalized


def resolve_connection_version(conn: Connection) -> str:
    """Return the configured AAP version for a saved connection."""
    if conn.version:
        try:
            major, minor = parse_aap_major_minor(conn.version)
            return f"{major}.{minor}"
        except ValueError:
            return conn.version

    if conn.api_prefix == LEGACY_API_PREFIX:
        return "2.4"
    if conn.api_prefix in (CONTROLLER_API_PREFIX, GATEWAY_API_PREFIX):
        return "2.6"
    return "2.4"


def build_connection_layout(conn: Connection) -> ApiLayout:
    """Build the API layout for a saved connection."""
    return build_api_layout(conn.url, resolve_connection_version(conn))


def ping_probe_candidates(conn: Connection) -> list[tuple[str, str]]:
    """Return (ping_url, api_prefix) pairs to try when testing a connection."""
    host = normalize_host_url(conn.url)
    return [
        (f"{join_api_base(host, CONTROLLER_API_PREFIX)}/ping/", CONTROLLER_API_PREFIX),
        (f"{join_api_base(host, LEGACY_API_PREFIX)}/ping/", LEGACY_API_PREFIX),
        (f"{join_api_base(host, GATEWAY_API_PREFIX)}/ping/", GATEWAY_API_PREFIX),
    ]


def me_probe_url(conn: Connection, version: str | None) -> str:
    """Return the /me/ URL to validate authentication for a tested connection."""
    resolved_version = version or resolve_connection_version(conn)
    layout = build_api_layout(conn.url, resolved_version)
    return f"{layout.base_for_endpoint('me')}/me/"
