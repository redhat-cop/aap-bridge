"""Parallel export coordinator for multiple resource types.

This module provides a coordinator that exports different resource types
concurrently to maximize throughput while respecting concurrency limits.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.config import ExportConfig, PerformanceConfig
from aap_migration.migration.exporter import create_exporter
from aap_migration.migration.state import MigrationState
from aap_migration.resources import get_endpoint, normalize_resource_type
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


class ParallelExportCoordinator:
    """Coordinates parallel export of multiple resource types.

    This coordinator exports different resource types concurrently,
    with each type using parallel page fetching internally.
    This provides two levels of parallelism:
    1. Multiple resource types exported at once
    2. Multiple pages fetched concurrently within each type
    """

    def __init__(
        self,
        source_client: AAPSourceClient,
        migration_state: MigrationState,
        performance_config: PerformanceConfig,
        output_dir: Path,
        records_per_file: int = 1000,
        export_config: ExportConfig | None = None,
    ):
        """Initialize parallel export coordinator.

        Args:
            source_client: AAP source client
            migration_state: Migration state manager
            performance_config: Performance configuration
            output_dir: Output directory for exports
            records_per_file: Maximum records per file
            export_config: Export configuration (for skip_dynamic_hosts, etc.)
        """
        self.source_client = source_client
        self.migration_state = migration_state
        self.performance_config = performance_config
        self.output_dir = output_dir
        self.records_per_file = records_per_file
        self.export_config = export_config or ExportConfig()
        self.results: dict[str, dict[str, Any]] = {}

        # Lock for thread-safe state operations
        self._state_lock = asyncio.Lock()

        logger.info(
            "parallel_export_coordinator_initialized",
            output_dir=str(output_dir),
            max_concurrent_types=performance_config.max_concurrent_types,
            max_concurrent_pages=performance_config.max_concurrent_pages,
            records_per_file=records_per_file,
            skip_dynamic_hosts=self.export_config.skip_dynamic_hosts,
        )

    async def export_resource_type(
        self,
        resource_type: str,
        resume: bool = False,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Export a single resource type with parallel page fetching.

        Args:
            resource_type: Type of resource to export
            resume: Whether to resume from checkpoint
            progress_callback: Optional callback for progress updates

        Returns:
            Export statistics for this resource type
        """
        # Normalize resource type
        resource_type = normalize_resource_type(resource_type)

        stats: dict[str, Any] = {
            "resource_type": resource_type,
            "exported": 0,
            "failed": 0,
            "skipped": 0,
            "files_written": 0,
        }

        logger.info(
            "parallel_export_type_started",
            resource_type=resource_type,
            resume=resume,
        )

        try:
            # Create exporter for this resource type
            try:
                exporter = create_exporter(
                    resource_type,
                    self.source_client,
                    self.migration_state,
                    self.performance_config,
                    skip_execution_environment_names=self.export_config.skip_execution_environment_names,
                    skip_credential_names=self.export_config.skip_credential_names,
                )
            except NotImplementedError as e:
                # No exporter for this resource type - skip it gracefully
                logger.warning(
                    "no_exporter_for_type",
                    resource_type=resource_type,
                    message=str(e),
                )
                stats["skipped"] += 1
                stats["skip_reason"] = "No exporter implemented"
                return stats

            # Apply skip_dynamic_hosts filter for hosts
            if resource_type == "hosts" and self.export_config.skip_dynamic_hosts:
                if hasattr(exporter, "set_skip_dynamic_hosts"):
                    exporter.set_skip_dynamic_hosts(True)
                    logger.info(
                        "parallel_export_skip_dynamic_hosts_enabled",
                        message="Filtering out hosts from dynamic inventory sources",
                    )

            # Apply skip_smart_inventories filter for inventory
            if resource_type == "inventory" and self.export_config.skip_smart_inventories:
                if hasattr(exporter, "set_skip_smart_inventories"):
                    exporter.set_skip_smart_inventories(True)
                    logger.info(
                        "parallel_export_skip_smart_inventories_enabled",
                        message="Filtering out smart inventories (kind='smart')",
                    )

            # Set resume checkpoint if enabled
            if resume:
                max_exported_id = self.migration_state.get_max_exported_id(resource_type)
                if max_exported_id is not None:
                    exporter.set_resume_checkpoint(max_exported_id)
                    logger.info(
                        "parallel_export_resume_checkpoint",
                        resource_type=resource_type,
                        resume_from_id=max_exported_id,
                    )

            # Create directory for this resource type
            type_dir = self.output_dir / resource_type
            type_dir.mkdir(parents=True, exist_ok=True)

            # Get endpoint for this resource type
            endpoint = get_endpoint(resource_type)

            # Build filters for this resource type
            export_filters: dict[str, Any] = {}
            if resource_type == "hosts" and self.export_config.skip_dynamic_hosts:
                # API-level filtering: only export static hosts (not from dynamic inventory sources)
                export_filters["inventory_sources__isnull"] = "true"
                logger.info(
                    "parallel_export_applying_dynamic_host_filter",
                    message="API filter: inventory_sources__isnull=true (exclude dynamic hosts)",
                )
            if resource_type == "inventory":
                export_filters["pending_deletion"] = "false"
                logger.info(
                    "parallel_export_applying_inventory_filter",
                    message="API filter: pending_deletion=false (exclude deleted inventories)",
                )

            # Export with parallel page fetching
            current_batch: list[dict[str, Any]] = []
            file_count = 0
            pending_mappings: list[dict[str, Any]] = []
            mapping_batch_size = self.performance_config.mapping_batch_size

            iteration_count = 0
            async for resource in exporter.export_parallel(
                resource_type=resource_type,
                endpoint=endpoint,
                page_size=self.performance_config.batch_sizes.get(resource_type, 200),
                max_concurrent_pages=self.performance_config.max_concurrent_pages,
                filters=export_filters if export_filters else None,
            ):
                # Yield control to event loop to prevent UI starvation
                await asyncio.sleep(0)

                iteration_count += 1

                try:
                    # Store ID mapping
                    source_id = resource.get("id")
                    source_name = resource.get("name", "")

                    pending_mappings.append(
                        {
                            "resource_type": resource_type,
                            "source_id": source_id,
                            "target_id": None,
                            "source_name": source_name,
                        }
                    )

                    # Batch commit mappings (thread-safe)
                    if len(pending_mappings) >= mapping_batch_size:
                        async with self._state_lock:
                            self.migration_state.batch_create_mappings(
                                pending_mappings, batch_size=mapping_batch_size
                            )
                        pending_mappings = []

                    # Save RAW resource data (NO transformation)
                    # Only add source ID for tracking
                    resource["_source_id"] = source_id
                    current_batch.append(resource)
                    stats["exported"] += 1

                    # Write batch when it reaches the limit
                    if len(current_batch) >= self.records_per_file:
                        file_count += 1
                        file_path = type_dir / f"{resource_type}_{file_count:04d}.json"
                        with open(file_path, "w") as f:
                            json.dump(current_batch, f, indent=2)

                        logger.debug(
                            "parallel_export_file_written",
                            resource_type=resource_type,
                            file_number=file_count,
                            records=len(current_batch),
                        )
                        current_batch = []

                    stats["skipped"] = exporter.get_stats().get("skipped_count", 0)
                    # Progress callback (exported + skipped + failed drives TUI bar)
                    if progress_callback:
                        progress_callback(resource_type, stats)

                except Exception as e:
                    logger.warning(
                        "parallel_export_failed",
                        resource_type=resource_type,
                        resource_id=resource.get("id"),
                        error=str(e),
                    )
                    stats["failed"] += 1

            # Sync stats from exporter (resume dedup, EE name filter, etc.)
            exporter_stats = exporter.get_stats()
            stats["skipped"] = exporter_stats.get("skipped_count", 0)

            if progress_callback:
                progress_callback(resource_type, stats)

            # Commit remaining mappings
            if pending_mappings:
                async with self._state_lock:
                    self.migration_state.batch_create_mappings(
                        pending_mappings, batch_size=mapping_batch_size
                    )

            # Write remaining batch
            if current_batch:
                file_count += 1
                file_path = type_dir / f"{resource_type}_{file_count:04d}.json"
                with open(file_path, "w") as f:
                    json.dump(current_batch, f, indent=2)

            stats["files_written"] = file_count

            logger.info(
                "parallel_export_type_completed",
                resource_type=resource_type,
                exported=stats["exported"],
                failed=stats["failed"],
                files_written=stats["files_written"],
            )

        except Exception as e:
            logger.error(
                "parallel_export_type_failed",
                resource_type=resource_type,
                error=str(e),
            )
            stats["error"] = str(e)

        return stats

    async def export_all_parallel(
        self,
        resource_types: list[str],
        resume: bool = False,
        progress_callback: Any | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Export multiple resource types in parallel.

        Args:
            resource_types: List of resource types to export
            resume: Whether to resume from checkpoint
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary of statistics per resource type
        """
        max_concurrent = self.performance_config.max_concurrent_types
        semaphore = asyncio.Semaphore(max_concurrent)

        logger.info(
            "parallel_export_all_started",
            resource_types=resource_types,
            max_concurrent_types=max_concurrent,
            resume=resume,
        )

        async def export_with_semaphore(rtype: str) -> tuple[str, dict[str, Any]]:
            """Export a resource type with semaphore control."""
            async with semaphore:
                logger.info(
                    "parallel_export_type_acquiring_slot",
                    resource_type=rtype,
                )
                result = await self.export_resource_type(rtype, resume, progress_callback)
                return rtype, result

        # Create tasks for all resource types
        tasks = [export_with_semaphore(rtype) for rtype in resource_types]

        # Execute all exports concurrently (limited by semaphore)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        total_exported = 0
        total_failed = 0
        total_skipped = 0
        skipped_types = []

        for item in results:
            if isinstance(item, BaseException):
                logger.error(
                    "parallel_export_task_exception",
                    error=str(item),
                )
            else:
                rtype, stats = item
                self.results[rtype] = stats
                total_exported += stats.get("exported", 0)
                total_failed += stats.get("failed", 0)

                # Track skipped types (those without exporters)
                if stats.get("skipped", 0) > 0 and "skip_reason" in stats:
                    total_skipped += 1
                    skipped_types.append(rtype)

        logger.info(
            "parallel_export_all_completed",
            resource_types_count=len(resource_types),
            total_exported=total_exported,
            total_failed=total_failed,
            total_skipped=total_skipped,
            skipped_types=skipped_types,
            results=self.results,
        )

        return self.results

    def get_results(self) -> dict[str, dict[str, Any]]:
        """Get export results.

        Returns:
            Dictionary of statistics per resource type
        """
        return self.results.copy()
