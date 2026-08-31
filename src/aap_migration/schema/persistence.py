"""Schema persistence for saving and loading AAP API schemas."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aap_migration.schema.models import ComparisonResult
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


async def save_schemas(
    source_schemas: dict[str, dict[str, Any]],
    target_schemas: dict[str, dict[str, Any]],
    comparisons: dict[str, ComparisonResult],
    output_dir: Path | str,
    source_url: str,
    target_url: str,
    source_version: str,
    target_version: str,
) -> dict[str, Path]:
    """Save schemas and comparison to JSON files.

    Args:
        source_schemas: Dict of {resource_type: schema} from source AAP
        target_schemas: Dict of {resource_type: schema} from target AAP
        comparisons: Dict of {resource_type: ComparisonResult}
        output_dir: Directory to save schemas
        source_url: Source AAP URL
        target_url: Target AAP URL
        source_version: Source AAP version
        target_version: Target AAP version

    Returns:
        Dict of {filename: Path} for created files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).isoformat()
    created_files = {}

    # Save AAP 2.3 schemas
    source_file = output_path / f"aap_{source_version}_schemas.json"
    source_data = {
        "generated_at": timestamp,
        "aap_version": source_version,
        "source_url": source_url,
        "schemas": source_schemas,
    }

    with open(source_file, "w") as f:
        json.dump(source_data, f, indent=2)
    created_files["source_schemas"] = source_file

    logger.info(
        "source_schemas_saved",
        file=str(source_file),
        resource_types=len(source_schemas),
    )

    # Save AAP 2.6 schemas
    target_file = output_path / f"aap_{target_version}_schemas.json"
    target_data = {
        "generated_at": timestamp,
        "aap_version": target_version,
        "source_url": target_url,
        "schemas": target_schemas,
    }

    with open(target_file, "w") as f:
        json.dump(target_data, f, indent=2)
    created_files["target_schemas"] = target_file

    logger.info(
        "target_schemas_saved",
        file=str(target_file),
        resource_types=len(target_schemas),
    )

    # Save schema comparison
    comparison_file = output_path / "schema_comparison.json"
    comparison_data = {
        "generated_at": timestamp,
        "source_version": source_version,
        "target_version": target_version,
        "source_url": source_url,
        "target_url": target_url,
        "resources": {
            resource_type: comparison.to_dict() for resource_type, comparison in comparisons.items()
        },
    }

    with open(comparison_file, "w") as f:
        json.dump(comparison_data, f, indent=2)
    created_files["comparison"] = comparison_file

    logger.info(
        "schema_comparison_saved",
        file=str(comparison_file),
        resource_types=len(comparisons),
        breaking_changes=sum(1 for c in comparisons.values() if c.has_breaking_changes),
    )

    return created_files


def load_comparison(schema_file: Path | str) -> dict[str, Any]:
    """Load schema comparison from JSON file.

    Args:
        schema_file: Path to schema_comparison.json

    Returns:
        Loaded comparison data

    Raises:
        FileNotFoundError: If schema file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    schema_path = Path(schema_file)

    if not schema_path.exists():
        raise FileNotFoundError(
            f"Schema comparison file not found: {schema_path}. "
            f"Run 'aap-bridge schema generate' first."
        )

    with open(schema_path) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid schema comparison file: {schema_path}")

    logger.info(
        "schema_comparison_loaded",
        file=str(schema_path),
        resource_types=len(data.get("resources", {})),
        generated_at=data.get("generated_at"),
    )

    return data


def load_schemas(schemas_dir: Path | str, version: str) -> dict[str, dict[str, Any]]:
    """Load AAP schemas from JSON file.

    Args:
        schemas_dir: Directory containing schema files
        version: AAP version (e.g., "2.3", "2.4", "2.6")

    Returns:
        Dict of {resource_type: schema}

    Raises:
        FileNotFoundError: If schema file doesn't exist
    """
    schemas_path = Path(schemas_dir) / f"aap_{version}_schemas.json"

    if not schemas_path.exists():
        raise FileNotFoundError(
            f"Schema file not found: {schemas_path}. Run 'aap-bridge schema generate' first."
        )

    with open(schemas_path) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid schema file: {schemas_path}")

    schemas = data.get("schemas", {})
    if not isinstance(schemas, dict):
        raise ValueError(f"Invalid schema file: {schemas_path}")

    logger.info(
        "schemas_loaded",
        file=str(schemas_path),
        version=version,
        resource_types=len(schemas),
    )

    return schemas


def schema_files_exist(schemas_dir: Path | str) -> bool:
    """Check if schema files exist in directory.

    Args:
        schemas_dir: Directory to check

    Returns:
        True if required schema files exist
    """
    schemas_path = Path(schemas_dir)
    comparison_file = schemas_path / "schema_comparison.json"

    # The existence of schema_comparison.json is the primary indicator
    # that schemas have been generated and compared.
    return comparison_file.exists()


def get_schema_info(schemas_dir: Path | str) -> dict[str, Any] | None:
    """Get information about existing schemas.

    Args:
        schemas_dir: Directory containing schemas

    Returns:
        Schema metadata or None if files don't exist
    """
    comparison_file = Path(schemas_dir) / "schema_comparison.json"

    if not comparison_file.exists():
        return None

    try:
        with open(comparison_file) as f:
            data = json.load(f)

        return {
            "generated_at": data.get("generated_at"),
            "source_version": data.get("source_version"),
            "target_version": data.get("target_version"),
            "source_url": data.get("source_url"),
            "target_url": data.get("target_url"),
            "resource_count": len(data.get("resources", {})),
            "breaking_changes": sum(
                1
                for r in data.get("resources", {}).values()
                if r.get("severity") in ["HIGH", "CRITICAL"]
            ),
        }
    except Exception as e:
        logger.error("failed_to_read_schema_info", error=str(e))
        return None
