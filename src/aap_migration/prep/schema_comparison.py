"""Schema comparison module.

This module compares source (AAP 2.3) and target (AAP 2.6) schemas
to identify field differences and generate transformation rules.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


def compare_schemas(
    source_schema: dict[str, Any],
    target_schema: dict[str, Any],
) -> dict[str, Any]:
    """Compare source and target schemas to generate transformation rules.

    Args:
        source_schema: Source schema from schema_generator
        target_schema: Target schema from schema_generator

    Returns:
        Dictionary containing:
        - generated_at: ISO timestamp
        - source_version: Source API version
        - target_version: Target API version
        - transformations: Dict of resource_type -> transformation_rules
    """
    source_version = source_schema["api_version"]
    target_version = target_schema["api_version"]

    logger.info(
        "comparing_schemas",
        source_version=source_version,
        target_version=target_version,
    )

    transformations: dict[str, dict[str, Any]] = {}
    source_schemas = source_schema.get("schemas", {})
    target_schemas = target_schema.get("schemas", {})

    # Get all resource types from both schemas
    all_resource_types = set(source_schemas.keys()) | set(target_schemas.keys())

    for resource_type in sorted(all_resource_types):
        source_fields = source_schemas.get(resource_type, {}).get("fields", {})
        target_fields = target_schemas.get(resource_type, {}).get("fields", {})

        # Handle case where target schema is unavailable (e.g., server error)
        # Use source schema as fallback
        if source_fields and not target_fields:
            logger.info(
                "using_source_schema_fallback",
                resource_type=resource_type,
                reason="Target schema unavailable (likely server error during prep)",
            )
            # Use source schema for both - assume compatible
            transformations[resource_type] = {
                "fields_removed": [],
                "fields_added": {},
                "field_renames": {},
                "fields_type_changed": {},
                "new_required_defaults": {},
                "notes": ["Using source schema as fallback - target schema unavailable"],
                "requires_manual_verification": True,
            }
            continue

        # Skip if resource type doesn't exist in both (and not using fallback)
        if not source_fields or not target_fields:
            logger.debug(
                "resource_type_skipped",
                resource_type=resource_type,
                in_source=bool(source_fields),
                in_target=bool(target_fields),
            )
            continue

        # Identify field changes
        source_field_names = set(source_fields.keys())
        target_field_names = set(target_fields.keys())

        fields_removed = sorted(source_field_names - target_field_names)
        fields_added = sorted(target_field_names - source_field_names)
        fields_common = sorted(source_field_names & target_field_names)

        # Check for type changes in common fields
        fields_type_changed = {}
        for field_name in fields_common:
            source_type = source_fields[field_name].get("type")
            target_type = target_fields[field_name].get("type")
            if source_type != target_type:
                fields_type_changed[field_name] = {
                    "source_type": source_type,
                    "target_type": target_type,
                }

        # Check for required status changes
        fields_required_changed = {}
        for field_name in fields_common:
            source_required = source_fields[field_name].get("required", False)
            target_required = target_fields[field_name].get("required", False)
            if source_required != target_required:
                fields_required_changed[field_name] = {
                    "source_required": source_required,
                    "target_required": target_required,
                }

        # Build transformation rules for this resource type
        transformation: dict[str, Any] = {
            "fields_removed": fields_removed,
            "fields_added": fields_added,
            "fields_unchanged": fields_common,
            "fields_renamed": {},
            "fields_type_changed": fields_type_changed,
            "fields_required_changed": fields_required_changed,
        }

        # Add defaults for new required fields
        new_required_defaults = {}
        for field_name in fields_added:
            field_spec = target_fields[field_name]
            if field_spec.get("required") and not field_spec.get("read_only"):
                # Required field added - need default
                new_required_defaults[field_name] = field_spec.get("default")

        if new_required_defaults:
            transformation["new_required_defaults"] = new_required_defaults

        transformations[resource_type] = transformation

        logger.debug(
            "resource_type_compared",
            resource_type=resource_type,
            fields_removed=len(fields_removed),
            fields_added=len(fields_added),
            fields_type_changed=len(fields_type_changed),
        )

    logger.info(
        "schemas_compared",
        source_version=source_version,
        target_version=target_version,
        resource_types_compared=len(transformations),
    )

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_version": source_version,
        "target_version": target_version,
        "transformations": transformations,
    }

    return result


def save_comparison(
    comparison_data: dict[str, Any],
    output_file: Path,
) -> None:
    """Save schema comparison to JSON file.

    Args:
        comparison_data: Comparison data from compare_schemas()
        output_file: Path to output JSON file
    """
    logger.info(
        "saving_comparison",
        output_file=str(output_file),
        transformation_count=len(comparison_data.get("transformations", {})),
    )

    # Create parent directory if it doesn't exist
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON file
    with open(output_file, "w") as f:
        json.dump(comparison_data, f, indent=2)

    logger.info(
        "comparison_saved",
        output_file=str(output_file),
        file_size=output_file.stat().st_size,
    )


def load_comparison(comparison_file: Path) -> dict[str, Any]:
    """Load schema comparison from JSON file.

    Args:
        comparison_file: Path to comparison JSON file

    Returns:
        Comparison data

    Raises:
        FileNotFoundError: If file doesn't exist
        JSONDecodeError: If file is not valid JSON
    """
    logger.debug("loading_comparison", file=str(comparison_file))

    with open(comparison_file) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid comparison file: {comparison_file}")

    logger.debug(
        "comparison_loaded",
        file=str(comparison_file),
        transformation_count=len(data.get("transformations", {})),
    )

    return data
