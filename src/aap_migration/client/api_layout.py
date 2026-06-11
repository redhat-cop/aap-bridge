"""AAP API layout and version-aware endpoint routing.

AAP 2.4 and earlier expose a single controller API at /api/v2/. AAP 2.5+
introduces the platform gateway; shared resources (organizations, users, teams,
RBAC, etc.) live under /api/gateway/v1/ while automation content remains under
/api/controller/v2/.

API topology is selected from the configured AAP version (SOURCE__VERSION /
TARGET__VERSION), not from the API itself — older releases do not expose a
reliable product version in API responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

# API path suffixes stripped from configured URLs (longest first).
_API_PATH_SUFFIXES: tuple[str, ...] = (
    "/api/gateway/v1",
    "/api/controller/v2",
    "/api/v2",
    "/api/gateway",
    "/api/controller",
)

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


def _api_topology_from_exported_base(exported_api_base: str) -> str | None:
    """Infer gateway vs controller vs legacy from an exported ``_api_base`` path."""
    normalized = exported_api_base.rstrip("/")
    if "/api/gateway/" in normalized or normalized.endswith("/api/gateway/v1"):
        return "gateway"
    if "/api/controller/" in normalized or normalized.endswith("/api/controller/v2"):
        return "controller"
    if "/api/v2" in normalized:
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
    """
    if exported_api_base:
        topology = _api_topology_from_exported_base(exported_api_base)
        if topology == "gateway" and layout.gateway_base:
            return layout.gateway_base
        if topology == "controller" and layout.controller_base:
            return layout.controller_base
        if topology == "legacy" and layout.legacy_base:
            return layout.legacy_base

    if layout.mode is ApiMode.GATEWAY:
        return layout.base_for_role_assignment(content_type)
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
        prefixes: list[str] = []
        for base in (self.legacy_base, self.gateway_base, self.controller_base):
            if not base:
                continue
            path = urlparse(base).path.rstrip("/")
            if path:
                prefixes.append(path)
        return tuple(sorted(set(prefixes), key=len, reverse=True))

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
        if not path:
            return path

        normalized = path if path.startswith("/") else f"/{path}"
        for prefix in self.path_prefixes:
            marker = f"{prefix}/"
            if marker in normalized:
                return normalized.split(marker, 1)[1]

        cleaned = normalized.lstrip("/")
        for prefix in self.path_prefixes:
            bare = prefix.lstrip("/")
            if cleaned.startswith(f"{bare}/"):
                return cleaned[len(bare) + 1 :]
        return cleaned


def normalize_host_url(url: str) -> str:
    """Normalize a configured URL to scheme + host (no API path suffix)."""
    normalized = url.rstrip("/")
    for suffix in _API_PATH_SUFFIXES:
        if normalized.endswith(suffix):
            stripped = normalized[: -len(suffix)].rstrip("/")
            if stripped != normalized:
                logger.info(
                    "api_url_normalized",
                    api_url=url,
                    host_url=stripped,
                )
            normalized = stripped
            break
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
            gateway_base=f"{normalized_host}/api/gateway/v1",
            controller_base=f"{normalized_host}/api/controller/v2",
        )
    else:
        layout = ApiLayout(
            host_url=normalized_host,
            mode=ApiMode.LEGACY,
            aap_version=aap_version,
            legacy_base=f"{normalized_host}/api/v2",
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
