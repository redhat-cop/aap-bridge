"""AAP API layout and version-aware endpoint routing.

AAP 2.4 and earlier expose a single controller API at /api/v2/. AAP 2.5+
introduces the platform gateway; shared resources (organizations, users, teams,
RBAC, etc.) live under /api/gateway/v1/ while automation content remains under
/api/controller/v2/.

API topology is selected from the configured AAP version, not from the API
itself — older releases do not expose a reliable product version in API
responses.

- CLI and TUI: ``SOURCE__VERSION`` / ``TARGET__VERSION`` in ``.env`` (via
  ``config/config.yaml``).
- Web UI: per-connection ``version`` saved in the connections database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

# Canonical AAP API path roots (single source of truth).
LEGACY_API_PREFIX = "/api/v2"
GATEWAY_API_PREFIX = "/api/gateway/v1"
CONTROLLER_API_PREFIX = "/api/controller/v2"
GATEWAY_API_FAMILY = "/api/gateway"
CONTROLLER_API_FAMILY = "/api/controller"

# Versioned API roots, longest first (for URL normalization and href stripping).
API_VERSIONED_PREFIXES: tuple[str, ...] = (
    GATEWAY_API_PREFIX,
    CONTROLLER_API_PREFIX,
    LEGACY_API_PREFIX,
)

# Path suffixes stripped from configured host URLs (longest first).
API_PATH_SUFFIXES: tuple[str, ...] = (
    *API_VERSIONED_PREFIXES,
    GATEWAY_API_FAMILY,
    CONTROLLER_API_FAMILY,
)

# Markers with trailing slash for stripping absolute hrefs and pagination URLs.
API_PATH_MARKERS: tuple[str, ...] = tuple(f"{prefix}/" for prefix in API_VERSIONED_PREFIXES)

# First path segment -> route to gateway API on AAP 2.5+.
GATEWAY_ENDPOINT_SEGMENTS: frozenset[str] = frozenset(
    {
        # Shared / migrated resources
        "organizations",
        "users",
        "teams",
        "applications",
        "role_definitions",
        "tokens",
        # Gateway platform endpoints (not migrated; routed correctly when probed)
        "activitystream",
        "app_urls",
        "authenticator_maps",
        "authenticator_plugins",
        "authenticator_users",
        "authenticators",
        "ca_certificates",
        "http_ports",
        "me",
        "ping",
        "routes",
        "service_clusters",
        "service_keys",
        "service_nodes",
        "service_types",
        "services",
        "session",
        "settings",
        "status",
        "trigger_definition",
        "ui_auth",
        "ui_plugin_routes",
    }
)

# Role assignments on these content types use the gateway API on AAP 2.5+.
# Controller automation permissions (projects, job templates, etc.) use
# /api/controller/v2/role_*_assignments/ per Red Hat API migration guidance.
GATEWAY_RBAC_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "awx.organization",
        "awx.team",
        # Gateway RBAC API uses shared.* labels for platform objects (AAP 2.5+).
        "shared.organization",
        "shared.team",
    }
)

# Gateway exports platform RBAC content_type labels that differ from controller.
_RBAC_CONTENT_TYPE_ALIASES: dict[str, str] = {
    "shared.organization": "awx.organization",
    "shared.team": "awx.team",
}


def normalize_rbac_content_type(content_type: str | None) -> str | None:
    """Normalize gateway RBAC content_type labels for routing and lookups."""
    if not content_type:
        return None
    return _RBAC_CONTENT_TYPE_ALIASES.get(content_type, content_type)


def join_api_base(host_url: str, api_prefix: str) -> str:
    """Join a normalized host URL with an API path prefix."""
    return f"{host_url.rstrip('/')}{api_prefix}"


def strip_api_path_prefix(path: str) -> str:
    """Strip a known AAP API path prefix, returning the relative endpoint."""
    if not path:
        return path

    normalized = path if path.startswith("/") else f"/{path}"
    for marker in API_PATH_MARKERS:
        if marker in normalized:
            return normalized.split(marker, 1)[1]

    cleaned = normalized.lstrip("/")
    for marker in API_PATH_MARKERS:
        bare = marker.lstrip("/")
        if cleaned.startswith(bare):
            return cleaned[len(bare) :]

    return cleaned


def api_topology_from_url(url: str) -> str | None:
    """Infer gateway vs controller vs legacy from an API base or href URL."""
    normalized = url.rstrip("/")
    if GATEWAY_API_FAMILY in normalized or normalized.endswith(GATEWAY_API_PREFIX):
        return "gateway"
    if CONTROLLER_API_FAMILY in normalized or normalized.endswith(CONTROLLER_API_PREFIX):
        return "controller"
    if LEGACY_API_PREFIX in normalized:
        return "legacy"
    return None


def role_definition_api_base(
    layout: ApiLayout,
    content_type: str | None,
    exported_api_base: str | None = None,
) -> str:
    """Return gateway vs controller base on *this* instance for role_definition APIs.

    Export stores ``_api_base`` with the source hostname to record which API
    surface the role came from. Import must remap that to the target layout's
    gateway/controller bases — not POST back to the source host.

    On gateway topology, ``content_type`` determines the correct API surface
    (``awx.*`` → controller, ``shared.*`` → gateway). The exported source base
    must not override that routing — the same custom role can appear on both
    APIs during export, but assignments for ``awx.*`` objects are always
    created on the controller.
    """
    if layout.mode is ApiMode.GATEWAY:
        return layout.base_for_role_assignment(content_type)

    if exported_api_base:
        topology = api_topology_from_url(exported_api_base)
        if topology == "legacy" and layout.legacy_base:
            return layout.legacy_base

    if not layout.legacy_base:
        raise ValueError("legacy_base is required for legacy API mode")
    return layout.legacy_base

# AAP 2.5 introduced the platform gateway API layout.
_GATEWAY_TOPOLOGY_MIN_VERSION = (2, 5)


class ApiMode(str, Enum):
    """AAP API topology for an instance."""

    LEGACY = "legacy"
    GATEWAY = "gateway"


@dataclass(frozen=True, slots=True)
class ApiLayout:
    """Resolved API bases for an AAP instance."""

    host_url: str
    mode: ApiMode
    aap_version: str
    legacy_base: str | None = None
    gateway_base: str | None = None
    controller_base: str | None = None

    @property
    def default_base_url(self) -> str:
        """Primary API base used for logging and endpoint discovery."""
        if self.mode is ApiMode.LEGACY:
            if not self.legacy_base:
                raise ValueError("legacy_base is required for legacy API mode")
            return self.legacy_base
        if not self.controller_base:
            raise ValueError("controller_base is required for gateway API mode")
        return self.controller_base

    @property
    def path_prefixes(self) -> tuple[str, ...]:
        """URL path prefixes for stripping absolute hrefs (longest first)."""
        return API_VERSIONED_PREFIXES

    def base_for_endpoint(self, endpoint: str) -> str:
        """Return the API base URL for a relative endpoint path."""
        if self.mode is ApiMode.LEGACY:
            if not self.legacy_base:
                raise ValueError("legacy_base is required for legacy API mode")
            return self.legacy_base

        segment = endpoint.lstrip("/").split("/")[0]
        if segment in GATEWAY_ENDPOINT_SEGMENTS:
            if not self.gateway_base:
                raise ValueError("gateway_base is required for gateway API mode")
            return self.gateway_base

        if not self.controller_base:
            raise ValueError("controller_base is required for gateway API mode")
        return self.controller_base

    def base_for_role_assignment(self, content_type: str | None) -> str:
        """Return API base for role_user_assignments / role_team_assignments."""
        if self.mode is ApiMode.LEGACY:
            if not self.legacy_base:
                raise ValueError("legacy_base is required for legacy API mode")
            return self.legacy_base

        normalized = normalize_rbac_content_type(content_type)
        if normalized and normalized in GATEWAY_RBAC_CONTENT_TYPES:
            if not self.gateway_base:
                raise ValueError("gateway_base is required for gateway API mode")
            return self.gateway_base

        if not self.controller_base:
            raise ValueError("controller_base is required for gateway API mode")
        return self.controller_base

    def role_assignment_bases(self) -> tuple[str, ...]:
        """API bases to query when listing all role assignments (gateway topology)."""
        if self.mode is ApiMode.LEGACY:
            if not self.legacy_base:
                raise ValueError("legacy_base is required for legacy API mode")
            return (self.legacy_base,)

        bases: list[str] = []
        if self.gateway_base:
            bases.append(self.gateway_base)
        if self.controller_base:
            bases.append(self.controller_base)
        return tuple(bases)

    def relative_endpoint(self, path: str) -> str:
        """Strip a known API prefix from an absolute or relative path."""
        return strip_api_path_prefix(path)


def normalize_host_url(url: str, *, instance: str | None = None) -> str:
    """Normalize a configured URL to scheme + host (no API path suffix)."""
    normalized = url.rstrip("/")
    original = normalized
    log_context = {"instance": instance} if instance else {}
    for suffix in API_PATH_SUFFIXES:
        if normalized.endswith(suffix):
            stripped = normalized[: -len(suffix)].rstrip("/")
            if stripped != normalized:
                logger.info(
                    "api_url_normalized",
                    api_url=url,
                    host_url=stripped,
                    **log_context,
                )
            normalized = stripped
            break
    if instance and normalized == original:
        logger.info(
            "api_host_url_ready",
            host_url=normalized,
            **log_context,
        )
    return normalized


def parse_aap_major_minor(version: str) -> tuple[int, int]:
    """Parse major.minor from an AAP version string (e.g. '2.4.1', '2.6')."""
    parts = version.strip().split(".")
    if len(parts) < 2:
        raise ValueError(
            f"Invalid AAP version '{version}': expected major.minor (e.g. '2.4' or '2.6')"
        )
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(
            f"Invalid AAP version '{version}': expected major.minor (e.g. '2.4' or '2.6')"
        ) from exc


def uses_gateway_topology(aap_version: str) -> bool:
    """Return True when the configured AAP version uses gateway + controller APIs."""
    major, minor = parse_aap_major_minor(aap_version)
    return (major, minor) >= _GATEWAY_TOPOLOGY_MIN_VERSION


def build_api_layout(host_url: str, aap_version: str) -> ApiLayout:
    """Build API layout from host URL and configured AAP version."""
    normalized_host = normalize_host_url(host_url)

    if uses_gateway_topology(aap_version):
        layout = ApiLayout(
            host_url=normalized_host,
            mode=ApiMode.GATEWAY,
            aap_version=aap_version,
            gateway_base=join_api_base(normalized_host, GATEWAY_API_PREFIX),
            controller_base=join_api_base(normalized_host, CONTROLLER_API_PREFIX),
        )
    else:
        layout = ApiLayout(
            host_url=normalized_host,
            mode=ApiMode.LEGACY,
            aap_version=aap_version,
            legacy_base=join_api_base(normalized_host, LEGACY_API_PREFIX),
        )

    logger.info(
        "api_layout_built",
        mode=layout.mode.value,
        aap_version=aap_version,
        host_url=layout.host_url,
        legacy_base=layout.legacy_base,
        gateway_base=layout.gateway_base,
        controller_base=layout.controller_base,
    )
    return layout


def _endpoint_segment(endpoint: str) -> str:
    return endpoint.lstrip("/").split("/")[0]


def uses_gateway_api(layout: ApiLayout | None, endpoint: str) -> bool:
    """Return True if the endpoint should use the gateway API base."""
    if layout is None or layout.mode is ApiMode.LEGACY:
        return False
    return _endpoint_segment(endpoint) in GATEWAY_ENDPOINT_SEGMENTS
