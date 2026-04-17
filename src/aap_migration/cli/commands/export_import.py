"""
Export and import commands.

This module provides commands for exporting resources from source AAP
and importing them to target AAP independently.
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import click

from aap_migration.cli.commands.migrate import PHASE1_RESOURCE_TYPES, PHASE2_RESOURCE_TYPES
from aap_migration.cli.commands.patch_projects import patch_project_scm_details
from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import handle_errors, pass_context, requires_config
from aap_migration.cli.utils import (
    echo_error,
    echo_info,
    echo_success,
    echo_warning,
    format_count,
    step_progress,
)
from aap_migration.migration.exporter import create_exporter
from aap_migration.migration.importer import create_importer
from aap_migration.migration.parallel_exporter import ParallelExportCoordinator
from aap_migration.migration.state import ExportRunContext, MigrationState
from aap_migration.reporting.live_progress import MigrationProgressDisplay
from aap_migration.resources import (
    ORGANIZATION_SCOPED_RESOURCES,
    RESOURCE_REGISTRY,
    ResourceCategory,
    get_endpoint,
    get_exportable_types,
    get_resource_category,
    normalize_resource_type,
)
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================
# Auto-Dependency Resolution Helper Functions
# ============================================


def get_importer_dependencies(resource_type: str) -> dict[str, str]:
    """Get the DEPENDENCIES dictionary from an importer class.

    Args:
        resource_type: Type of resource (e.g., 'inventory_sources')

    Returns:
        Dictionary mapping field names to resource types
        (e.g., {"organization": "organizations", "credential": "credentials"})
        Returns empty dict if importer has no dependencies or doesn't exist.

    Example:
        >>> get_importer_dependencies('inventory_sources')
        {'inventory': 'inventory', 'source_project': 'projects', 'credential': 'credentials'}
    """
    try:
        # Create a dummy importer instance to access class-level DEPENDENCIES
        # We don't need a real client/state here, just the class metadata
        # But create_importer requires them, so we'll import the class directly
        from aap_migration.migration.importer import (
            CredentialImporter,
            CredentialTypeImporter,
            ExecutionEnvironmentImporter,
            HostImporter,
            InventoryGroupImporter,
            InventoryImporter,
            InventorySourceImporter,
            JobTemplateImporter,
            LabelImporter,
            NotificationTemplateImporter,
            OrganizationImporter,
            ProjectImporter,
            RBACImporter,
            ScheduleImporter,
            TeamImporter,
            UserImporter,
            WorkflowImporter,
        )

        # Map resource types to importer classes (canonical + legacy aliases)
        importer_classes = {
            "organizations": OrganizationImporter,
            "labels": LabelImporter,
            "users": UserImporter,
            "teams": TeamImporter,
            "credential_types": CredentialTypeImporter,
            "credentials": CredentialImporter,
            "projects": ProjectImporter,
            "execution_environments": ExecutionEnvironmentImporter,
            "inventory": InventoryImporter,
            "inventories": InventoryImporter,
            "inventory_sources": InventorySourceImporter,
            "groups": InventoryGroupImporter,
            "inventory_groups": InventoryGroupImporter,
            "hosts": HostImporter,
            "job_templates": JobTemplateImporter,
            "workflow_job_templates": WorkflowImporter,
            "schedules": ScheduleImporter,
            "notification_templates": NotificationTemplateImporter,
            "rbac": RBACImporter,
        }

        importer_class = importer_classes.get(resource_type)
        if importer_class:
            return importer_class.DEPENDENCIES.copy()
        else:
            logger.warning(f"Unknown resource type '{resource_type}', no dependencies found")
            return {}
    except Exception as e:
        logger.warning(f"Failed to get dependencies for {resource_type}: {e}")
        return {}


def build_dependency_closure(
    requested_types: list[str], all_available_types: list[str]
) -> list[str]:
    """Build complete ordered list of resource types including all dependencies.

    Uses transitive closure to find all nested dependencies. Results are
    sorted by migration_order to ensure dependencies are imported first.

    Args:
        requested_types: Resource types user wants to import
        all_available_types: All resource types available in export directory

    Returns:
        Ordered list of resource types (dependencies first, then requested types)

    Example:
        >>> build_dependency_closure(['inventory_sources'], ['organizations', ...])
        ['organizations', 'credential_types', 'credentials', 'projects', 'inventories', 'inventory_sources']
    """
    # Track all types we need to import (set for deduplication)
    needed_types = set()

    # Queue for BFS traversal
    queue = list(requested_types)
    visited = set()

    while queue:
        current_type = queue.pop(0)

        if current_type in visited:
            continue
        visited.add(current_type)

        # Add this type to needed set (if it's available)
        if current_type in all_available_types:
            needed_types.add(current_type)

        # Get dependencies for this type
        deps = get_importer_dependencies(current_type)

        # Add dependency resource types to queue
        for dep_resource_type in deps.values():
            if dep_resource_type not in visited:
                queue.append(dep_resource_type)

    # Sort by migration_order to ensure dependencies come first
    sorted_types = sorted(
        needed_types,
        key=lambda t: RESOURCE_REGISTRY.get(t).migration_order if t in RESOURCE_REGISTRY else 999,
    )

    return sorted_types


def get_missing_dependencies(
    types_to_check: list[str], migration_state: MigrationState
) -> list[str]:
    """Check which resource types haven't been imported yet.

    Args:
        types_to_check: Resource types to check import status for
        migration_state: Migration state manager

    Returns:
        List of resource types that haven't been imported (total_imported == 0)

    Example:
        >>> get_missing_dependencies(['organizations', 'inventories'], state)
        ['inventories']  # organizations already imported
    """
    missing = []

    for resource_type in types_to_check:
        try:
            stats = migration_state.get_import_stats(resource_type)
            # Consider it "missing" if:
            # 1. Nothing imported yet (total_imported == 0), OR
            # 2. Some resources still pending (partial import failure)
            # This ensures dependencies with failed imports are re-attempted
            if stats["total_imported"] == 0 or stats["pending"] > 0:
                missing.append(resource_type)
        except Exception as e:
            logger.warning(f"Failed to get import stats for {resource_type}: {e}")
            # If we can't check, assume it's missing (safer to re-import)
            missing.append(resource_type)

    return missing


@click.command(name="export")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory path for exported files (default: exports/)",
)
@click.option(
    "--resource-type",
    "-r",
    multiple=True,
    type=str,
    help="Resource types to export (default: all discovered or exportable)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite output directory if it exists",
)
@click.option(
    "--records-per-file",
    type=int,
    default=None,
    help="Maximum records per file (default: 1000)",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from last checkpoint (skips already-exported resources via API filtering)",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Automatically confirm prompts (skip confirmation)",
)
@pass_context
@requires_config
@handle_errors
def export(
    ctx: MigrationContext,
    output: Path | None,
    resource_type: tuple,
    force: bool,
    records_per_file: int | None,
    resume: bool,
    yes: bool,
) -> None:
    """Export RAW resources from source AAP 2.3 to directory structure.

    Exports RAW resources from the source AAP instance to a directory with separate
    files for each resource type. Data is saved without transformation to preserve
    all original fields. Large resource types are automatically split into multiple
    files to keep file sizes manageable.

    NOTE: This command saves RAW data. Use 'transform' command to prepare data for import.

    Three-phase workflow:
        1. aap-bridge export (RAW data → exports/)
        2. aap-bridge transform (exports/ → xformed/)
        3. aap-bridge import (xformed/ → AAP 2.6)

    Examples:

        \b
        # Export all resources (uses default: exports/)
        aap-bridge export

        \b
        # Export specific resources
        aap-bridge export --resource-type organizations --resource-type inventories

        \b
        # Custom output directory
        aap-bridge export --output /custom/path/exports/

        \b
        # Custom records per file (default: 1000)
        aap-bridge export --records-per-file 500

        \b
        # Force overwrite
        aap-bridge export --force

        \b
        # Resume from checkpoint (skips API calls for already-exported resources)
        aap-bridge export --resume
    """
    # Use defaults from config if not provided
    if output is None:
        output = Path(ctx.config.paths.export_dir)
    else:
        output = Path(output)

    if records_per_file is None:
        records_per_file = ctx.config.export.records_per_file

    # Check if directory exists
    if output.exists() and not force:
        if not yes and not click.confirm(f"Directory {output} exists. Overwrite?"):
            raise click.exceptions.Exit(0)

    # Create directory structure
    output.mkdir(parents=True, exist_ok=True)

    # Determine resource types to export
    # Use discovered endpoints if available, otherwise fall back to hardcoded list
    if resource_type:
        # User specified types - normalize them
        types_to_export = [normalize_resource_type(rt) for rt in resource_type]
    else:
        # No types specified - use discovered or hardcoded, then normalize
        discovered_types = get_exportable_types(use_discovered=True)
        types_to_export = [normalize_resource_type(rt) for rt in discovered_types]

    # Check if parallel resource type export is enabled
    parallel_types_enabled = ctx.config.performance.parallel_resource_types
    if not resume:
        for rtype in types_to_export:
            cleared = ctx.migration_state.clear_mappings(rtype, phase="export")
            if cleared > 0:
                logger.info("cleared_stale_export_mappings", resource_type=rtype, count=cleared)

    async def run_export():
        import logging
        from datetime import datetime

        # Discover and validate versions (REQ-001, REQ-002)
        # Use config override if available, else auto-detect from API
        source_version = ctx.config.source.version or await ctx.source_client.get_version()
        target_version = ctx.config.target.version or await ctx.target_client.get_version()

        # Store on context for downstream use
        ctx.source_version = source_version
        ctx.target_version = target_version

        from aap_migration.resources import get_version_path

        version_path = get_version_path(source_version, target_version)
        if version_path is None:
            if not force:
                echo_error(f"Unsupported migration path: {source_version} → {target_version}")
                raise click.ClickException("Unsupported version path")
            else:
                echo_warning(f"Unknown migration path: {source_version} → {target_version}")
        else:
            logger.info(
                "export_version_path_validated",
                source=source_version,
                target=target_version,
                status=version_path.status,
            )

        # Create run context for identity validation (REQ-001)
        current_run = ExportRunContext(
            source_url=ctx.config.source.url,
            source_version=source_version,
            output_dir=str(output.absolute()),
            resource_types=tuple(sorted(types_to_export)),
            filters=tuple(sorted(ctx.config.export.filters.items())),
            state_dsn_fingerprint=ExportRunContext.hash_dsn(ctx.migration_state.database_url),
            timestamp=datetime.utcnow().isoformat(),
        )

        # Resume validation (REQ-003)
        metadata_file = output / "metadata.json"
        if resume and metadata_file.exists():
            try:
                with open(metadata_file) as f:
                    existing_metadata = json.load(f)
                stored_fingerprint = existing_metadata.get("run_context", {}).get("run_fingerprint")
                if stored_fingerprint and stored_fingerprint != current_run.run_fingerprint:
                    if not force:
                        echo_error(
                            f"Resume mismatch: stored run fingerprint {stored_fingerprint} "
                            f"does not match current {current_run.run_fingerprint}.\n"
                            "Source URL, resource types, or filters have changed since "
                            "the original export.\n"
                            "Use --force to override, or run without --resume for a fresh export."
                        )
                        raise click.ClickException("Resume context mismatch")
                    else:
                        echo_warning(
                            "Resume mismatch detected but --force is set. Proceeding with caution."
                        )
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("failed_to_load_existing_metadata", error=str(e))

        # Suppress console logging for cleaner output (Live progress display will handle it)
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        for handler in root_logger.handlers[:]:
            if hasattr(handler, "__class__") and "RichHandler" in handler.__class__.__name__:
                root_logger.removeHandler(handler)

        total_resources = 0
        export_stats = {}
        skipped_readonly = []
        skipped_runtime = []
        skipped_manual = []
        skipped_no_exporter = []
        exported_successfully = []

        try:
            # Step 1: Pre-fetch counts for all resource types (before progress display)
            # Silently fetch counts - will be shown in the Live progress display
            phases = []
            for rtype in types_to_export:
                category = get_resource_category(rtype)

                # Skip read-only/never migrate endpoints
                if category == ResourceCategory.NEVER_MIGRATE:
                    logger.debug(
                        "skipping_never_migrate_endpoint",
                        resource_type=rtype,
                        reason="Excluded from migration scope",
                    )
                    skipped_readonly.append(rtype)
                    continue

                try:
                    endpoint = get_endpoint(rtype)
                except KeyError:
                    logger.warning("unknown_resource_type", resource_type=rtype)
                    continue

                # Create exporter using factory
                try:
                    temp_exporter = create_exporter(
                        rtype,
                        ctx.source_client,
                        ctx.migration_state,
                        ctx.config.performance,
                    )
                except NotImplementedError as e:
                    # Exporter not implemented yet
                    logger.warning("exporter_not_implemented", resource_type=rtype, message=str(e))
                    skipped_no_exporter.append(rtype)
                    continue

                # Apply skip flags to temp exporter (before getting count)
                if rtype == "hosts" and ctx.config.export.skip_dynamic_hosts:
                    if hasattr(temp_exporter, "set_skip_dynamic_hosts"):
                        temp_exporter.set_skip_dynamic_hosts(True)

                if rtype == "inventories" and ctx.config.export.skip_smart_inventories:
                    if hasattr(temp_exporter, "set_skip_smart_inventories"):
                        temp_exporter.set_skip_smart_inventories(True)

                # Build filters dict for count query
                count_filters: dict[str, str] = {}
                if rtype == "hosts" and ctx.config.export.skip_dynamic_hosts:
                    count_filters["inventory_sources__isnull"] = "true"
                    logger.info(
                        "export_count_applying_dynamic_host_filter",
                        resource_type=rtype,
                        filter="inventory_sources__isnull=true (exclude dynamic hosts)",
                    )
                if rtype == "inventories":
                    count_filters["pending_deletion"] = "false"
                    logger.info(
                        "export_count_applying_inventory_filter",
                        resource_type=rtype,
                        filter="pending_deletion=false",
                    )

                # Get count from API WITH FILTERS
                count = await temp_exporter.get_count(
                    endpoint, filters=count_filters if count_filters else None
                )
                description = rtype.replace("_", " ").title()
                phases.append((rtype, description, count))
                logger.debug(f"Fetched count for {description}: {count} resources")

            # Filter out resources with 0 count - no value showing empty phases
            phases = [(rtype, desc, count) for rtype, desc, count in phases if count > 0]

            # Log export mode to file
            logger.info("export_mode", mode="RAW", transformation=False)

            # Step 3: Use the new Live progress display with all phases initialized upfront
            with MigrationProgressDisplay(
                title="🚀 AAP Export Progress (RAW Data)", enabled=True
            ) as progress:
                # Set total phases BEFORE initialize_phases to avoid jitter
                progress.set_total_phases(len(phases))
                # Initialize all phases upfront (guidellm pattern - like demo)
                progress.initialize_phases(phases)

                # Step 4: Export and transform each resource type
                # Check if parallel resource type export is enabled
                if parallel_types_enabled:
                    # Use parallel export coordinator for concurrent resource type export
                    coordinator = ParallelExportCoordinator(
                        source_client=ctx.source_client,
                        migration_state=ctx.migration_state,
                        performance_config=ctx.config.performance,
                        output_dir=output,
                        records_per_file=records_per_file,
                        export_config=ctx.config.export,
                    )

                    # Create progress callback to update display
                    def progress_callback(rtype: str, stats: dict):
                        phase_id = rtype  # We use resource_type as phase_id
                        progress.update_phase(
                            phase_id, stats.get("exported", 0), stats.get("failed", 0)
                        )

                    # Start all phases before parallel export begins
                    # This transitions tasks from "pending" to "running" status
                    for rtype, description, total_count in phases:
                        progress.start_phase(rtype, description, total_count)

                    # Get list of resource types to export
                    resource_types_list = [rtype for rtype, _, _ in phases]

                    # Export all resource types in parallel
                    parallel_results = await coordinator.export_all_parallel(
                        resource_types=resource_types_list,
                        resume=resume,
                        progress_callback=progress_callback,
                    )

                    # Aggregate results
                    for rtype, stats in parallel_results.items():
                        exported_count = stats.get("exported", 0)
                        total_resources += exported_count
                        export_stats[rtype] = {
                            "count": exported_count,
                            "files": stats.get("files_written", 0),
                            "skipped": stats.get("skipped", 0),
                            "failed": stats.get("failed", 0),
                        }
                        # Complete phase in progress display
                        progress.complete_phase(rtype)

                        # Track successful exports
                        if exported_count > 0:
                            exported_successfully.append(rtype)

                        # Track skipped types (no exporter)
                        if stats.get("skipped", 0) > 0 and "skip_reason" in stats:
                            skipped_no_exporter.append(rtype)

                else:
                    # Sequential export (original behavior)
                    for rtype, description, total_count in phases:
                        # Create directory for this resource type
                        resource_dir = output / rtype
                        resource_dir.mkdir(parents=True, exist_ok=True)

                        exporter = create_exporter(
                            rtype,
                            ctx.source_client,
                            ctx.migration_state,
                            ctx.config.performance,
                        )

                        # Apply skip_dynamic_hosts filter for hosts
                        if rtype == "hosts" and ctx.config.export.skip_dynamic_hosts:
                            if hasattr(exporter, "set_skip_dynamic_hosts"):
                                exporter.set_skip_dynamic_hosts(True)
                                logger.info(
                                    "filtering_hosts",
                                    message="Skipping hosts from dynamic inventory sources",
                                )

                        # Apply skip_smart_inventories filter for inventories
                        if rtype == "inventories" and ctx.config.export.skip_smart_inventories:
                            if hasattr(exporter, "set_skip_smart_inventories"):
                                exporter.set_skip_smart_inventories(True)
                                logger.info(
                                    "filtering_inventories",
                                    message="Skipping smart inventories (only exporting static inventories)",
                                )

                        # Set resume checkpoint if resume mode is enabled
                        if resume:
                            max_exported_id = ctx.migration_state.get_max_exported_id(rtype)
                            if max_exported_id is not None:
                                exporter.set_resume_checkpoint(max_exported_id)
                                logger.info(
                                    "resume_checkpoint_applied",
                                    resource_type=rtype,
                                    resume_from_id=max_exported_id,
                                )

                        # Export and transform resources with file splitting
                        resource_count = 0
                        failed_count = 0
                        file_count = 0
                        current_batch = []
                        pending_mappings = []  # Batch mappings for DB writes
                        mapping_batch_size = ctx.config.performance.mapping_batch_size

                        # Start phase (we already know the total count from pre-fetch)
                        phase_id = progress.start_phase(rtype, description, total_count)

                        # Get endpoint for this resource type
                        endpoint = get_endpoint(rtype)

                        # Use parallel page fetching for faster export
                        max_concurrent_pages = ctx.config.performance.max_concurrent_pages
                        page_size = ctx.config.performance.batch_sizes.get(rtype, 200)

                        async for resource in exporter.export_parallel(
                            resource_type=rtype,
                            endpoint=endpoint,
                            page_size=page_size,
                            max_concurrent_pages=max_concurrent_pages,
                        ):
                            try:
                                # Store ID mapping in database BEFORE transformation
                                source_id = resource.get("id")
                                source_name = resource.get("name", "")

                                # Queue mapping for batch insert (instead of individual write)
                                pending_mappings.append(
                                    {
                                        "resource_type": rtype,
                                        "source_id": source_id,
                                        "target_id": None,  # Will be set during import
                                        "source_name": source_name,
                                    }
                                )

                                # Batch commit mappings to reduce DB overhead
                                if len(pending_mappings) >= mapping_batch_size:
                                    ctx.migration_state.batch_create_mappings(
                                        pending_mappings, batch_size=mapping_batch_size
                                    )
                                    pending_mappings = []

                                # Save RAW resource data (NO transformation)
                                # Only add source ID for tracking
                                resource["_source_id"] = source_id
                                current_batch.append(resource)
                                resource_count += 1
                            except Exception as e:
                                logger.warning(
                                    "export_failed",
                                    resource_type=rtype,
                                    resource_id=resource.get("id"),
                                    error=str(e),
                                )
                                failed_count += 1
                                resource_count += 1

                            # Update progress (including failures)
                            progress.update_phase(phase_id, resource_count, failed_count)

                            # Write batch when it reaches the limit
                            if len(current_batch) >= records_per_file:
                                file_count += 1
                                file_path = resource_dir / f"{rtype}_{file_count:04d}.json"
                                with open(file_path, "w") as f:
                                    json.dump(current_batch, f, indent=2)

                                logger.debug(
                                    "export_file_written",
                                    resource_type=rtype,
                                    file_number=file_count,
                                    records=len(current_batch),
                                )

                                current_batch = []

                        # Commit remaining mappings
                        if pending_mappings:
                            ctx.migration_state.batch_create_mappings(
                                pending_mappings, batch_size=mapping_batch_size
                            )

                        # Write remaining batch
                        if current_batch:
                            file_count += 1
                            file_path = resource_dir / f"{rtype}_{file_count:04d}.json"
                            with open(file_path, "w") as f:
                                json.dump(current_batch, f, indent=2)

                        total_resources += resource_count
                        export_stats[rtype] = {
                            "count": resource_count,
                            "files": file_count,
                        }

                        logger.info(
                            "exported_resources",
                            resource_type=rtype,
                            count=resource_count,
                            files=file_count,
                        )

                        # Complete this phase
                        progress.complete_phase(phase_id)

                        # Track successful export
                        exported_successfully.append(rtype)

            # Write metadata file
            metadata = {
                "export_timestamp": datetime.utcnow().isoformat(),
                "source_url": ctx.config.source.url,
                "source_url_fingerprint": hashlib.sha256(
                    ctx.config.source.url.encode()
                ).hexdigest()[:16],
                "source_version": source_version,
                "target_version": target_version,
                "version_path_status": version_path.status if version_path else "unknown",
                "total_resources": total_resources,
                "total_skipped": sum(s.get("skipped", 0) for s in export_stats.values()),
                "records_per_file": records_per_file,
                "run_context": current_run.to_dict(),
                "resource_types": {
                    rtype: {
                        "count": stats["count"],
                        "files": stats["files"],
                        "skipped": parallel_results.get(rtype, {}).get("skipped", 0)
                        if parallel_types_enabled
                        else stats.get("skipped", 0),
                        "failed": parallel_results.get(rtype, {}).get("failed", 0)
                        if parallel_types_enabled
                        else stats.get("failed", 0),
                    }
                    for rtype, stats in export_stats.items()
                },
            }

            with open(output / "metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)

            # Log detailed export info to file
            logger.info(
                "export_completed",
                total_resources=total_resources,
                exported_types=exported_successfully,
                skipped_readonly=skipped_readonly,
                skipped_runtime=skipped_runtime,
                skipped_manual=skipped_manual,
                skipped_no_exporter=skipped_no_exporter,
            )

            # Show concise export summary
            click.echo()
            echo_info("Export Summary:")
            click.echo(f"  Resources exported: {format_count(total_resources)}")
            click.echo(f"  Resource types: {len(exported_successfully)}")
            click.echo(
                f"  Skipped (read-only/runtime): {len(skipped_readonly) + len(skipped_runtime)}"
            )
            if skipped_manual:
                click.echo(f"  Requires manual migration: {len(skipped_manual)}")
            if skipped_no_exporter:
                click.echo(f"  Missing exporter: {len(skipped_no_exporter)}")
                for rtype in skipped_no_exporter:
                    click.echo(f"    - {rtype}")

        except Exception as e:
            echo_error(f"Export failed: {e}")
            logger.error("export_failed", error=str(e), exc_info=True)
            raise click.ClickException(str(e)) from e
        finally:
            # Restore original logging handlers
            for handler in original_handlers:
                if handler not in root_logger.handlers:
                    root_logger.addHandler(handler)

    try:
        asyncio.run(run_export())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_export())


@click.command(name="import")
@click.option(
    "--input",
    "-i",
    "input_dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Input directory path containing transformed files (default: xformed/)",
)
@click.option(
    "--resource-type",
    "-r",
    multiple=True,
    type=str,
    help="Resource types to import (default: all discovered or importable)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation and proceed with import",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume import from checkpoint (skip already-imported resources)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Perform dry run without making changes",
)
@click.option(
    "--skip-dependencies",
    is_flag=True,
    help="Skip automatic dependency resolution (for testing/debugging only)",
)
@click.option(
    "--check-dependencies",
    is_flag=True,
    help="Show what would be imported (including dependencies) and exit",
)
@click.option(
    "--force-reimport",
    is_flag=True,
    help="Clear import progress for requested types (allows re-import after failures)",
)
@click.option(
    "--phase",
    type=click.Choice(["phase1", "phase2", "all"], case_sensitive=False),
    default="all",
    help=(
        "Import phase: phase1 (foundation through projects), "
        "phase2 (patch projects then inventory + automation), all (complete)"
    ),
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Automatically confirm prompts (skip confirmation)",
)
@pass_context
@requires_config
@handle_errors
def import_cmd(
    ctx: MigrationContext,
    input_dir: Path | None,
    resource_type: tuple,
    force: bool,
    resume: bool,
    dry_run: bool,
    skip_dependencies: bool,
    check_dependencies: bool,
    force_reimport: bool,
    phase: str,
    yes: bool,
) -> None:
    """Import TRANSFORMED resources to target AAP 2.6.

    Imports transformed resources from xformed/ directory to the target AAP
    instance. Data must be pre-transformed using the 'transform' command.
    Automatically handles multi-file resource types and resolves
    dependencies.

    NOTE: This command expects data from xformed/ directory (already transformed).
    Do NOT point it at exports/ (raw data). Use the transform command first.

    Three-phase workflow:
        1. aap-bridge export (RAW data → exports/)
        2. aap-bridge transform (exports/ → xformed/)
        3. aap-bridge import (xformed/ → AAP 2.6)

    Dependencies are automatically resolved and imported. For example,
    importing inventory_sources will automatically import organizations,
    credential_types, credentials, projects, and inventories first.

    Examples:

        \b
        # Import all resources (uses default: xformed/)
        aap-bridge import

        \b
        # Import specific resources (dependencies auto-imported)
        aap-bridge import --resource-type inventory_sources

        \b
        # Check what would be imported (including dependencies)
        aap-bridge import --resource-type inventory_sources --check-dependencies

        \b
        # Custom input directory
        aap-bridge import --input /custom/xformed/

        \b
        # Skip dependency resolution (for testing - will likely fail)
        aap-bridge import --resource-type inventory_sources --skip-dependencies

        \b
        # Resume interrupted import (skip already-imported)
        aap-bridge import --resume

        \b
        # Force import without confirmation
        aap-bridge import --force

        \b
        # Dry run
        aap-bridge import --dry-run

        \b
        # Two-phase import workflow:
        # Phase 1: Import foundation through projects
        aap-bridge import --phase phase1

        \b
        # Phase 2: Patch projects, then import inventory + automation
        aap-bridge import --phase phase2
    """
    import logging

    # Use defaults from config if not provided
    if input_dir is None:
        input_dir = Path(ctx.config.paths.transform_dir)
    else:
        input_dir = Path(input_dir)

    # Suppress console logging for cleaner output (Live progress display will handle it)
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    for handler in root_logger.handlers[:]:
        if hasattr(handler, "__class__") and "RichHandler" in handler.__class__.__name__:
            root_logger.removeHandler(handler)

    # Load metadata with inline progress (:: → ✓)
    metadata_file = input_dir / "metadata.json"
    if not metadata_file.exists():
        echo_error(f"Metadata file not found: {metadata_file}")
        raise click.ClickException("Invalid export directory - metadata.json missing")

    try:
        with step_progress("Loading transformed files"):
            with open(metadata_file) as f:
                metadata = json.load(f)
    except click.ClickException:
        raise
    except Exception as e:
        echo_error(f"Failed to load metadata: {e}")
        raise click.ClickException(str(e)) from e

    # Validate that data is transformed (from xformed/ not exports/)
    if "transform_timestamp" not in metadata:
        echo_error("❌ Input directory contains RAW export data, not transformed data")
        echo_info("")
        echo_info("This directory appears to contain RAW exports from AAP 2.3.")
        echo_info("Import requires transformed data. Please run:")
        echo_info("")
        echo_info(f"  aap-bridge transform --input {input_dir} --output xformed/")
        echo_info("  aap-bridge import --input xformed/")
        echo_info("")
        raise click.ClickException("Import requires transformed data from xformed/ directory")

    # Handle Phase 2 (patch projects, then inventory + automation)
    if phase == "phase2":
        echo_info(
            "Phase 2: Patching Projects + Importing Inventory & Automation (templates, schedules, …)"
        )

    # Determine resource types to import
    available_types = list(metadata.get("resource_types", {}).keys())
    requested_types = list(resource_type) if resource_type else available_types

    # Check for missing prerequisite types (REQ-006)
    from aap_migration.migration.transformer import DEPENDENCY_MAP

    missing_prerequisites: list[str] = []
    for rtype in requested_types:
        deps = DEPENDENCY_MAP.get(rtype, [])
        for dep_type in deps:
            dep_key = normalize_resource_type(dep_type)
            # Check transformed metadata for dependency status (keys use canonical names)
            dep_meta = metadata.get("resource_types", {}).get(dep_key, {})
            # Either it wasn't in the metadata, or it had 0 transformed resources
            if not dep_meta or dep_meta.get("transformed_count", 0) == 0:
                # Only warn if it's not already in id_mappings
                if not ctx.migration_state.get_all_mappings(dep_key):
                    missing_prerequisites.append(
                        f"{rtype} requires {dep_key} (0 transformed resources available)"
                    )

    if missing_prerequisites:
        echo_warning("Pipeline continuity issues detected:")
        for msg in missing_prerequisites:
            click.echo(f"  ⚠ {msg}")
        echo_warning(
            "Import of dependent resources may fail. "
            "Consider transforming parent resources if this is unexpected."
        )

    # Dependency resolution (always enabled unless --skip-dependencies or importing all)
    if check_dependencies:
        # Just show what would be imported and exit
        types_with_deps = build_dependency_closure(requested_types, available_types)
        missing_deps = get_missing_dependencies(types_with_deps, ctx.migration_state)

        click.echo()
        echo_info("Dependency Check:")
        click.echo(f"  Requested types: {', '.join(requested_types)}")
        click.echo(f"  Full dependency closure: {', '.join(types_with_deps)}")

        if missing_deps:
            echo_warning(f"  Missing (need to import): {', '.join(missing_deps)}")
            click.echo()
            echo_info(
                "To import with dependencies, run:\n"
                f"  aap-bridge import --input {input_dir} "
                f"--resource-type {' --resource-type '.join(requested_types)}"
            )
        else:
            echo_success("  All dependencies already imported!")

        raise click.exceptions.Exit(0)

    elif not skip_dependencies and requested_types != available_types:
        # Auto-dependency resolution (enabled by default)
        # Build dependency closure (includes dependencies + requested types)
        types_with_deps = build_dependency_closure(requested_types, available_types)

        # Check which ones are missing (not yet imported)
        missing_deps = get_missing_dependencies(types_with_deps, ctx.migration_state)

        # Show what will be imported
        click.echo()
        echo_info("Automatic Dependency Resolution:")
        click.echo(f"  Requested types: {', '.join(requested_types)}")
        click.echo(f"  With dependencies: {', '.join(types_with_deps)}")

        if missing_deps:
            echo_warning(f"  Missing (will import): {', '.join(missing_deps)}")
            types_to_import = missing_deps
        else:
            echo_success("  All dependencies already imported!")
            types_to_import = requested_types
        click.echo()

    else:
        # Skip dependency resolution (--skip-dependencies flag or importing all types)
        if skip_dependencies and requested_types != available_types:
            echo_warning(
                "Dependency resolution skipped (--skip-dependencies). "
                "Import may fail if dependencies are missing."
            )
        # Always sort types_to_import by migration_order to ensure dependencies come first
        # This is critical for credential_types to be imported before credentials, etc.
        types_to_import = sorted(
            requested_types,
            key=lambda t: RESOURCE_REGISTRY.get(t).migration_order
            if t in RESOURCE_REGISTRY
            else 999,
        )

    # Filter by phase if specified
    if phase == "phase1":
        types_to_import = [t for t in types_to_import if t in PHASE1_RESOURCE_TYPES]
        logger.info("Phase 1 import: credential_types/credentials will be PATCHed (pre-created)")
    elif phase == "phase2":
        types_to_import = [t for t in types_to_import if t in PHASE2_RESOURCE_TYPES]

    if phase in ("phase1", "phase2"):
        types_to_import = sorted(
            types_to_import,
            key=lambda t: RESOURCE_REGISTRY[t].migration_order
            if t in RESOURCE_REGISTRY
            else 999,
        )

    # Force re-import: Clear import progress and reset target_ids
    if force_reimport:
        click.echo()
        echo_warning("Force re-import enabled - clearing import progress...")

        for rtype in types_to_import:
            # Clear migration_progress records (removes import status tracking)
            cleared_count = ctx.migration_state.clear_progress(rtype)

            # Reset target_id to NULL in id_mappings (preserves source_id from export)
            reset_count = ctx.migration_state.reset_target_ids(rtype)

            echo_info(
                f"  {rtype}: Cleared {cleared_count} progress records, reset {reset_count} mappings"
            )

        click.echo()

    if dry_run:
        echo_warning("DRY RUN MODE - No changes will be made")

    # Show import progress statistics if resume mode
    if resume:
        echo_info("Resume mode enabled - checking import progress...")
        has_pending = False
        for rtype in types_to_import:
            stats = ctx.migration_state.get_import_stats(rtype)
            if stats["total_exported"] > 0:
                has_pending = stats["pending"] > 0 or has_pending
                click.echo(
                    f"  {rtype}: {format_count(stats['total_imported'])}\
/{format_count(stats['total_exported'])} "
                    f"({stats['percent_complete']:.1f}% complete, "
                    f"{format_count(stats['pending'])} pending)"
                )
        if not has_pending:
            echo_warning("No pending imports found. All resources already imported.")
            return
        click.echo()

    # Log import details to file only
    import_details = []
    total_resources_to_import = 0
    for rtype in types_to_import:
        stats = metadata.get("resource_types", {}).get(rtype, {})
        count = stats.get("count", 0)
        files = stats.get("files", 0)
        total_resources_to_import += count
        import_details.append({"type": rtype, "count": count, "files": files})

    logger.debug(
        "import_starting",
        resource_type_count=len(types_to_import),
        resource_types=types_to_import,
        total_resources=total_resources_to_import,
        details=import_details,
    )

    # Confirmation check (unless --force, --yes, or --dry-run)
    if not force and not yes and not dry_run:
        click.echo()
        logger.info(
            "import_summary",
            resource_type_count=len(types_to_import),
            total_resources=total_resources_to_import,
        )
        if not click.confirm("Proceed with import?"):
            echo_info("Import cancelled")
            raise click.exceptions.Exit(0)

    async def batch_precheck_resources(
        resource_type: str,
        resources: list[dict],
        importer,
        client,
        state,
        progress,
        phase_id: str,
    ) -> list[dict]:
        """
        Proactively check which resources already exist in target environment.

        User's architecture:
        1. Clear all target_ids for resource type (start fresh)
        2. Batch query target environment by identifier (parallel)
        3. Update id_mappings for resources found in target
        4. Filter resources that still need importing (target_id is NULL)
        5. Update progress for pre-existing resources

        Args:
            resource_type: Type of resource (e.g., "users", "organizations")
            resources: All resources to check
            importer: Importer instance (provides IDENTIFIER_FIELD)
            client: Target AAP client
            state: Migration state manager
            progress: Progress display
            phase_id: Progress phase identifier

        Returns:
            List of resources that need to be imported (don't exist in target)
        """
        from aap_migration.utils.logging import get_logger

        logger = get_logger(__name__)

        if not resources:
            return []

        # Step 1: Clear target_ids to ensure we don't trust stale data
        cleared_count = state.reset_target_ids(resource_type)
        logger.info("cleared_target_ids", resource_type=resource_type, count=cleared_count)

        # Step 2: Get identifier field from importer
        identifier_field = getattr(importer, "IDENTIFIER_FIELD", "name")

        # Extract identifiers from resources
        resource_identifiers = []
        resource_by_identifier = {}

        for resource in resources:
            identifier = resource.get(identifier_field)
            source_id = resource.get("_source_id")
            if identifier and source_id:
                resource_identifiers.append(identifier)
                resource_by_identifier[identifier] = {"source_id": source_id, "data": resource}

        if not resource_identifiers:
            logger.warning(
                "no_identifiers_found",
                resource_type=resource_type,
                identifier_field=identifier_field,
            )
            return resources

        logger.info(
            "batch_checking_existing_resources",
            resource_type=resource_type,
            total=len(resource_identifiers),
            identifier_field=identifier_field,
        )

        # Step 3: Batch query target environment with URI length limit
        # Use character-based batching to avoid 414 URI Too Large errors
        # Long resource names (e.g., inventories) can cause URI to exceed 8KB limit
        MAX_QUERY_CHARS = 4000  # Safe limit for query parameters
        existing_by_identifier = {}

        # Build batches based on character count, not fixed count
        current_batch: list[str] = []
        current_length = 0
        batches: list[list[str]] = []

        for identifier in resource_identifiers:
            # Account for identifier length + comma separator
            identifier_length = len(identifier) + 1

            if current_length + identifier_length > MAX_QUERY_CHARS and current_batch:
                # Current batch is full, start new one
                batches.append(current_batch)
                current_batch = [identifier]
                current_length = identifier_length
            else:
                current_batch.append(identifier)
                current_length += identifier_length

        # Don't forget the last batch
        if current_batch:
            batches.append(current_batch)

        logger.info(
            "batch_precheck_batches_created",
            resource_type=resource_type,
            total_identifiers=len(resource_identifiers),
            num_batches=len(batches),
            max_query_chars=MAX_QUERY_CHARS,
        )

        for batch_idx, batch_identifiers in enumerate(batches):
            # Query target: GET /api/v2/{resource_type}/?{field}__in=val1,val2,val3
            filter_key = f"{identifier_field}__in"
            filters = {filter_key: ",".join(batch_identifiers)}

            try:
                existing_batch = await client.list_resources(
                    resource_type=resource_type, filters=filters
                )

                # Index by identifier for fast lookup
                # For organization-scoped resources, use composite key (name, organization)
                for existing_resource in existing_batch:
                    if resource_type in ORGANIZATION_SCOPED_RESOURCES:
                        # Use (name, organization) as composite key
                        name = existing_resource.get("name")
                        org = existing_resource.get("organization")
                        if name is not None:
                            # Handle null organization (some credentials can have null org)
                            key = (name, org) if org is not None else name
                            existing_by_identifier[key] = existing_resource
                    else:
                        # Use name only for globally unique resources
                        existing_identifier = existing_resource.get(identifier_field)
                        if existing_identifier:
                            existing_by_identifier[existing_identifier] = existing_resource

            except Exception as e:
                logger.error(
                    "batch_query_failed",
                    resource_type=resource_type,
                    batch_idx=batch_idx,
                    batch_size=len(batch_identifiers),
                    error=str(e),
                )
                # Continue with next batch

        # Step 4: Update id_mappings for resources found in target
        found_count = 0
        to_import = []

        for identifier, resource_info in resource_by_identifier.items():
            source_id = resource_info["source_id"]
            resource_data = resource_info["data"]

            # Build lookup key based on resource scope
            if resource_type in ORGANIZATION_SCOPED_RESOURCES:
                # For org-scoped resources, use (name, organization) as key
                name = resource_data.get("name")
                org = resource_data.get("organization")
                # Handle null organization (some credentials can have null org)
                lookup_key = (name, org) if org is not None else name
            else:
                # For globally unique resources, use identifier (name)
                lookup_key = identifier

            # Debug: Log lookup key being used
            logger.debug(
                "checking_resource_existence",
                resource_type=resource_type,
                source_id=source_id,
                lookup_key=str(lookup_key),
                scoped=resource_type in ORGANIZATION_SCOPED_RESOURCES,
            )

            if lookup_key in existing_by_identifier:
                # Resource exists in target - create/update id_mapping
                existing = existing_by_identifier[lookup_key]

                state.save_id_mapping(
                    resource_type=resource_type,
                    source_id=source_id,
                    target_id=existing["id"],
                    source_name=identifier,
                    target_name=existing.get(identifier_field),
                )

                found_count += 1

                logger.debug(
                    "resource_exists_in_target",
                    resource_type=resource_type,
                    source_id=source_id,
                    target_id=existing["id"],
                    lookup_key=str(lookup_key),
                )
            else:
                # Resource does NOT exist - needs to be imported
                to_import.append(resource_data)

        # Step 5: Update progress for pre-existing resources (they are skipped, not imported)
        if found_count > 0:
            # Pre-existing resources count as skipped (completed=0, failed=0, skipped=found_count)
            progress.update_phase(phase_id, 0, 0, found_count)
            logger.info(
                "pre_existing_resources_found",
                resource_type=resource_type,
                already_existing=found_count,
                to_import=len(to_import),
                total=len(resources),
            )

        return to_import

    async def run_import():
        total_imported = 0
        total_failed = 0
        total_skipped = 0
        skipped_no_importer = []

        # Track detailed stats per resource type
        run_stats = {}

        # Initialize phases
        phases = []

        # If Phase 2, check for projects to patch and add as first phase
        if phase == "phase2" and not dry_run:
            # Duplicate scanning logic to get count for progress bar
            projects_dir = input_dir / "projects"
            patch_count = 0
            if projects_dir.exists():
                json_files = sorted(projects_dir.glob("projects_*.json"))
                # Silent scan (no step_progress)
                for json_file in json_files:
                    try:
                        with open(json_file) as f:
                            resources = json.load(f)
                            for resource in resources:
                                if "_deferred_scm_details" in resource:
                                    patch_count += 1
                    except Exception:
                        pass

            if patch_count > 0:
                phases.append(("patching", "Patching Projects", patch_count))

        for rtype in types_to_import:
            stats = metadata.get("resource_types", {}).get(rtype, {})
            count = stats.get("count", 0)

            # For accurate counts, read actual file contents instead of metadata
            # (metadata count may not reflect post-transform splits like constructed inventories)
            rtype_dir = input_dir / rtype
            if rtype_dir.exists():
                actual_count = 0
                for json_file in sorted(rtype_dir.glob(f"{rtype}_*.json")):
                    try:
                        with open(json_file) as f:
                            actual_count += len(json.load(f))
                    except Exception:
                        pass
                if actual_count > 0:
                    count = actual_count

            description = rtype.replace("_", " ").title()
            phases.append((rtype, description, count))

        # Filter out resources with 0 count - no value showing empty phases
        phases = [(rtype, desc, count) for rtype, desc, count in phases if count > 0]

        try:
            # Track skipped resource types (no importer available)
            skipped_no_importer = []

            with MigrationProgressDisplay(title="🚀 AAP Import Progress", enabled=True) as progress:
                # Set total phases BEFORE initialize_phases to avoid jitter
                progress.set_total_phases(len(phases))
                # Initialize all phases upfront (guidellm pattern - like demo)
                progress.initialize_phases(phases)

                for rtype, description, total_count in phases:
                    # Handle patching phase (Phase 2 logic)
                    if rtype == "patching":
                        # Call patch logic using existing progress display
                        # Note: patch_project_scm_details handles start_phase/update/complete internally
                        await patch_project_scm_details(
                            ctx,
                            input_dir,
                            batch_size=ctx.config.performance.project_patch_batch_size,
                            interval=ctx.config.performance.project_patch_batch_interval,
                            progress_display=progress,
                        )
                        continue

                    # Start phase
                    phase_id = progress.start_phase(rtype, description, total_count)

                    # Load resume cache if resume mode is enabled
                    imported_source_ids_cache = set()
                    if resume:
                        imported_source_ids_cache = ctx.migration_state.get_imported_source_ids(
                            rtype
                        )
                        if imported_source_ids_cache:
                            logger.info(
                                "import_resume_cache_loaded",
                                resource_type=rtype,
                                already_imported=len(imported_source_ids_cache),
                            )

                    # Load all files for this resource type
                    resource_dir = input_dir / rtype
                    if not resource_dir.exists():
                        echo_warning(f"No directory for {rtype}, skipping")
                        progress.complete_phase(phase_id)
                        continue

                    # Find all JSON files for this resource type
                    json_files = sorted(resource_dir.glob(f"{rtype}_*.json"))

                    if not json_files:
                        echo_warning(f"No files found for {rtype}, skipping")
                        progress.complete_phase(phase_id)
                        continue

                    # Load resources from all files
                    all_resources = []
                    for json_file in json_files:
                        try:
                            with open(json_file) as f:
                                file_resources = json.load(f)
                                all_resources.extend(file_resources)
                        except Exception as e:
                            echo_error(f"Failed to load {json_file}: {e}")
                            continue

                    resources = all_resources
                    if not resources:
                        echo_warning(f"No {rtype} to import, skipping")
                        progress.complete_phase(phase_id)
                        continue

                    imported_count = 0
                    failed_count = 0
                    skipped_count = 0

                    # Import expects pre-transformed data from xformed/ directory
                    # Ensure _source_id is set (fallback to database lookup if missing)
                    transformed_resources = []
                    for resource in resources:
                        source_id = resource.get("_source_id")

                        # Fallback: Look up source_id from database by name if missing
                        if source_id is None:
                            resource_name = resource.get("name", "")
                            mapping = ctx.migration_state.get_mapping_by_name(rtype, resource_name)
                            if mapping:
                                source_id = mapping.source_id
                                resource["_source_id"] = source_id
                                logger.info(
                                    "recovered_source_id_from_database",
                                    resource_type=rtype,
                                    name=resource_name,
                                    source_id=source_id,
                                )
                            else:
                                logger.warning(
                                    "missing_source_id",
                                    resource_type=rtype,
                                    name=resource_name,
                                    message="No _source_id in JSON and no database mapping found",
                                )

                        transformed_resources.append(resource)

                    if not dry_run:
                        # Create appropriate importer using factory
                        try:
                            importer = create_importer(
                                rtype,
                                ctx.target_client,
                                ctx.migration_state,
                                ctx.config.performance,
                                ctx.config.resource_mappings,
                            )
                        except NotImplementedError:
                            logger.info(
                                "skipping_no_importer",
                                resource_type=rtype,
                                message=f"No importer available for {rtype}",
                            )
                            skipped_no_importer.append(rtype)
                            # Mark phase as complete (all skipped - pass 0 completed, 0 failed, total_count skipped)
                            progress.update_phase(phase_id, 0, 0, total_count)
                            progress.complete_phase(phase_id)
                            continue

                        # Import based on resource type
                        # Map resource type names to their importer method names
                        # Note: 'hosts' is handled separately below (line-by-line import)
                        method_map = {
                            # Foundation resources
                            "organizations": "import_organizations",
                            "instances": "import_instances",
                            "instance_groups": "import_instance_groups",
                            "labels": "import_labels",
                            # Identity and access
                            "users": "import_users",
                            "teams": "import_teams",
                            # Credentials
                            "credential_types": "import_credential_types",
                            "credentials": "import_credentials",
                            # Projects and execution
                            "projects": "import_projects",
                            "execution_environments": "import_execution_environments",
                            # Inventory resources (canonical names + legacy aliases)
                            "inventory": "import_inventories",
                            "inventories": "import_inventories",
                            "inventory_sources": "import_inventory_sources",
                            "groups": "import_inventory_groups",
                            "inventory_groups": "import_inventory_groups",
                            # Job templates and workflows
                            "job_templates": "import_job_templates",
                            "workflow_job_templates": "import_workflow_job_templates",
                            "schedules": "import_schedules",
                            # Constructed inventories
                            "constructed_inventories": "import_constructed_inventories",
                            # RBAC
                            "rbac": "import_rbac_assignments",
                            "role_definitions": "import_role_definitions",
                            "role_user_assignments": "import_role_user_assignments",
                            "role_team_assignments": "import_role_team_assignments",
                        }

                        method_name = method_map.get(rtype)
                        if method_name and hasattr(importer, method_name):
                            # Proactive batch pre-check: query target to find existing resources
                            # This avoids "already exists" errors and shows accurate progress
                            resources_to_import = await batch_precheck_resources(
                                resource_type=rtype,
                                resources=transformed_resources,
                                importer=importer,
                                client=ctx.target_client,
                                state=ctx.migration_state,
                                progress=progress,
                                phase_id=phase_id,
                            )

                            # Calculate skipped count (resources that already exist)
                            skipped_count = len(transformed_resources) - len(resources_to_import)

                            if resources_to_import:
                                # Create progress callback for live updates
                                def update_progress(
                                    success: int, failed: int, skipped: int, phase_id=phase_id
                                ) -> None:
                                    """Update progress display in real-time."""
                                    progress.update_phase(phase_id, success, failed, skipped)

                                method = getattr(importer, method_name)
                                results = await method(
                                    resources_to_import, progress_callback=update_progress
                                )

                                # Calculate actual imported, failed, and skipped from results
                                imported_count = len(
                                    [r for r in results if r and not r.get("_skipped")]
                                )
                                skipped_in_import = len(
                                    [r for r in results if r and r.get("_skipped")]
                                )
                                failed_count = (
                                    len(resources_to_import) - imported_count - skipped_in_import
                                )

                                # Final progress update
                                progress.update_phase(
                                    phase_id,
                                    completed=imported_count + failed_count + skipped_in_import,
                                    failed=failed_count,
                                    skipped=skipped_in_import,
                                )

                                # Aggregate this phase's skips into total_skipped
                                total_skipped += skipped_in_import
                            else:
                                imported_count = 0
                                skipped_in_import = 0  # All resources were skipped by pre-check and counted in skipped_count
                                total_skipped += skipped_in_import
                                logger.info(
                                    "all_resources_exist",
                                    resource_type=rtype,
                                    total=len(transformed_resources),
                                )

                            # NOTE: SCM sync waiting has been removed from automatic flow.
                            # With two-phase import, users run phase1 (up to projects),
                            # then manually wait for project sync, then run phase2.
                            # The wait_for_project_sync() function is still available
                            # for manual use if needed.

                        elif rtype == "hosts":
                            # Hosts are imported using bulk API for performance
                            # Group hosts by inventory for bulk import
                            hosts_by_inventory: dict[int, list[dict]] = {}
                            hosts_without_inventory = 0

                            for host in transformed_resources:
                                source_id = host.get("_source_id")

                                # Skip if already imported (resume mode)
                                if resume and source_id in imported_source_ids_cache:
                                    skipped_count += 1
                                    continue

                                inv_id = host.get("inventory")
                                if inv_id:
                                    hosts_by_inventory.setdefault(inv_id, []).append(host)
                                else:
                                    hosts_without_inventory += 1

                            if hosts_without_inventory > 0:
                                logger.warning(
                                    "hosts_without_inventory",
                                    count=hosts_without_inventory,
                                    message="Hosts skipped - no inventory field",
                                )

                            # Track totals across all inventories
                            total_created = 0
                            total_failed = hosts_without_inventory
                            total_skipped_hosts_bulk = 0

                            # Import each inventory's hosts in bulk
                            for inv_source_id, inv_hosts in hosts_by_inventory.items():
                                # Resolve source inventory ID to target inventory ID
                                target_inv_id = ctx.migration_state.get_mapped_id(
                                    "inventories", inv_source_id
                                )
                                if not target_inv_id:
                                    logger.warning(
                                        "inventory_not_mapped",
                                        source_inventory_id=inv_source_id,
                                        host_count=len(inv_hosts),
                                        message="Skipping hosts - inventory not in id_mappings",
                                    )
                                    # These are skipped (not failed) since inventory wasn't migrated
                                    total_skipped_hosts_bulk += len(inv_hosts)
                                    progress.update_phase(
                                        phase_id,
                                        total_created + total_failed,
                                        total_failed,
                                        total_skipped_hosts_bulk,
                                    )
                                    continue

                                # Create progress callback that captures current totals
                                # Using default args to capture current values
                                def bulk_progress(
                                    created: int,
                                    failed: int,
                                    skipped: int,  # Accept skipped from bulk importer
                                    _phase_id: str = phase_id,
                                    base_created: int = total_created,
                                    base_failed: int = total_failed,
                                    base_skipped: int = total_skipped_hosts_bulk,  # Pass base skipped
                                ) -> None:
                                    # completed = created + failed (NOT skipped - it's passed separately)
                                    # Progress bar will calculate: completed + skipped = total processed
                                    progress.update_phase(
                                        _phase_id,
                                        completed=base_created + created + base_failed + failed,
                                        failed=base_failed + failed,
                                        skipped=base_skipped + skipped,
                                    )

                                result = await importer.import_hosts_bulk(
                                    inventory_id=target_inv_id,
                                    hosts=inv_hosts,
                                    progress_callback=bulk_progress,
                                )

                                batch_created = result.get("total_created", 0)
                                batch_failed = result.get("total_failed", 0)
                                batch_skipped = result.get(
                                    "total_skipped", 0
                                )  # Get skipped from bulk import
                                total_created += batch_created
                                total_failed += batch_failed
                                total_skipped_hosts_bulk += batch_skipped

                            imported_count = total_created
                            failed_count = total_failed
                            skipped_in_import = (
                                total_skipped_hosts_bulk  # Update skipped count for this phase
                            )
                        else:
                            # No import method available for this resource type
                            logger.info(
                                "skipping_no_import_method",
                                resource_type=rtype,
                                message=f"No import method available for {rtype}",
                            )
                            skipped_no_importer.append(rtype)
                            # Mark as complete (all skipped - pass 0 completed, 0 failed, total_count skipped)
                            progress.update_phase(phase_id, 0, 0, total_count)
                            progress.complete_phase(phase_id)
                            continue

                        total_imported += imported_count
                        final_skipped_for_phase = (
                            skipped_in_import + skipped_count
                        )  # Combine skips from importer and pre-check
                        total_skipped += final_skipped_for_phase
                        final_failed_for_phase = (
                            len(resources) - imported_count - final_skipped_for_phase
                        )
                        total_failed += final_failed_for_phase

                        # Store stats for summary
                        run_stats[rtype] = {
                            "imported": imported_count,
                            "skipped": final_skipped_for_phase,
                            "failed": final_failed_for_phase,
                            "total": len(resources),
                        }

                        # Update final progress
                        progress.update_phase(
                            phase_id,
                            imported_count,
                            final_failed_for_phase,
                            final_skipped_for_phase,
                        )
                        logger.info(
                            "imported_resources",
                            resource_type=rtype,
                            imported=imported_count,
                            skipped=skipped_count,
                            failed=failed_count,
                        )

                    # Complete this phase
                    progress.complete_phase(phase_id)

                    # Automatic Phase 2: Patch projects if this was 'projects' import and phase is 'all'
                    if rtype == "projects" and phase == "all":
                        echo_info("Automatic Phase 2: Patching projects with SCM details...")
                        try:
                            # We can't easily nest progress bars, so let patch_projects run its own
                            # It might look a bit messy if the outer one is still active, but phase is complete
                            await patch_project_scm_details(
                                ctx,
                                input_dir,
                                batch_size=ctx.config.performance.project_patch_batch_size,
                                interval=ctx.config.performance.project_patch_batch_interval,
                            )
                        except Exception as e:
                            echo_warning(f"Project patching failed: {e}")
                            logger.error("patch_projects_failed", error=str(e))

            click.echo()
            if dry_run:
                total_resources = sum(count for _, _, count in phases)
                echo_info(f"DRY RUN: Would import {format_count(total_resources)} resources")
            else:
                echo_success(f"Successfully imported {format_count(total_imported)} resources")
                if total_skipped > 0:
                    echo_info(f"Skipped {format_count(total_skipped)} already-imported resources")
                if total_failed > 0:
                    echo_warning(f"Failed to import {format_count(total_failed)} resources")

            # Show summary
            click.echo()
            echo_info("Import Summary:")
            for rtype, description, _count in phases:
                stats = run_stats.get(rtype, {"imported": 0, "skipped": 0, "failed": 0, "total": 0})
                imported = stats["imported"]
                skipped = stats["skipped"]
                failed = stats["failed"]

                status_parts = []
                if imported > 0:
                    status_parts.append(f"{format_count(imported)} imported")
                if skipped > 0:
                    status_parts.append(f"{format_count(skipped)} skipped")
                if failed > 0:
                    status_parts.append(f"{format_count(failed)} failed")

                status_str = ", ".join(status_parts) if status_parts else "0 resources processed"

                if rtype in skipped_no_importer:
                    # Fetch total count from metadata for skipped items
                    total_in_export = (
                        metadata.get("resource_types", {}).get(rtype, {}).get("count", 0)
                    )
                    click.echo(
                        f"  {description}: {format_count(total_in_export)} resources (⚠️  SKIPPED - no importer)"
                    )
                else:
                    click.echo(f"  {description}: {status_str}")

            # Show skipped resources if any
            if skipped_no_importer:
                click.echo()
                echo_warning(
                    f"⚠️  {len(skipped_no_importer)} resource type(s) skipped (no importer available):"
                )
                for rtype in skipped_no_importer:
                    echo_warning(f"   • {rtype}")

            # Write import metadata file (REQ-002)
            import_metadata = {
                "import_timestamp": datetime.now(UTC).isoformat(),
                "source_version": metadata.get("source_version"),
                "target_version": metadata.get("target_version"),
                "target_url": ctx.config.target.url,
                "version_path_status": metadata.get("version_path_status"),
                "source_run_fingerprint": metadata.get("run_context", {}).get("run_fingerprint"),
                "total_imported": total_imported,
                "total_failed": total_failed,
                "total_skipped": total_skipped,
                "resource_types": {
                    rtype: {
                        "attempted": stats["total"],
                        "created": stats["imported"],
                        "skipped": stats["skipped"],
                        "failed": stats["failed"],
                    }
                    for rtype, stats in run_stats.items()
                },
            }

            with open(input_dir / "import_metadata.json", "w") as f:
                json.dump(import_metadata, f, indent=2)

            logger.info(
                "import_metadata_saved",
                file=str(input_dir / "import_metadata.json"),
            )

        except Exception as e:
            echo_error(f"Import failed: {e}")
            logger.error("import_failed", error=str(e), exc_info=True)
            raise click.ClickException(str(e)) from e
        finally:
            # Restore original logging handlers
            for handler in original_handlers:
                if handler not in root_logger.handlers:
                    root_logger.addHandler(handler)

    try:
        asyncio.run(run_import())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_import())
