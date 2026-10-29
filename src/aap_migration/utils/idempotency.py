"""Idempotency utilities for AAP migration operations.

This module provides utilities for ensuring idempotent migrations:
- Unique key generation for resource identification
- Idempotent decorator for functions
- Conflict resolution and duplicate detection
- Resource comparison utilities
"""

import functools
import hashlib
import json
from collections.abc import Callable
from typing import Any

from aap_migration.client.exceptions import ConflictError
from aap_migration.migration.state import MigrationState
from aap_migration.resources import normalize_resource_type
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


def generate_resource_key(resource: dict[str, Any], key_fields: list[str]) -> str:
    """Generate a unique key for a resource based on specified fields.

    This creates a deterministic string key from a resource dictionary by
    concatenating specified field values. Supports nested field access using
    dot notation (e.g., "inventory.id").

    Args:
        resource: Resource dictionary
        key_fields: List of field names to include in key

    Returns:
        Unique key string in format "field1:value1|field2:value2|..."

    Examples:
        >>> resource = {"name": "test-inv", "organization": 1}
        >>> generate_resource_key(resource, ["name", "organization"])
        'name:test-inv|organization:1'

        >>> resource = {"name": "host1", "inventory": {"id": 123}}
        >>> generate_resource_key(resource, ["name", "inventory.id"])
        'name:host1|inventory.id:123'
    """
    key_parts = []

    for field in key_fields:
        # Handle nested field access (e.g., "inventory.id")
        if "." in field:
            parts = field.split(".")
            value = resource
            for part in parts:
                value = value.get(part, "") if isinstance(value, dict) else ""
                if not value:
                    break
        else:
            value = resource.get(field, "")

        # Convert to string for consistency
        key_parts.append(f"{field}:{value}")

    return "|".join(key_parts)


def hash_resource(
    resource: dict[str, Any],
    exclude_fields: list[str] | None = None,
) -> str:
    """Generate SHA-256 hash of a resource for comparison.

    Creates a deterministic hash of a resource dictionary. Field order
    does not affect the hash. Useful for detecting changes in resources.

    Args:
        resource: Resource dictionary to hash
        exclude_fields: Optional list of fields to exclude from hash
            (e.g., ["id", "created", "modified"])

    Returns:
        SHA-256 hash as hex string (64 characters)

    Examples:
        >>> resource = {"name": "test", "description": "Test inventory"}
        >>> hash_resource(resource)
        'a1b2c3...'  # 64-character SHA-256 hash

        >>> # Exclude auto-generated fields
        >>> hash_resource(resource, exclude_fields=["id", "created"])
        'x1y2z3...'
    """
    # Create a copy to avoid modifying original
    resource_copy = dict(resource)

    # Remove excluded fields
    if exclude_fields:
        for field in exclude_fields:
            resource_copy.pop(field, None)

    # Sort keys for deterministic JSON
    json_str = json.dumps(resource_copy, sort_keys=True, default=str)

    # Generate SHA-256 hash
    return hashlib.sha256(json_str.encode()).hexdigest()


