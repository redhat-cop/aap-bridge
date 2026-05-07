"""Migration coordinator for orchestrating the full ETL pipeline.

This module provides the main coordinator that orchestrates the complete
migration process: Export → Transform → Import for all resource types
in proper dependency order.
"""

from datetime import UTC, datetime
from typing import Any

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.config import MigrationConfig
from aap_migration.migration.checkpoint import CheckpointManager
from aap_migration.migration.exporter import create_exporter
from aap_migration.migration.importer import create_importer
from aap_migration.migration.inventory_source_sync import sync_inventory_sources_after_import
from aap_migration.migration.state import MigrationState
from aap_migration.migration.transformer import SkipResourceError, create_transformer
from aap_migration.reporting.live_progress import MigrationProgressDisplay
from aap_migration.reporting.progress import ProgressTracker
from aap_migration.reporting.report import generate_migration_report
from aap_migration.schema.comparator import SchemaComparator
from aap_migration.schema.models import ComparisonResult
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


class MigrationCoordinator:
    """Coordinates the full migration pipeline.

    Orchestrates Export → Transform → Import for all resource types,
    managing dependencies, checkpoints, and error recovery.
    """

    # Migration phases in dependency order
    MIGRATION_PHASES = [
        {
            "name": "organizations",
            "description": "Organizations (foundation for most resources)",
            "resource_types": ["organizations"],
            "batch_size": 50,
        },
        {
            "name": "identity",
            "description": "Labels, Users, and Teams",
            "resource_types": ["labels", "users", "teams"],
            "batch_size": 100,
        },
        {
            "name": "credentials",
            "description": "Credential Types and Credentials",
            "resource_types": ["credential_types", "credentials"],
            "batch_size": 50,
        },
        {
            "name": "credential_input_sources",
            "description": "Credential Input Sources",
            "resource_types": ["credential_input_sources"],
            "batch_size": 100,
        },
        {
            "name": "execution_environments",
            "description": "Execution Environments",
            "resource_types": ["execution_environments"],
            "batch_size": 100,
        },
        {
            "name": "projects",
            "description": "Projects",
            "resource_types": ["projects"],
            "batch_size": 100,
        },
        {
            "name": "inventory",
            "description": "Inventories (80,000+ expected)",
            "resource_types": ["inventory"],
            "batch_size": 100,
        },
        {
            "name": "inventory_sources",
            "description": "Inventory Sources (before constructed/smart-dependent inventories)",
            "resource_types": ["inventory_sources"],
            "batch_size": 100,
        },
        {
            "name": "constructed_inventories",
            "description": "Constructed Inventories",
            "resource_types": ["constructed_inventories"],
            "batch_size": 100,
        },
        {
            "name": "groups",
            "description": "Inventory Groups",
            "resource_types": ["groups"],
            "batch_size": 100,
        },
        {
            "name": "hosts",
            "description": "Hosts (using bulk operations)",
            "resource_types": ["hosts"],
            "batch_size": 200,
            "use_bulk": True,
        },
        {
            "name": "notification_templates",
            "description": "Notification Templates",
            "resource_types": ["notification_templates"],
            "batch_size": 100,
        },
        {
            "name": "job_templates",
            "description": "Job Templates",
            "resource_types": ["job_templates"],
            "batch_size": 100,
        },
        {
            "name": "workflows",
            "description": "Workflow Job Templates",
            "resource_types": ["workflow_job_templates"],
            "batch_size": 50,
        },
        {
            "name": "system_job_templates",
            "description": "System Job Templates",
            "resource_types": ["system_job_templates"],
            "batch_size": 50,
        },
        {
            "name": "schedules",
            "description": "Schedules",
            "resource_types": ["schedules"],
            "batch_size": 100,
        },
        {
            "name": "role_definitions",
            "description": "Role Definitions",
            "resource_types": ["role_definitions"],
            "batch_size": 50,
        },
        {
            "name": "role_user_assignments",
            "description": "User Role Assignments",
            "resource_types": ["role_user_assignments"],
            "batch_size": 100,
        },
        {
            "name": "role_team_assignments",
            "description": "Team Role Assignments",
            "resource_types": ["role_team_assignments"],
            "batch_size": 100,
        },
    ]

    def __init__(
        self,
        config: MigrationConfig,
        source_client: AAPSourceClient,
        target_client: AAPTargetClient,
        state: MigrationState,
        enable_progress: bool = True,
        show_stats: bool = False,
    ):
        """Initialize migration coordinator.

        Args:
            config: Migration configuration
            source_client: AAP 2.3 source client
            target_client: AAP 2.6 target client
            state: Migration state manager
            enable_progress: Whether to enable progress bars (disable for CI/automation)
            show_stats: Whether to show detailed statistics in progress display
        """
        self.config = config
        self.source_client = source_client
        self.target_client = target_client
        self.state = state
        self.checkpoint_manager = CheckpointManager(state)
        self.progress_tracker: ProgressTracker | None = None
        self.progress_display: MigrationProgressDisplay | None = None
        self._current_phase_id: str | None = None  # For progress_display updates
        self.enable_progress = enable_progress
        self.show_stats = show_stats

        # Schema comparison results (populated by compare_schemas_before_migration)
        self.schema_comparisons: dict[str, ComparisonResult] = {}
        self.schema_comparator = SchemaComparator()

        self.metrics = {
            "start_time": None,
            "end_time": None,
            "phases_completed": 0,
            "phases_failed": 0,
            "total_resources_exported": 0,
            "total_resources_imported": 0,
            "total_resources_failed": 0,
            "total_resources_skipped": 0,
            "errors": [],
            "skipped_items": [],
        }

        logger.info(
            "migration_coordinator_initialized",
            source_url=config.source.url,
            target_url=config.target.url,
            dry_run=config.dry_run,
        )

    async def migrate_all(
        self,
        skip_phases: list[str] | None = None,
        only_phases: list[str] | None = None,
        generate_report: bool = True,
        report_dir: str = "./reports",
    ) -> dict[str, Any]:
        """Execute full migration pipeline.

        Args:
            skip_phases: Optional list of phase names to skip
            only_phases: Optional list of phase names to migrate (mutually exclusive with skip_phases)
            generate_report: Whether to generate migration reports
            report_dir: Directory to save reports

        Returns:
            Migration summary with statistics
        """
        self.metrics["start_time"] = datetime.now(UTC)

        # Determine which phases to execute
        phases_to_execute = self._determine_phases(skip_phases, only_phases)

        # Initialize progress display (new Rich-based display)
        if self.enable_progress:
            # Also keep old ProgressTracker for backward compatibility
            self.progress_tracker = ProgressTracker(
                total_phases=len(phases_to_execute),
                enable=True,
            )
            self.progress_display = MigrationProgressDisplay(
                enabled=True,
                show_stats=self.show_stats,
            )
        else:
            self.progress_display = MigrationProgressDisplay(enabled=False)

        logger.info(
            "migration_started",
            dry_run=self.config.dry_run,
            skip_phases=skip_phases,
            only_phases=only_phases,
            total_phases=len(phases_to_execute),
        )

        try:
            # Use progress display as context manager
            with self.progress_display:
                self.progress_display.set_total_phases(len(phases_to_execute))

                for phase in phases_to_execute:
                    try:
                        logger.info(
                            "phase_starting",
                            phase_name=phase["name"],
                            description=phase["description"],
                            resource_types=phase["resource_types"],
                        )

                        # Start phase progress tracking (both old and new)
                        if self.progress_tracker:
                            self.progress_tracker.start_phase(phase["name"])

                        # Start new Rich progress display for this phase
                        # Note: Using estimated count of 100 for now; will be updated after export
                        phase_id = self.progress_display.start_phase(
                            phase_name=phase["name"],
                            resource_type=phase["description"],
                            total_items=100,  # Initial estimate, updated during execution
                        )
                        self._current_phase_id = phase_id  # Store for use in ETL pipeline

                        await self._execute_phase(phase)

                        self.metrics["phases_completed"] += 1

                        # Complete phase progress tracking (both old and new)
                        if self.progress_tracker:
                            self.progress_tracker.complete_phase()

                        self.progress_display.complete_phase(phase_id)

                        logger.info(
                            "phase_completed",
                            phase_name=phase["name"],
                            phases_completed=self.metrics["phases_completed"],
                        )

                    except Exception as e:
                        logger.error(
                            "phase_failed",
                            phase_name=phase["name"],
                            error=str(e),
                            exc_info=True,
                        )

                        self.metrics["phases_failed"] += 1
                        self.metrics["errors"].append(
                            {
                                "phase": phase["name"],
                                "error": str(e),
                                "timestamp": datetime.now(UTC).isoformat(),
                            }
                        )

                        # Stop on first failure unless configured otherwise
                        if not self.config.skip_validation:  # Using this as "continue on error"
                            raise

        finally:
            # Close progress tracker
            if self.progress_tracker:
                self.progress_tracker.close()

        self.metrics["end_time"] = datetime.now(UTC)

        summary = self._generate_summary()

        # Generate reports
        if generate_report:
            try:
                report_files = generate_migration_report(
                    migration_id=self.state.migration_id,
                    summary=summary,
                    output_dir=report_dir,
                    formats=["json", "markdown", "html"],
                )
                summary["report_files"] = report_files
                logger.info("migration_reports_generated", files=report_files)
            except Exception as e:
                logger.error("report_generation_failed", error=str(e))

        return summary

    async def migrate_phase(self, phase_name: str) -> dict[str, Any]:
        """Execute migration for a specific phase.

        Args:
            phase_name: Name of phase to migrate

        Returns:
            Phase migration summary
        """
        # Find phase configuration
        phase = None
        for p in self.MIGRATION_PHASES:
            if p["name"] == phase_name:
                phase = p
                break

        if not phase:
            raise ValueError(f"Unknown phase: {phase_name}")

        logger.info("single_phase_migration", phase_name=phase_name)

        await self._execute_phase(phase)

        return {
            "phase": phase_name,
            "status": "completed",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _execute_phase(self, phase: dict[str, Any]) -> None:
        """Execute a single migration phase.

        Args:
            phase: Phase configuration dictionary
        """
        phase_name = phase["name"]
        resource_types = phase["resource_types"]

        phase_stats = {
            "exported": 0,
            "transformed": 0,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
        }

        for resource_type in resource_types:
            try:
                logger.info(
                    "processing_resource_type",
                    phase=phase_name,
                    resource_type=resource_type,
                )

                # Execute ETL pipeline for this resource type
                stats = await self._execute_etl_pipeline(
                    resource_type=resource_type,
                    phase_config=phase,
                )

                # Update phase statistics
                phase_stats["exported"] += stats.get("exported", 0)
                phase_stats["transformed"] += stats.get("transformed", 0)
                phase_stats["imported"] += stats.get("imported", 0)
                phase_stats["failed"] += stats.get("failed", 0)
                phase_stats["skipped"] += stats.get("skipped", 0)

                logger.info(
                    "resource_type_completed",
                    phase=phase_name,
                    resource_type=resource_type,
                    stats=stats,
                )

            except Exception as e:
                logger.error(
                    "resource_type_failed",
                    phase=phase_name,
                    resource_type=resource_type,
                    error=str(e),
                )
                phase_stats["failed"] += 1
                raise

        # Update global metrics
        self.metrics["total_resources_exported"] += phase_stats["exported"]
        self.metrics["total_resources_imported"] += phase_stats["imported"]
        self.metrics["total_resources_failed"] += phase_stats["failed"]
        self.metrics["total_resources_skipped"] += phase_stats["skipped"]

        # Create checkpoint after phase completion
        if not self.config.dry_run:
            checkpoint_id = self.checkpoint_manager.create_checkpoint(
                phase=phase_name,
                description=f"Completed {phase['description']}",
                progress_stats=phase_stats,
            )

            logger.info(
                "checkpoint_created",
                phase=phase_name,
                checkpoint_id=checkpoint_id,
                stats=phase_stats,
            )

    async def _execute_etl_pipeline(
        self,
        resource_type: str,
        phase_config: dict[str, Any],
    ) -> dict[str, int]:
        """Execute Export → Transform → Import pipeline for a resource type.

        Args:
            resource_type: Type of resource to migrate
            phase_config: Phase configuration

        Returns:
            Statistics for this resource type
        """
        stats = {
            "exported": 0,
            "transformed": 0,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
        }

        try:
            # Create exporter, transformer, importer
            exporter = create_exporter(
                resource_type=resource_type,
                client=self.source_client,
                state=self.state,
                performance_config=self.config.performance,
                skip_execution_environment_names=self.config.export.skip_execution_environment_names,
                skip_credential_names=self.config.export.skip_credential_names,
            )

            transformer = create_transformer(
                resource_type=resource_type,
                dry_run=self.config.dry_run,
                state=self.state,  # Pass state for dependency validation
            )

            importer = create_importer(
                resource_type=resource_type,
                client=self.target_client,
                state=self.state,
                performance_config=self.config.performance,
                resource_mappings=self.config.resource_mappings,
                skip_execution_environment_names=self.config.export.skip_execution_environment_names,
                skip_credential_names=self.config.export.skip_credential_names,
            )

            # Special handling for hosts (bulk operations)
            if resource_type == "hosts" and phase_config.get("use_bulk"):
                return await self._execute_bulk_host_migration(exporter, transformer, importer)

            # Standard ETL pipeline
            resources_to_import = []

            # Export phase
            async for resource in exporter.export():
                stats["exported"] += 1

                # Update progress
                if self.progress_tracker:
                    self.progress_tracker.update_resource(exported=1)

                # Store source ID before transformation
                source_id = resource["id"]
                resource["_source_id"] = source_id

                # Transform phase
                try:
                    transformed = transformer.transform_resource(
                        resource_type=resource_type,
                        data=resource,
                        validate=True,
                    )
                    stats["transformed"] += 1
                    resources_to_import.append(transformed)

                    # Update progress
                    if self.progress_tracker:
                        self.progress_tracker.update_resource(transformed=1)

                except SkipResourceError as e:
                    # Resource skipped due to missing required dependency
                    logger.warning(
                        "resource_skipped_missing_dependency",
                        resource_type=resource_type,
                        source_id=e.source_id,
                        source_name=resource.get("name", "unknown"),
                        missing_dependency=e.missing_dependency,
                        reason=str(e),
                    )
                    stats["skipped"] += 1

                    # Track skip for reporting
                    self.metrics["skipped_items"].append(
                        {
                            "phase": phase_config["name"],
                            "resource_type": resource_type,
                            "source_id": e.source_id,
                            "name": resource.get("name", "unknown"),
                            "reason": str(e),
                            "missing_dependency": e.missing_dependency,
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )

                    # Update progress
                    if self.progress_tracker:
                        self.progress_tracker.update_resource(skipped=1)

                except Exception as e:
                    logger.error(
                        "transformation_failed",
                        resource_type=resource_type,
                        source_id=source_id,
                        error=str(e),
                    )
                    stats["failed"] += 1

                    # Update progress
                    if self.progress_tracker:
                        self.progress_tracker.update_resource(failed=1)

            # Update Rich progress display live during transform
            # completed = transformed + failed (NOT skipped - it's passed separately)
            # Progress bar calculates: completed + skipped = total processed
            if self.progress_display and self._current_phase_id:
                self.progress_display.update_phase(
                    self._current_phase_id,
                    completed=stats["transformed"] + stats["failed"],
                    failed=stats["failed"],
                    skipped=stats["skipped"],
                )

            # Update Rich progress display with actual total after export/transform
            if self.progress_display and self._current_phase_id and stats["exported"] > 0:
                # Set actual total items based on what was exported
                if self._current_phase_id in self.progress_display.phase_states:
                    self.progress_display.phase_states[self._current_phase_id].total_items = stats[
                        "exported"
                    ]
                # Also update the Rich Progress task's total
                if self._current_phase_id in self.progress_display.phase_tasks:
                    task_id = self.progress_display.phase_tasks[self._current_phase_id]
                    self.progress_display.phase_progress.update(task_id, total=stats["exported"])

            # Import phase
            if not self.config.dry_run:
                # Track import-phase progress separately for Rich display
                # completed = successful imports (not failures)
                # failed = import failures only
                # skipped = transform skips + import skips (already migrated)
                import_succeeded = 0  # Successful imports
                import_failed = 0  # Failed imports
                import_skipped = 0  # Already migrated (import-time skips)
                inventory_source_ids_for_sync: list[int] = []

                for resource in resources_to_import:
                    source_id = resource.pop("_source_id", None)
                    if not source_id:
                        continue

                    result = await importer.import_resource(
                        resource_type=resource_type,
                        source_id=source_id,
                        data=resource,
                    )

                    if result:
                        policy_skip = (
                            isinstance(result, dict)
                            and result.get("_skipped")
                            and result.get("policy_skip")
                        )
                        if policy_skip:
                            stats["skipped"] += 1
                            import_skipped += 1
                            if self.progress_tracker:
                                self.progress_tracker.update_resource(skipped=1)
                        else:
                            stats["imported"] += 1
                            import_succeeded += 1
                            if (
                                resource_type == "inventory_sources"
                                and isinstance(result, dict)
                                and result.get("id") is not None
                            ):
                                inventory_source_ids_for_sync.append(int(result["id"]))
                            if self.progress_tracker:
                                self.progress_tracker.update_resource(imported=1)
                    else:
                        # Check if it was a failure or just skipped (already imported)
                        if self.state.is_migrated(resource_type, source_id):
                            stats["skipped"] += 1
                            import_skipped += 1
                            if self.progress_tracker:
                                self.progress_tracker.update_resource(skipped=1)
                        else:
                            stats["failed"] += 1
                            import_failed += 1
                            if self.progress_tracker:
                                self.progress_tracker.update_resource(failed=1)

                    # Update Rich progress display with current import progress
                    # completed = imported + failed (NOT skipped - it's passed separately)
                    # Progress bar calculates: completed + skipped = total processed
                    if self.progress_display and self._current_phase_id:
                        self.progress_display.update_phase(
                            self._current_phase_id,
                            completed=stats["imported"] + stats["failed"],
                            failed=stats["failed"],
                            skipped=stats["skipped"],
                        )

                if resource_type == "inventory_sources" and inventory_source_ids_for_sync:
                    logger.info(
                        "inventory_sources_post_import_sync",
                        count=len(inventory_source_ids_for_sync),
                        message="Triggering inventory updates before later resource types",
                    )
                    await sync_inventory_sources_after_import(
                        self.target_client,
                        inventory_source_ids_for_sync,
                        self.config.performance,
                    )

                # Report any import errors
                if importer.import_errors:
                    logger.warning(
                        "import_errors_summary",
                        resource_type=resource_type,
                        error_count=len(importer.import_errors),
                        errors=importer.import_errors[:10],  # First 10 for log
                        message="See full error list in migration report",
                    )
                    # Add errors to global metrics for reporting
                    self.metrics["errors"].extend(
                        [
                            {"phase": phase_config["name"], "resource_type": resource_type, **error}
                            for error in importer.import_errors
                        ]
                    )

            else:
                # Dry run - just count what would be imported
                stats["imported"] = len(resources_to_import)

            # Report skipped resources summary
            if stats["skipped"] > 0:
                logger.warning(
                    "resources_skipped_summary",
                    resource_type=resource_type,
                    skipped_count=stats["skipped"],
                    message=f"{stats['skipped']} resources were skipped due to missing dependencies",
                )

            logger.info(
                "etl_pipeline_completed",
                resource_type=resource_type,
                stats=stats,
            )

        except Exception as e:
            logger.error(
                "etl_pipeline_failed",
                resource_type=resource_type,
                error=str(e),
            )
            raise

        return stats

    async def _execute_bulk_host_migration(self, exporter, transformer, importer) -> dict[str, int]:
        """Execute bulk host migration using AAP 2.6 bulk operations.

        Args:
            exporter: Host exporter instance
            transformer: Data transformer instance
            importer: Host importer instance (with bulk operations)

        Returns:
            Migration statistics
        """
        stats = {
            "exported": 0,
            "transformed": 0,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
        }

        # Group hosts by inventory for bulk import
        hosts_by_inventory = {}

        async for host in exporter.export():
            stats["exported"] += 1

            # Update progress for export
            if self.progress_tracker:
                self.progress_tracker.update_resource(exported=1)

            inventory_id = host.get("inventory")
            if not inventory_id:
                logger.warning("host_missing_inventory", host_id=host.get("id"))
                stats["failed"] += 1
                if self.progress_tracker:
                    self.progress_tracker.update_resource(failed=1)
                continue

            # Store source ID
            source_id = host["id"]
            host["_source_id"] = source_id

            # Transform (handles dependency validation for inventory)
            try:
                transformed = transformer.transform_resource(
                    resource_type="hosts",
                    data=host,
                    validate=False,  # Bulk API has different requirements
                )
                stats["transformed"] += 1

                # Update progress for transform
                if self.progress_tracker:
                    self.progress_tracker.update_resource(transformed=1)

                # Get mapped inventory ID (after successful transformation)
                target_inventory_id = self.state.get_mapped_id("inventory", inventory_id)
                if not target_inventory_id:
                    # This shouldn't happen if HostTransformer validated correctly,
                    # but handle gracefully
                    logger.warning(
                        "host_inventory_not_imported",
                        host_id=source_id,
                        inventory_id=inventory_id,
                        message="Inventory transformed but not yet imported",
                    )
                    stats["failed"] += 1
                    if self.progress_tracker:
                        self.progress_tracker.update_resource(failed=1)
                    continue

                # Group by target inventory
                if target_inventory_id not in hosts_by_inventory:
                    hosts_by_inventory[target_inventory_id] = []

                hosts_by_inventory[target_inventory_id].append(transformed)

            except SkipResourceError as e:
                # Host skipped because its inventory was not exported
                logger.info(
                    "host_skipped_missing_inventory",
                    host_id=e.source_id,
                    missing_dependency=e.missing_dependency,
                    reason=str(e),
                )
                stats["skipped"] += 1

                # Track skip for reporting
                self.metrics["skipped_items"].append(
                    {
                        "phase": "hosts",
                        "resource_type": "hosts",
                        "source_id": e.source_id,
                        "name": host.get("name", "unknown"),
                        "reason": str(e),
                        "missing_dependency": e.missing_dependency,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )

                if self.progress_tracker:
                    self.progress_tracker.update_resource(skipped=1)

            except Exception as e:
                logger.error(
                    "host_transformation_failed",
                    resource_type="hosts",
                    source_id=source_id,
                    source_name=host.get("name"),
                    error=str(e),
                )
                stats["failed"] += 1
                if self.progress_tracker:
                    self.progress_tracker.update_resource(failed=1)

        # Update Rich progress display with actual total after export/transform
        if self.progress_display and self._current_phase_id and stats["exported"] > 0:
            # Set actual total items based on what was exported
            if self._current_phase_id in self.progress_display.phase_states:
                self.progress_display.phase_states[self._current_phase_id].total_items = stats[
                    "exported"
                ]
            # Also update the Rich Progress task's total
            if self._current_phase_id in self.progress_display.phase_tasks:
                task_id = self.progress_display.phase_tasks[self._current_phase_id]
                self.progress_display.phase_progress.update(task_id, total=stats["exported"])

        # Bulk import hosts by inventory
        if not self.config.dry_run:
            for target_inventory_id, hosts in hosts_by_inventory.items():
                try:
                    result = await importer.import_hosts_bulk(
                        inventory_id=target_inventory_id,
                        hosts=hosts,
                    )
                    created = result.get("total_created", 0)
                    failed = result.get("total_failed", 0)
                    skipped = result.get("total_skipped", 0)

                    stats["imported"] += created
                    stats["failed"] += failed
                    stats["skipped"] += skipped

                    # Update progress for imported hosts (legacy tracker)
                    if self.progress_tracker:
                        for _ in range(created):
                            self.progress_tracker.update_resource(imported=1)
                        for _ in range(failed):
                            self.progress_tracker.update_resource(failed=1)
                        for _ in range(skipped):
                            self.progress_tracker.update_resource(skipped=1)

                    # Update Rich progress display after each inventory
                    # completed = imported + failed (NOT skipped - it's passed separately)
                    # Progress bar calculates: completed + skipped = total processed
                    if self.progress_display and self._current_phase_id:
                        self.progress_display.update_phase(
                            self._current_phase_id,
                            completed=stats["imported"] + stats["failed"],
                            failed=stats["failed"],
                            skipped=stats["skipped"],
                        )

                except Exception as e:
                    # Extract sample source_ids for troubleshooting
                    sample_source_ids = [h.get("_source_id") or h.get("id") for h in hosts[:5]]
                    logger.error(
                        "bulk_host_import_failed",
                        resource_type="hosts",
                        inventory_id=target_inventory_id,
                        host_count=len(hosts),
                        sample_source_ids=sample_source_ids,
                        error=str(e),
                    )
                    stats["failed"] += len(hosts)

                    # Update progress for failed hosts
                    if self.progress_tracker:
                        for _ in range(len(hosts)):
                            self.progress_tracker.update_resource(failed=1)
        else:
            # Dry run
            stats["imported"] = sum(len(hosts) for hosts in hosts_by_inventory.values())
            # Update progress for dry run
            if self.progress_tracker:
                for _ in range(stats["imported"]):
                    self.progress_tracker.update_resource(imported=1)

        return stats

    async def compare_schemas_before_migration(
        self, resource_types: list[str] | None = None
    ) -> dict[str, ComparisonResult]:
        """Compare AAP 2.3 and AAP 2.6 schemas before migration.

        This method fetches schemas from both source and target AAP instances
        using the OPTIONS HTTP method and compares them to identify migration
        requirements and potential issues.

        Args:
            resource_types: List of resource types to compare (default: all from migration phases)

        Returns:
            Dict of {resource_type: ComparisonResult}
        """
        if resource_types is None:
            # Get all resource types from migration phases
            resource_types = []
            for phase in self.MIGRATION_PHASES:
                resource_types.extend(phase["resource_types"])

        logger.info(
            "schema_comparison_started",
            resource_types=resource_types,
            count=len(resource_types),
        )

        comparisons = {}

        for resource_type in resource_types:
            try:
                logger.debug("fetching_schemas", resource_type=resource_type)

                # Fetch schemas from both instances
                source_schema = await self.schema_comparator.fetch_schema(
                    self.source_client, resource_type
                )
                target_schema = await self.schema_comparator.fetch_schema(
                    self.target_client, resource_type
                )

                # Compare schemas
                comparison = self.schema_comparator.compare_schemas(
                    resource_type, source_schema, target_schema
                )

                comparisons[resource_type] = comparison

                if comparison.has_breaking_changes:
                    logger.warning(
                        "schema_breaking_changes_detected",
                        resource_type=resource_type,
                        breaking_changes_count=sum(
                            1 for diff in comparison.field_diffs if diff.is_breaking
                        ),
                    )

            except Exception as e:
                logger.error(
                    "schema_comparison_failed",
                    resource_type=resource_type,
                    error=str(e),
                )
                # Continue with other resource types
                continue

        # Store comparisons for use by transformers
        self.schema_comparisons = comparisons

        logger.info(
            "schema_comparison_completed",
            total_resource_types=len(resource_types),
            comparisons_count=len(comparisons),
            breaking_changes_count=sum(1 for c in comparisons.values() if c.has_breaking_changes),
        )

        return comparisons

    def has_critical_schema_issues(self) -> bool:
        """Check if there are critical schema issues that might block migration.

        Returns:
            True if critical issues detected
        """
        from aap_migration.schema.models import Severity

        for comparison in self.schema_comparisons.values():
            for diff in comparison.field_diffs:
                if diff.severity == Severity.CRITICAL:
                    return True
            for change in comparison.schema_changes:
                if change.severity == Severity.CRITICAL:
                    return True
        return False

    def _determine_phases(
        self,
        skip_phases: list[str] | None,
        only_phases: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Determine which phases to execute.

        Args:
            skip_phases: Phases to skip
            only_phases: Only execute these phases

        Returns:
            List of phase configurations to execute
        """
        if skip_phases and only_phases:
            raise ValueError("Cannot specify both skip_phases and only_phases")

        phases = self.MIGRATION_PHASES

        if only_phases:
            phases = [p for p in phases if p["name"] in only_phases]
        elif skip_phases:
            phases = [p for p in phases if p["name"] not in skip_phases]

        return phases

    def _generate_summary(self) -> dict[str, Any]:
        """Generate migration summary.

        Returns:
            Migration summary dictionary
        """
        duration = None
        if self.metrics["start_time"] and self.metrics["end_time"]:
            duration = (self.metrics["end_time"] - self.metrics["start_time"]).total_seconds()

        summary = {
            "migration_id": self.state.migration_id,
            "status": "completed"
            if self.metrics["phases_failed"] == 0
            else "completed_with_errors",
            "start_time": self.metrics["start_time"].isoformat()
            if self.metrics["start_time"]
            else None,
            "end_time": self.metrics["end_time"].isoformat() if self.metrics["end_time"] else None,
            "duration_seconds": duration,
            "phases_completed": self.metrics["phases_completed"],
            "phases_failed": self.metrics["phases_failed"],
            "total_resources_exported": self.metrics["total_resources_exported"],
            "total_resources_imported": self.metrics["total_resources_imported"],
            "total_resources_failed": self.metrics["total_resources_failed"],
            "total_resources_skipped": self.metrics["total_resources_skipped"],
            "errors": self.metrics["errors"],
            "skipped_items": self.metrics["skipped_items"],
            "dry_run": self.config.dry_run,
        }

        logger.info("migration_completed", summary=summary)

        return summary

    async def resume_from_checkpoint(self, checkpoint_id: int) -> dict[str, Any]:
        """Resume migration from a checkpoint.

        Args:
            checkpoint_id: Checkpoint ID to resume from

        Returns:
            Migration summary
        """
        logger.info("resuming_from_checkpoint", checkpoint_id=checkpoint_id)

        # Restore checkpoint
        checkpoint = self.checkpoint_manager.restore_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint not found: {checkpoint_id}")

        # Determine which phase to resume from
        last_completed_phase = checkpoint["phase"]

        # Find index of last completed phase
        phase_idx = -1
        for idx, phase in enumerate(self.MIGRATION_PHASES):
            if phase["name"] == last_completed_phase:
                phase_idx = idx
                break

        if phase_idx == -1:
            raise ValueError(f"Unknown phase in checkpoint: {last_completed_phase}")

        # Resume from next phase
        remaining_phases = self.MIGRATION_PHASES[phase_idx + 1 :]

        logger.info(
            "resuming_migration",
            checkpoint_phase=last_completed_phase,
            remaining_phases=[p["name"] for p in remaining_phases],
        )

        # Execute remaining phases
        only_phases = [p["name"] for p in remaining_phases]
        return await self.migrate_all(only_phases=only_phases)
