"""Schema generation module for AAP instances.

This module generates schemas for all endpoints by sending OPTIONS requests
and extracting field definitions from the responses.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


async def fetch_endpoint_schema(
    client: AAPSourceClient | AAPTargetClient,
    endpoint_url: str,
) -> dict[str, Any] | None:
    """Fetch schema for a single endpoint using OPTIONS request.

    Args:
        client: AAP client
        endpoint_url: Endpoint URL (e.g., "/api/v2/organizations/")

    Returns:
        Schema data dict or None if OPTIONS not supported

    Raises:
        HTTPError: If request fails
    """
    try:
        # Send OPTIONS request to get schema
        # Suppress server error logging in client (handle it here)
        response = await client.options(endpoint_url, suppress_server_error=True)

        # Extract schema from response
        # OPTIONS response contains actions (GET, POST, etc.) with field definitions
        schema = {}

        # Get POST action (contains writable fields)
        if "actions" in response and "POST" in response["actions"]:
            post_fields = response["actions"]["POST"]
            for field_name, field_spec in post_fields.items():
                schema[field_name] = {
                    "type": field_spec.get("type", "string"),
                    "required": field_spec.get("required", False),
                    "read_only": field_spec.get("read_only", False),
                    "help_text": field_spec.get("help_text", ""),
                }

                # Add additional constraints
                if "max_length" in field_spec:
                    schema[field_name]["max_length"] = field_spec["max_length"]
                if "default" in field_spec:
                    schema[field_name]["default"] = field_spec["default"]
                if "choices" in field_spec:
                    schema[field_name]["choices"] = field_spec["choices"]

        # Get GET action (contains readable fields, including read-only ones)
        if "actions" in response and "GET" in response["actions"]:
            get_fields = response["actions"]["GET"]
            for field_name, field_spec in get_fields.items():
                if field_name not in schema:
                    schema[field_name] = {
                        "type": field_spec.get("type", "string"),
                        "required": False,
                        "read_only": True,
                        "help_text": field_spec.get("help_text", ""),
                    }

        return schema if schema else None

    except Exception as e:
        # Check if it's an HTTP error with status code
        status_code = None
        # Try standard httpx/requests response attribute
        if hasattr(e, "response") and hasattr(e.response, "status_code"):
            status_code = e.response.status_code
        # Try direct status_code attribute (custom exceptions)
        elif hasattr(e, "status_code"):
            status_code = e.status_code

        # Extract parsing error status (e.g. "[500] Server Error") from string if needed
        if status_code is None and "[500]" in str(e):
            status_code = 500

        if status_code and status_code >= 500:
            # Server error - needs investigation
            # Log full details to file only (DEBUG) to avoid cluttering console with HTML
            logger.debug(
                "server_error_schema_fetch_details",
                endpoint=endpoint_url,
                status_code=status_code,
                error=str(e),
            )
            # Log at INFO level - user sees summary in CLI output
            # Console level is WARNING, so this only goes to file
            logger.info(
                "server_error_schema_fetch",
                endpoint=endpoint_url,
                status_code=status_code,
                message="Server error - will use source schema as fallback",
            )
        else:
            # Other error (client error, network, etc.)
            # Log full details to DEBUG
            logger.debug(
                "schema_fetch_failed_details",
                endpoint=endpoint_url,
                error=str(e),
            )
            # Log at INFO level - user sees summary in CLI output
            # Truncate error message for readability
            error_msg = str(e).split("\n")[0][:200]  # First line, max 200 chars
            logger.info(
                "schema_fetch_failed",
                endpoint=endpoint_url,
                error=error_msg,
            )
        return None


async def generate_schema(
    client: AAPSourceClient | AAPTargetClient,
    endpoints_data: dict[str, Any],
) -> dict[str, Any]:
    """Generate schema for all discovered endpoints.

    Args:
        client: AAP client
        endpoints_data: Discovered endpoints from endpoint_discovery

    Returns:
        Dictionary containing:
        - api_version: AAP version
        - generated_at: ISO timestamp
        - schemas: Dict of endpoint_name -> field_schemas
    """
    api_version = endpoints_data["api_version"]

    logger.info(
        "generating_schemas",
        api_version=api_version,
        endpoint_count=len(endpoints_data["endpoints"]),
    )

    schemas = {}
    success_count = 0
    failed_count = 0

    for endpoint_name, endpoint_info in endpoints_data["endpoints"].items():
        endpoint_url = endpoint_info["url"]

        logger.debug(
            "fetching_endpoint_schema",
            endpoint_name=endpoint_name,
            endpoint_url=endpoint_url,
        )

        schema = await fetch_endpoint_schema(client, endpoint_url)

        if schema:
            schemas[endpoint_name] = {"fields": schema}
            success_count += 1
        else:
            # Downgrade to INFO as requested - "it works but no schema" is common
            logger.info(
                "schema_generation_failed",
                endpoint_name=endpoint_name,
                endpoint_url=endpoint_url,
            )
            failed_count += 1

    logger.info(
        "schemas_generated",
        api_version=api_version,
        success_count=success_count,
        failed_count=failed_count,
    )

    result = {
        "api_version": api_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "schemas": schemas,
    }

    return result


def save_schema(
    schema_data: dict[str, Any],
    output_file: Path,
) -> None:
    """Save generated schema to JSON file.

    Args:
        schema_data: Schema data from generate_schema()
        output_file: Path to output JSON file
    """
    logger.info(
        "saving_schema",
        output_file=str(output_file),
        schema_count=len(schema_data.get("schemas", {})),
    )

    # Create parent directory if it doesn't exist
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON file
    with open(output_file, "w") as f:
        json.dump(schema_data, f, indent=2)

    logger.info(
        "schema_saved",
        output_file=str(output_file),
        file_size=output_file.stat().st_size,
    )


def load_schema(schema_file: Path) -> dict[str, Any]:
    """Load schema from JSON file.

    Args:
        schema_file: Path to schema JSON file

    Returns:
        Schema data

    Raises:
        FileNotFoundError: If file doesn't exist
        JSONDecodeError: If file is not valid JSON
    """
    logger.debug("loading_schema", file=str(schema_file))

    with open(schema_file) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid schema file: {schema_file}")

    logger.debug(
        "schema_loaded",
        file=str(schema_file),
        schema_count=len(data.get("schemas", {})),
    )

    return data
