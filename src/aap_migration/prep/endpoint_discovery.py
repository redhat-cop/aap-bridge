"""Endpoint discovery module for AAP instances.

This module discovers all available API endpoints from AAP 2.3 (source)
and AAP 2.6 (target) instances by fetching the API root.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.client.api_layout import ApiMode
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

_SKIP_ROOT_KEYS = frozenset(
    {
        "description",
        "current_version",
        "available_versions",
        "oauth2",
        "custom_logo",
        "custom_login_info",
        "login_redirect_override",
        "apis",
    }
)


def _relative_endpoint_path(endpoint_url: str) -> str:
    """Extract relative endpoint path from an API root href."""
    return endpoint_url.rstrip("/").split("/")[-1] + "/"


def _endpoint_ignored(endpoint_name: str, endpoint_path: str, ignored_endpoints: list[str]) -> bool:
    """Return True if an endpoint should be skipped during discovery."""
    ignored_keys = {item.rstrip("/") for item in ignored_endpoints}
    return endpoint_name in ignored_keys or endpoint_path.rstrip("/") in ignored_keys


def _discover_bases(client: AAPSourceClient | AAPTargetClient) -> list[str]:
    """Return API versioned base URLs to probe for endpoint listings."""
    layout = client.api_layout

    if layout.mode is ApiMode.GATEWAY:
        bases: list[str] = []
        if layout.gateway_base:
            bases.append(layout.gateway_base)
        if layout.controller_base:
            bases.append(layout.controller_base)
        return bases

    if layout.legacy_base:
        return [layout.legacy_base]
    return [client.base_url]


async def discover_endpoints(
    client: AAPSourceClient | AAPTargetClient,
    api_version: str,
    ignored_endpoints: list[str] | None = None,
) -> dict[str, Any]:
    """Discover all available endpoints from AAP API root.

    Args:
        client: AAP client (source or target)
        api_version: API version string (e.g., "2.3.0" or "2.6.0")
        ignored_endpoints: List of endpoint paths to ignore (e.g., ["mesh_visualizer/", "metrics/"])

    Returns:
        Dictionary containing:
        - api_version: AAP version
        - discovered_at: ISO timestamp
        - base_url: Base URL of the API
        - endpoints: Dict of endpoint_name -> endpoint_details

    Raises:
        HTTPError: If API is unreachable or returns error
    """
    ignored_endpoints = ignored_endpoints or []

    logger.info(
        "discovering_endpoints",
        api_version=api_version,
        host_url=client.host_url,
        ignored_count=len(ignored_endpoints),
    )

    try:
        endpoints_data: dict[str, Any] = {}
        endpoint_count = 0
        ignored_count = 0

        for base in _discover_bases(client):
            response = await client.get_api_root(base)

            for endpoint_name, endpoint_url in response.items():
                if endpoint_name in _SKIP_ROOT_KEYS:
                    continue
                if not isinstance(endpoint_url, str):
                    continue

                endpoint_path = _relative_endpoint_path(endpoint_url)

                if _endpoint_ignored(endpoint_name, endpoint_path, ignored_endpoints):
                    logger.debug(
                        "endpoint_ignored",
                        endpoint_name=endpoint_name,
                        endpoint_path=endpoint_path,
                    )
                    ignored_count += 1
                    continue

                if endpoint_name in endpoints_data:
                    continue

                endpoints_data[endpoint_name] = {
                    "url": endpoint_path,
                    "methods": None,
                    "supports_filtering": None,
                    "supports_pagination": None,
                }
                endpoint_count += 1

        logger.info(
            "endpoints_discovered",
            api_version=api_version,
            endpoint_count=endpoint_count,
            ignored_count=ignored_count,
        )

        return {
            "api_version": api_version,
            "discovered_at": datetime.now(UTC).isoformat(),
            "base_url": str(client.base_url),
            "host_url": client.host_url,
            "endpoints": endpoints_data,
        }

    except Exception as e:
        logger.error(
            "endpoint_discovery_failed",
            api_version=api_version,
            error=str(e),
            exc_info=True,
        )
        raise


def save_endpoints(
    endpoints_data: dict[str, Any],
    output_file: Path,
) -> None:
    """Save discovered endpoints to JSON file.

    Args:
        endpoints_data: Endpoints data from discover_endpoints()
        output_file: Path to output JSON file
    """
    logger.info(
        "saving_endpoints",
        output_file=str(output_file),
        endpoint_count=len(endpoints_data.get("endpoints", {})),
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        json.dump(endpoints_data, f, indent=2)

    logger.info(
        "endpoints_saved",
        output_file=str(output_file),
        file_size=output_file.stat().st_size,
    )


def load_endpoints(endpoints_file: Path) -> dict[str, Any]:
    """Load endpoints from JSON file.

    Args:
        endpoints_file: Path to endpoints JSON file

    Returns:
        Endpoints data

    Raises:
        FileNotFoundError: If file doesn't exist
        JSONDecodeError: If file is not valid JSON
    """
    logger.debug("loading_endpoints", file=str(endpoints_file))

    with open(endpoints_file) as f:
        data = json.load(f)

    logger.debug(
        "endpoints_loaded",
        file=str(endpoints_file),
        endpoint_count=len(data.get("endpoints", {})),
    )

    return data