def idempotent(
    state: MigrationState,
    resource_type: str,
    key_fields: list[str],
    source_id_field: str = "id",
    source_name_field: str = "name",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to make a function idempotent using state tracking.

    This decorator wraps async functions to:
    1. Check if resource already migrated (skip if so)
    2. Execute function if not migrated
    3. Handle ConflictError by finding existing resource
    4. Mark resource as completed in state
    5. Store source→target ID mapping

    Args:
        state: MigrationState instance for tracking
        resource_type: Resource type (e.g., "inventory", "hosts")
        key_fields: Fields that uniquely identify the resource
        source_id_field: Field name containing source resource ID
        source_name_field: Field name containing source resource name

    Returns:
        Decorated async function

    Examples:
        >>> @idempotent(
        ...     state=migration_state,
        ...     resource_type="inventory",
        ...     key_fields=["name", "organization"],
        ...     source_id_field="source_id",
        ...     source_name_field="name"
        ... )
        ... async def create_inventory(data: dict) -> dict:
        ...     return await client.create_resource("inventory", data)

        >>> # First call: executes function
        >>> result1 = await create_inventory({"name": "test", "source_id": 50})

        >>> # Second call with same source_id: skips execution, returns cached
        >>> result2 = await create_inventory({"name": "test", "source_id": 50})
    """

    def decorator(func: Callable) -> Callable:
        # Normalize resource type
        nonlocal resource_type
        resource_type = normalize_resource_type(resource_type)

        @functools.wraps(func)
        async def wrapper(data: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            # Extract source ID and name
            source_id = data.get(source_id_field)
            source_name = data.get(source_name_field, "")

            if source_id is not None:
                # Check if already migrated
                if state.is_migrated(resource_type, source_id):
                    target_id = state.get_mapped_id(resource_type, source_id)

                    logger.info(
                        "resource_already_migrated",
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                    )

                    # Return cached result
                    return {"id": target_id, **data}

            # Execute function
            try:
                result = await func(data, *args, **kwargs)
                if not isinstance(result, dict):
                    raise TypeError(f"Idempotent function must return dict, got {type(result)!r}")

                # Mark as completed if we have source_id
                if source_id is not None and "id" in result:
                    target_id = result["id"]

                    # Mark in progress first if not already
                    if not state.is_migrated(resource_type, source_id):
                        state.mark_in_progress(
                            resource_type=resource_type,
                            source_id=source_id,
                            source_name=source_name,
                        )

                    # Mark completed and store mapping
                    state.mark_completed(
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                    )

                    logger.debug(
                        "resource_migrated",
                        resource_type=resource_type,
                        source_id=source_id,
                        target_id=target_id,
                    )

                return result

            except ConflictError as e:
                logger.warning(
                    "resource_conflict_detected",
                    resource_type=resource_type,
                    source_id=source_id,
                    error=str(e),
                )

                # Try to find existing resource
                # We need the client to be passed in kwargs or available
                if "client" in kwargs:
                    client = kwargs["client"]
                    existing = await find_existing_resource(client, resource_type, data)

                    if existing:
                        # Mark as completed with existing ID
                        if source_id is not None:
                            target_id = existing["id"]

                            if not state.is_migrated(resource_type, source_id):
                                state.mark_in_progress(
                                    resource_type=resource_type,
                                    source_id=source_id,
                                    source_name=source_name,
                                )

                            state.mark_completed(
                                resource_type=resource_type,
                                source_id=source_id,
                                target_id=target_id,
                            )

                        return existing

                # Re-raise if we couldn't handle it
                raise

        return wrapper

    return decorator


async def handle_conflict(
    client: Any,
    resource_type: str,
    data: dict[str, Any],
    conflict_error: ConflictError,
) -> dict[str, Any]:
    """Handle a ConflictError by finding and returning the existing resource.

    When a 409 Conflict occurs during resource creation, this function
    attempts to find the existing resource and return it. This enables
    idempotent operations.

    Args:
        client: AAP client instance with find_resource_by_name method
        resource_type: Resource type (e.g., "inventory")
        data: Resource data that caused conflict
        conflict_error: The ConflictError exception

    Returns:
        Existing resource data

    Raises:
        ConflictError: If existing resource cannot be found

    Examples:
        >>> try:
        ...     result = await client.create_resource("inventory", data)
        ... except ConflictError as e:
        ...     result = await handle_conflict(client, "inventory", data, e)
    """
    resource_type = normalize_resource_type(resource_type)
    logger.info(
        "handling_conflict",
        resource_type=resource_type,
        resource_name=data.get("name"),
    )

    # Try to find existing resource
    existing = await find_existing_resource(client, resource_type, data)

    if existing:
        logger.info(
            "found_existing_resource",
            resource_type=resource_type,
            resource_id=existing.get("id"),
            resource_name=existing.get("name"),
        )
        return existing

    # If we couldn't find it, re-raise the conflict error
    logger.error(
        "could_not_find_existing_resource",
        resource_type=resource_type,
        resource_name=data.get("name"),
    )

    raise ConflictError(
        f"Could not find existing resource after conflict: {data.get('name')}",
        status_code=409,
    ) from conflict_error


async def find_existing_resource(
    client: Any,
    resource_type: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """Find an existing resource by name and organization.

    Attempts to locate a resource using the AAP API based on the resource's
    name and optionally its organization.

    Args:
        client: AAP client instance with find_resource_by_name method
        resource_type: Resource type (e.g., "inventory")
        data: Resource data containing "name" and optionally "organization"

    Returns:
        Existing resource data if found, None otherwise

    Examples:
        >>> data = {"name": "test-inventory", "organization": 5}
        >>> existing = await find_existing_resource(client, "inventory", data)
        >>> if existing:
        ...     print(f"Found resource with ID: {existing['id']}")
    """
    resource_type = normalize_resource_type(resource_type)
    name = data.get("name")
    organization = data.get("organization")

    if not name:
        logger.warning(
            "cannot_find_resource_without_name",
            resource_type=resource_type,
        )
        return None

    try:
        # Use client's find_resource_by_name method
        result = await client.find_resource_by_name(
            resource_type=resource_type,
            name=name,
            organization=organization,
        )

        return result if isinstance(result, dict) else None

    except Exception as e:
        logger.error(
            "error_finding_existing_resource",
            resource_type=resource_type,
            name=name,
            error=str(e),
        )
        return None


def compare_resources(
    resource1: dict[str, Any],
    resource2: dict[str, Any],
    ignore_fields: list[str] | None = None,
) -> bool:
    """Compare two resources for equality, optionally ignoring specific fields.

    Uses hash comparison for efficient equality checking. Field order
    does not affect comparison.

    Args:
        resource1: First resource dictionary
        resource2: Second resource dictionary
        ignore_fields: Optional list of fields to ignore in comparison
            (e.g., ["id", "created", "modified"])

    Returns:
        True if resources are equal (after ignoring specified fields)

    Examples:
        >>> resource1 = {"name": "test", "description": "Test", "id": 100}
        >>> resource2 = {"name": "test", "description": "Test", "id": 200}
        >>> compare_resources(resource1, resource2, ignore_fields=["id"])
        True

        >>> compare_resources(resource1, resource2)
        False
    """
    if ignore_fields is None:
        ignore_fields = []

    # Add common auto-generated fields to ignore list
    default_ignore = ["id", "created", "modified", "url", "related"]
    all_ignore_fields = list(set(ignore_fields + default_ignore))

    # Compare using hashes
    hash1 = hash_resource(resource1, exclude_fields=all_ignore_fields)
    hash2 = hash_resource(resource2, exclude_fields=all_ignore_fields)

    return hash1 == hash2


def is_duplicate(
    resource: dict[str, Any],
    existing_resources: list[dict[str, Any]],
    key_fields: list[str],
) -> bool:
    """Check if a resource is a duplicate of any in a list.

    Determines if a resource already exists in a list of resources by
    comparing unique keys generated from specified fields.

    Args:
        resource: Resource to check
        existing_resources: List of existing resources
        key_fields: Fields that uniquely identify resources

    Returns:
        True if resource is a duplicate, False otherwise

    Examples:
        >>> resource = {"name": "test-inv", "organization": 1}
        >>> existing = [{"name": "test-inv", "organization": 1}]
        >>> is_duplicate(resource, existing, ["name", "organization"])
        True

        >>> existing = [{"name": "other-inv", "organization": 1}]
        >>> is_duplicate(resource, existing, ["name", "organization"])
        False
    """
    if not existing_resources:
        return False

    # Generate key for the resource
    resource_key = generate_resource_key(resource, key_fields)

    # Check if any existing resource has the same key
    for existing in existing_resources:
        existing_key = generate_resource_key(existing, key_fields)
        if resource_key == existing_key:
            return True

    return False


def deduplicate_list(
    resources: list[dict[str, Any]],
    key_fields: list[str],
) -> list[dict[str, Any]]:
    """Remove duplicate resources from a list, keeping first occurrence.

    Creates a deduplicated list by comparing unique keys. Preserves the
    order of first occurrences.

    Args:
        resources: List of resources that may contain duplicates
        key_fields: Fields that uniquely identify resources

    Returns:
        List of unique resources (first occurrences preserved)

    Examples:
        >>> resources = [
        ...     {"name": "inv1", "org": 1, "id": 1},
        ...     {"name": "inv2", "org": 1, "id": 2},
        ...     {"name": "inv1", "org": 1, "id": 3},  # Duplicate
        ... ]
        >>> deduplicated = deduplicate_list(resources, ["name", "org"])
        >>> len(deduplicated)
        2
        >>> deduplicated[0]["id"]  # First occurrence
        1
    """
    if not resources:
        return []

    seen_keys = set()
    unique_resources = []

    for resource in resources:
        key = generate_resource_key(resource, key_fields)

        if key not in seen_keys:
            seen_keys.add(key)
            unique_resources.append(resource)

    if len(unique_resources) < len(resources):
        logger.info(
            "removed_duplicates",
            original_count=len(resources),
            unique_count=len(unique_resources),
            removed_count=len(resources) - len(unique_resources),
        )

    return unique_resources
