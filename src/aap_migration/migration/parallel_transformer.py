"""Parallel transformation coordinator for multiple resource types.

This module provides a coordinator that transforms different resource types
concurrently to maximize throughput.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.config import MigrationConfig, PerformanceConfig
from aap_migration.migration.organization_scope import (
    TRANSFORM_ORG_FILTER_RESOURCES,
    OrganizationScope,
    should_include_user_for_org,
)
from aap_migration.migration.state import MigrationState
from aap_migration.migration.transformer import SkipResourceError, create_transformer
from aap_migration.resources import normalize_resource_type
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


class ParallelTransformCoordinator:
    """Coordinates parallel transformation of multiple resource types."""

    def __init__(
        self,
        migration_state: MigrationState,
        performance_config: PerformanceConfig,
        input_dir: Path,
        output_dir: Path,
        schema_comparison_file: str | None = None,
        target_client: AAPTargetClient | None = None,
        skip_pending_deletion: bool = True,
        config: MigrationConfig | None = None,
        defer_project_sync: bool = True,
        org_scope: OrganizationScope | None = None,
        exported_ids_for_org: dict[str, set[int]] | None = None,
    ):
        """Initialize parallel transform coordinator.

        Args:
            migration_state: Migration state manager
            performance_config: Performance configuration
            input_dir: Input directory with RAW exports
            output_dir: Output directory for transformed data
            schema_comparison_file: Path to schema comparison file
            target_client: AAP target client (for pre-populating IDs)
            skip_pending_deletion: Whether to skip pending_deletion resources
            config: Optional migration configuration (for resource mappings)
            defer_project_sync: Whether to defer SCM sync for projects
        """
        self.migration_state = migration_state
        self.performance_config = performance_config
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.schema_comparison_file = schema_comparison_file
        self.target_client = target_client
        self.skip_pending_deletion = skip_pending_deletion
        self.config = config
        self.defer_project_sync = defer_project_sync
        self.org_scope = org_scope
        self.exported_ids_for_org = exported_ids_for_org or {}
        self.results: dict[str, dict[str, Any]] = {}

        # Lock for thread-safe state operations (if needed)
        self._state_lock = asyncio.Lock()

    async def transform_resource_type(
        self,
        resource_type: str,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Transform a single resource type.

        Args:
            resource_type: Type of resource to transform
            progress_callback: Optional callback for progress updates

        Returns:
            Transform statistics for this resource type
        """
        # Normalize resource type
        resource_type = normalize_resource_type(resource_type)

        stats = {
            "resource_type": resource_type,
            "count": 0,
            "failed": 0,
            "files": 0,
            "skipped_pending_deletion": 0,
            "skipped_custom_managed": 0,
            "skipped_missing_inventory": 0,
            "skipped_smart_inventories": 0,
            "skipped_dynamic_hosts": 0,
            "skipped_from_transformer": 0,  # New field for skips from transformer.stats
            "fields_removed": 0,
            "fields_added": 0,
            "fields_renamed": 0,
        }

        # Read RAW files from input directory
        input_type_dir = self.input_dir / resource_type
        if not input_type_dir.exists():
            logger.warning("input_dir_not_found", resource_type=resource_type)
            return stats

        # Find all JSON files
        json_files = sorted(input_type_dir.glob(f"{resource_type}_*.json"))
        if not json_files:
            logger.warning("no_files_found", resource_type=resource_type)
            return stats

        # Create output directory
        output_type_dir = self.output_dir / resource_type
        output_type_dir.mkdir(parents=True, exist_ok=True)

        # Create transformer
        transformer = create_transformer(
            resource_type=resource_type,
            dry_run=False,
            schema_comparison_file=self.schema_comparison_file,
            state=self.migration_state,
            input_dir=self.input_dir,
            config=self.config,
            defer_project_sync=self.defer_project_sync,
        )

        output_file_num = 0

        for json_file in json_files:
            try:
                with open(json_file) as f:
                    raw_resources = json.load(f)

                # 0. Filter out resources skipped during export
                # These are marked with "_skipped": true by the exporter (e.g. system jobs)
                active_resources = []
                for resource in raw_resources:
                    if resource.get("_skipped"):
                        continue
                    active_resources.append(resource)
                raw_resources = active_resources

                if (
                    self.org_scope
                    and resource_type in TRANSFORM_ORG_FILTER_RESOURCES
                ):
                    raw_resources = [
                        resource
                        for resource in raw_resources
                        if should_include_user_for_org(resource, self.exported_ids_for_org)
                    ]

                # 1. Filter out inventory (pending_deletion and smart)
                if resource_type == "inventory":
                    filtered_resources = []
                    for resource in raw_resources:
                        if self.skip_pending_deletion and resource.get("pending_deletion"):
                            logger.debug(
                                "skipping_pending_deletion_inventory",
                                resource_type=resource_type,
                                source_id=resource.get("_source_id") or resource.get("id"),
                            )
                            stats["skipped_pending_deletion"] += 1
                        elif (
                            self.config
                            and self.config.export.skip_smart_inventories
                            and resource.get("kind") == "smart"
                        ):
                            logger.debug(
                                "skipping_smart_inventory",
                                resource_type=resource_type,
                                source_id=resource.get("_source_id") or resource.get("id"),
                            )
                            stats["skipped_smart_inventories"] += 1
                        elif (
                            self.config
                            and self.config.export.skip_constructed_inventories
                            and resource.get("kind") == "constructed"
                        ):
                            logger.debug(
                                "skipping_constructed_inventory",
                                resource_type=resource_type,
                                source_id=resource.get("_source_id") or resource.get("id"),
                            )
                            stats["skipped_smart_inventories"] += 1
                        else:
                            filtered_resources.append(resource)
                    raw_resources = filtered_resources

                # 2. Filter out custom managed credential_types
                if resource_type == "credential_types":
                    filtered_resources = []
                    for resource in raw_resources:
                        is_managed = resource.get("managed", False)
                        summary_fields = resource.get("summary_fields", {})
                        related = resource.get("related", {})

                        has_created_by = "created_by" in summary_fields or "created_by" in related

                        if is_managed and has_created_by:
                            stats["skipped_custom_managed"] += 1
                        else:
                            filtered_resources.append(resource)
                    raw_resources = filtered_resources

                # 3. Filter out dynamic hosts (only when config flag is set)
                if (
                    resource_type == "hosts"
                    and self.config
                    and self.config.export.skip_dynamic_hosts
                ):
                    filtered_resources = []
                    for resource in raw_resources:
                        if resource.get("has_inventory_sources"):
                            logger.debug(
                                "skipping_dynamic_host",
                                resource_type=resource_type,
                                source_id=resource.get("_source_id") or resource.get("id"),
                            )
                            stats["skipped_dynamic_hosts"] += 1
                        else:
                            filtered_resources.append(resource)
                    raw_resources = filtered_resources

                # Transform batch
                transformed_batch = []
                for resource in raw_resources:
                    try:
                        # Transform resource
                        transformed = transformer.transform_resource(resource_type, resource)

                        # Preserve _source_id
                        source_id = resource.get("_source_id") or resource.get("id")
                        transformed["_source_id"] = source_id

                        transformed_batch.append(transformed)
                        stats["count"] += 1
                    except SkipResourceError as e:
                        logger.warning(
                            "resource_skipped_error",
                            resource_type=resource_type,
                            source_id=e.source_id,
                            reason=str(e),
                        )
                        stats["skipped_from_transformer"] += 1
                    except Exception as e:
                        logger.warning(
                            "transformation_failed",
                            resource_type=resource_type,
                            source_id=resource.get("_source_id") or resource.get("id"),
                            error=str(e),
                        )
                        stats["failed"] += 1

                    # Update progress
                    if progress_callback:
                        progress_callback(resource_type, stats)

                # 3. Filter hosts whose inventory is not in id_mappings
                if resource_type == "hosts":
                    filtered_batch = []
                    for host in transformed_batch:
                        inventory_id = host.get("inventory")
                        if inventory_id and self.migration_state.has_source_mapping(
                            "inventory", inventory_id
                        ):
                            filtered_batch.append(host)
                        else:
                            stats["skipped_missing_inventory"] += 1
                    transformed_batch = filtered_batch

                # 4. Pre-populate ID mappings from target (credentials/credential_types)
                if resource_type in ["credentials", "credential_types"] and self.target_client:
                    try:
                        mapped_count = 0
                        for resource in transformed_batch:
                            source_id = resource.get("_source_id")
                            if source_id:
                                await transformer.populate_target_id_from_target(
                                    resource,
                                    self.target_client,
                                    self.migration_state,
                                    source_id,
                                )
                                mapped_count += 1
                    except Exception as e:
                        logger.warning("populate_target_id_failed", error=str(e))

                # Split constructed inventories into separate directory
                if resource_type == "inventory":
                    constructed_batch = [
                        r for r in transformed_batch if r.get("kind") == "constructed"
                    ]
                    if constructed_batch:
                        ci_dir = self.output_dir / "constructed_inventories"
                        ci_dir.mkdir(parents=True, exist_ok=True)
                        ci_file = ci_dir / f"constructed_inventories_{output_file_num + 1:04d}.json"
                        with open(ci_file, "w") as f:
                            json.dump(constructed_batch, f, indent=2)
                        logger.info(
                            "constructed_inventories_split",
                            count=len(constructed_batch),
                            file=str(ci_file),
                        )
                        # Remove constructed from regular batch
                        transformed_batch = [
                            r for r in transformed_batch if r.get("kind") != "constructed"
                        ]

                # Write output file (even if empty)
                output_file_num += 1
                output_file = output_type_dir / f"{resource_type}_{output_file_num:04d}.json"
                with open(output_file, "w") as f:
                    json.dump(transformed_batch, f, indent=2)

            except Exception as e:
                logger.error(
                    "transform_file_failed",
                    file=str(json_file),
                    error=str(e),
                )
                continue

        # Add transformer stats
        if transformer:
            stats["fields_removed"] = transformer.stats.get("fields_removed", 0)
            stats["fields_added"] = transformer.stats.get("fields_added", 0)
            stats["fields_renamed"] = transformer.stats.get("fields_renamed", 0)

        stats["files"] = output_file_num
        return stats

    async def transform_all_parallel(
        self,
        resource_types: list[str],
        progress_callback: Any | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Transform multiple resource types in parallel.

        Args:
            resource_types: List of resource types to transform
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary of statistics per resource type
        """
        max_concurrent = self.performance_config.max_concurrent_types
        semaphore = asyncio.Semaphore(max_concurrent)

        logger.info(
            "parallel_transform_all_started",
            resource_types_count=len(resource_types),
            max_concurrent=max_concurrent,
        )

        async def transform_with_semaphore(rtype: str) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                result = await self.transform_resource_type(rtype, progress_callback)
                return rtype, result

        tasks = [transform_with_semaphore(rtype) for rtype in resource_types]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results:
            if isinstance(item, BaseException):
                logger.error("parallel_transform_task_exception", error=str(item))
            else:
                rtype, stats = item
                self.results[rtype] = stats

        return self.results
