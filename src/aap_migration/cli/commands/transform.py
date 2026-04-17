"""Transform command for AAP 2.3 → 2.6 data transformation.

This module provides the standalone transform command that reads raw
AAP 2.3 exports and transforms them to AAP 2.6 compatible format.

Architecture:
    Export → RAW data (exports/) → Transform → Transformed data (xformed/) → Import
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import handle_errors, pass_context
from aap_migration.cli.utils import (
    echo_error,
    echo_info,
    echo_warning,
    format_count,
)
from aap_migration.migration.parallel_transformer import ParallelTransformCoordinator
from aap_migration.migration.state import MigrationState
from aap_migration.migration.transformer import SkipResourceError, create_transformer
from aap_migration.reporting.live_progress import MigrationProgressDisplay
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


def sort_by_transform_order(resource_types: list[str]) -> list[str]:
    """Sort resources by migration_order (dependency order).

    Resources with migration_order in RESOURCE_REGISTRY are sorted first.
    Unknown resources are appended at the end.

    Args:
        resource_types: List of resource types to sort

    Returns:
        Sorted list in transform order (dependencies before dependents)
    """
    from aap_migration.resources import RESOURCE_REGISTRY, normalize_resource_type

    known = []
    unknown = []

    for rtype in resource_types:
        # Normalize endpoint name (e.g., "groups" → "inventory_groups")
        normalized = normalize_resource_type(rtype)
        info = RESOURCE_REGISTRY.get(normalized)

        if info and hasattr(info, "migration_order"):
            known.append((rtype, info.migration_order))  # Keep original name
        else:
            unknown.append(rtype)

    # Sort known types by migration_order (ascending)
    known.sort(key=lambda x: x[1])

    # Return sorted known types + unknown types at end
    return [rtype for rtype, _ in known] + unknown


async def seed_builtin_credential_types(ctx: MigrationContext, state: MigrationState) -> int:
    """Seed id_mappings with built-in credential types from source and target AAP.

    Fetches managed (built-in) credential types from both AAP instances,
    matches them by name, and creates id_mapping records with source_id → target_id.

    This ensures that credentials referencing built-in types pass dependency
    validation during transformation.

    Args:
        ctx: Migration context with source and target clients
        state: Migration state manager for id_mappings

    Returns:
        Number of built-in credential types seeded
    """
    try:
        # Fetch managed (built-in) credential types from source AAP 2.3
        source_types = {}
        source_credential_types = await ctx.source_client.get_credential_types(
            params={"managed": "true"}
        )
        for ct in source_credential_types:
            source_types[ct["name"]] = ct["id"]

        logger.debug(
            "fetched_source_credential_types",
            count=len(source_types),
            types=list(source_types.keys())[:5],
        )

        # Fetch managed (built-in) credential types from target AAP 2.6
        target_types = {}
        target_credential_types = await ctx.target_client.list_resources(
            "credential_types", filters={"managed": "true"}
        )
        for ct in target_credential_types:
            target_types[ct["name"]] = ct["id"]

        logger.debug(
            "fetched_target_credential_types",
            count=len(target_types),
            types=list(target_types.keys())[:5],
        )

        # Create id_mappings for matching types
        seeded_count = 0
        for name, source_id in source_types.items():
            target_id = target_types.get(name)
            if target_id:
                # Update with target_id (creates record if missing)
                state.mark_completed(
                    resource_type="credential_types",
                    source_id=source_id,
                    target_id=target_id,
                    target_name=name,
                    source_name=name,
                )
                seeded_count += 1
                logger.debug(
                    "seeded_builtin_credential_type",
                    name=name,
                    source_id=source_id,
                    target_id=target_id,
                )
            else:
                logger.warning(
                    "builtin_credential_type_not_found_in_target",
                    name=name,
                    source_id=source_id,
                )

        logger.info(
            "builtin_credential_types_seeded",
            count=seeded_count,
            source_count=len(source_types),
            target_count=len(target_types),
        )
        return seeded_count

    except Exception as e:
        logger.warning(
            "seed_builtin_credential_types_failed",
            error=str(e),
            message="Could not seed built-in credential types - credentials may fail validation",
        )
        return 0


@click.command(name="transform")
@click.option(
    "--input",
    "-i",
    "input_dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Input directory with RAW exports (default: exports/)",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for transformed data (default: xformed/)",
)
@click.option(
    "--schema-comparison",
    "-s",
    "schema_file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Schema comparison file (default: schemas/schema_comparison.json)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite output directory if it exists",
)
@click.option(
    "--resource-type",
    "-r",
    multiple=True,
    help="Resource types to transform (default: all)",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress progress display, show errors only",
)
@click.option(
    "--disable-progress",
    is_flag=True,
    help="Disable live progress display (for CI/CD environments)",
)
@click.option(
    "--skip-pending-deletion/--no-skip-pending-deletion",
    default=True,
    help="Skip inventories marked for deletion (pending_deletion=true). Default: skip.",
)
@click.option(
    "--defer-project-sync/--no-defer-project-sync",
    default=True,
    help="Defer project SCM sync by stripping SCM details (hydrated in Phase 2). Default: defer.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Automatically confirm prompts (skip confirmation)",
)
@pass_context
@handle_errors
def transform(
    ctx: MigrationContext,
    input_dir: Path | None,
    output_dir: Path | None,
    schema_file: Path | None,
    force: bool,
    resource_type: tuple,
    quiet: bool,
    disable_progress: bool,
    skip_pending_deletion: bool,
    defer_project_sync: bool,
    yes: bool,
) -> None:
    """Transform RAW AAP 2.3 data to AAP 2.6 compatible format.

    Reads RAW exports from input directory, transforms them for AAP 2.6
    compatibility, and writes to output directory. This is the middle
    phase in the three-phase migration process:

    \b
    1. Export → RAW data to exports/
    2. Transform → RAW to transformed (exports/ → xformed/)
    3. Import → transformed data to AAP 2.6

    Examples:

        \b
        # Transform all resource types (uses defaults: exports/ → xformed/)
        aap-bridge transform

        \b
        # Transform specific types
        aap-bridge transform --resource-type inventories --resource-type hosts

        \b
        # Disable project sync deferral (projects will sync immediately on import)
        aap-bridge transform --no-defer-project-sync

        \b
        # Force overwrite existing transformed data
        aap-bridge transform --force

        \b
        # Quiet mode (errors only)
        aap-bridge transform --quiet

        \b
        # Custom directories
        aap-bridge transform --input /custom/exports/ --output /custom/xformed/
    """
    # Use defaults from config if not provided
    if input_dir is None:
        input_dir = Path(ctx.config.paths.export_dir)
    else:
        input_dir = Path(input_dir)

    if output_dir is None:
        output_dir = Path(ctx.config.paths.transform_dir)
    else:
        output_dir = Path(output_dir)

    if schema_file is None:
        schema_file = Path(ctx.config.paths.schema_dir) / "schema_comparison.json"
    else:
        schema_file = Path(schema_file)

    # Load metadata from input directory
    metadata_file = input_dir / "metadata.json"
    if not metadata_file.exists():
        echo_error(f"❌ Metadata file not found: {metadata_file}")
        raise click.ClickException("Invalid export directory - metadata.json missing")

    with open(metadata_file) as f:
        metadata = json.load(f)

    # Determine resource types to transform
    available_types = list(metadata.get("resource_types", {}).keys())
    types_to_transform = list(resource_type) if resource_type else available_types

    # Sort by dependency order to ensure id_mappings exist for dependent resources
    # (e.g., credential_types must be transformed before credentials)
    types_to_transform = sort_by_transform_order(types_to_transform)

    # Check for missing prerequisite types (REQ-006)
    from aap_migration.migration.transformer import DEPENDENCY_MAP
    from aap_migration.resources import normalize_resource_type

    missing_prerequisites: list[str] = []
    for rtype in types_to_transform:
        deps = DEPENDENCY_MAP.get(rtype, [])
        for dep_type in deps:
            # If the dependency is supposed to be in this transform run but was
            # empty in the export, or if it wasn't exported at all
            dep_key = normalize_resource_type(dep_type)
            dep_meta = metadata.get("resource_types", {}).get(dep_key, {})
            if dep_meta.get("count", 0) == 0:
                missing_prerequisites.append(f"{rtype} requires {dep_key} (exported 0 resources)")

    if missing_prerequisites:
        echo_warning("Pipeline continuity issues detected:")
        for msg in missing_prerequisites:
            click.echo(f"  ⚠ {msg}")
        echo_warning(
            "Dependent resources will be skipped during transform. "
            "Consider re-exporting if this is unexpected."
        )

    if not types_to_transform:
        echo_error("❌ No resource types found to transform")
        raise click.ClickException("Export directory appears empty")

    # Check/create output directory
    if output_dir.exists() and not force:
        if not yes and not click.confirm(f"⚠️  Directory {output_dir} exists. Overwrite?"):
            raise click.exceptions.Exit(0)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Log transform configuration to file only (use debug to avoid console output)
    logger.debug(
        "transform_starting",
        resource_type_count=len(types_to_transform),
        resource_types=types_to_transform,
        defer_project_sync=defer_project_sync,
    )

    async def run_transform():
        import logging

        # Suppress console logging for cleaner output
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        if not disable_progress:
            for handler in root_logger.handlers[:]:
                if hasattr(handler, "__class__") and "RichHandler" in handler.__class__.__name__:
                    root_logger.removeHandler(handler)

        total_transformed = 0
        total_failed = 0
        total_skipped_by_transformer = 0  # New total for skips from individual transformers
        transform_stats = {}
        # Aggregate field stats across all resource types
        aggregated_trans_stats = {
            "fields_removed": 0,
            "fields_added": 0,
            "fields_renamed": 0,
        }
        null_org_credentials = []  # Track credentials with null organization removed

        try:
            # Schema comparison file path for transformers
            schema_file_path = (
                str(schema_file) if schema_file and Path(schema_file).exists() else None
            )

            # Log transformer config to file
            logger.info(
                "transformer_config",
                mode="AAP 2.3 → 2.6",
                schema_file=schema_file_path,
                auto_apply=schema_file_path is not None,
                defer_project_sync=defer_project_sync,
            )

            # Seed built-in credential types from source and target AAP
            # This creates id_mappings entries so credentials pass dependency validation
            if ctx.config_path:
                try:
                    state = ctx.migration_state
                    seeded = await seed_builtin_credential_types(ctx, state)
                    logger.info("seeded_credential_type_mappings", count=seeded)
                except Exception as e:
                    logger.warning(
                        "seed_credential_types_skipped",
                        error=str(e),
                        message="Could not seed credential types - continuing without",
                    )

            # Build phases for progress display
            phases = []
            for rtype in types_to_transform:
                stats = metadata.get("resource_types", {}).get(rtype, {})
                count = stats.get("count", 0)
                description = rtype.replace("_", " ").title()
                phases.append((rtype, description, count))

            # Filter out resources with 0 count - no value showing empty phases
            phases = [(rtype, desc, count) for rtype, desc, count in phases if count > 0]

            # Use Live progress display
            progress_enabled = not quiet and not disable_progress

            with MigrationProgressDisplay(
                title="🔄 AAP Transform Progress (2.3 → 2.6)", enabled=progress_enabled
            ) as progress:
                if progress_enabled:
                    # Set total phases BEFORE initialize_phases to avoid jitter
                    progress.set_total_phases(len(phases))
                    progress.initialize_phases(phases)

                # Check if parallel transformation is enabled
                parallel_enabled = ctx.config.performance.parallel_resource_types

                if parallel_enabled:
                    # Parallel transformation
                    # Create coordinator
                    coordinator = ParallelTransformCoordinator(
                        migration_state=ctx.migration_state,
                        performance_config=ctx.config.performance,
                        input_dir=input_dir,
                        output_dir=output_dir,
                        schema_comparison_file="schema_comparison.json",
                        target_client=ctx.target_client,
                        skip_pending_deletion=ctx.config.transform.skip_pending_deletion,
                        config=ctx.config,
                        defer_project_sync=defer_project_sync,
                    )

                    # Create progress callback
                    def progress_callback(rtype: str, stats: dict):
                        if progress_enabled:
                            total_skipped = (
                                stats.get("skipped_pending_deletion", 0)
                                + stats.get("skipped_smart_inventories", 0)
                                + stats.get("skipped_dynamic_hosts", 0)
                                + stats.get("skipped_missing_inventory", 0)
                                + stats.get("skipped_from_transformer", 0)
                            )
                            progress.update_phase(
                                rtype, stats.get("count", 0), stats.get("failed", 0), total_skipped
                            )

                    # Start all phases
                    if progress_enabled:
                        for rtype, description, total_count in phases:
                            progress.start_phase(rtype, description, total_count)

                    # Run parallel transformation
                    resource_types_list = [rtype for rtype, _, _ in phases]
                    results = await coordinator.transform_all_parallel(
                        resource_types_list, progress_callback
                    )

                    # Process results
                    for rtype, stats in results.items():
                        total_transformed += stats.get("count", 0)
                        total_failed += stats.get("failed", 0)

                        # Collect credentials with null org removed (if tracked in stats)

                        transform_stats[rtype] = {
                            "count": stats.get("count", 0),
                            "files": stats.get("files", 0),
                            "failed": stats.get("failed", 0),
                            "skipped_pending_deletion": stats.get("skipped_pending_deletion", 0),
                            "skipped_custom_managed": stats.get("skipped_custom_managed", 0),
                            "skipped_missing_inventory": stats.get("skipped_missing_inventory", 0),
                            "skipped_smart_inventories": stats.get("skipped_smart_inventories", 0),
                            "skipped_dynamic_hosts": stats.get("skipped_dynamic_hosts", 0),
                            "skipped_from_transformer": stats.get(
                                "skipped_from_transformer", 0
                            ),  # Aggregate this
                        }
                        total_skipped_by_transformer += stats.get(
                            "skipped_from_transformer", 0
                        )  # Add to total

                        # Aggregate field stats
                        aggregated_trans_stats["fields_removed"] += stats.get("fields_removed", 0)
                        aggregated_trans_stats["fields_added"] += stats.get("fields_added", 0)
                        aggregated_trans_stats["fields_renamed"] += stats.get("fields_renamed", 0)

                        if progress_enabled:
                            progress.complete_phase(rtype)

                    # Skip sequential loop
                    sequential_phases = []
                else:
                    sequential_phases = phases

                # Sequential transformation (original logic)
                for rtype, description, total_count in sequential_phases:
                    if progress_enabled:
                        phase_id = progress.start_phase(rtype, description, total_count)

                    # Read RAW files from input directory
                    input_type_dir = input_dir / rtype
                    if not input_type_dir.exists():
                        if not quiet:
                            echo_warning(f"⚠️  No directory for {rtype}, skipping")
                        if progress_enabled:
                            progress.complete_phase(phase_id)
                        continue

                    # Find all JSON files (split files: resourcetype_0001.json, etc.)
                    json_files = sorted(input_type_dir.glob(f"{rtype}_*.json"))
                    if not json_files:
                        if not quiet:
                            echo_warning(f"⚠️  No files found for {rtype}, skipping")
                        if progress_enabled:
                            progress.complete_phase(phase_id)
                        continue

                    # Create output directory
                    output_type_dir = output_dir / rtype
                    output_type_dir.mkdir(parents=True, exist_ok=True)

                    # Create resource-specific transformer (credentials → CredentialTransformer, etc.)
                    # Pass state to enable id_mappings registration during transformation
                    state = ctx.migration_state if ctx.config_path else None
                    transformer = create_transformer(
                        resource_type=rtype,
                        dry_run=False,
                        schema_comparison_file=schema_file_path,
                        state=state,
                        input_dir=input_dir,
                        config=ctx.config,
                        defer_project_sync=defer_project_sync,
                    )

                    # Transform files
                    transformed_count = 0
                    failed_count = 0
                    skipped_pending_deletion = 0
                    skipped_custom_managed = 0
                    skipped_missing_inventory = 0
                    skipped_smart_inventories = 0
                    skipped_dynamic_hosts = 0
                    skipped_from_transformer = 0
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

                            # Filter out inventories (pending_deletion and smart)
                            if rtype == "inventories":
                                original_count = len(raw_resources)
                                filtered_resources = []
                                for resource in raw_resources:
                                    if skip_pending_deletion and resource.get("pending_deletion"):
                                        logger.info(
                                            "skipping_pending_deletion_inventory",
                                            resource_type="inventories",
                                            source_id=resource.get("_source_id")
                                            or resource.get("id"),
                                            source_name=resource.get("name"),
                                        )
                                        skipped_pending_deletion += 1
                                    elif (
                                        ctx.config.export.skip_smart_inventories
                                        and resource.get("kind") == "smart"
                                    ):
                                        logger.info(
                                            "skipping_smart_inventory",
                                            resource_type="inventories",
                                            source_id=resource.get("_source_id")
                                            or resource.get("id"),
                                            source_name=resource.get("name"),
                                        )
                                        skipped_smart_inventories += 1
                                    elif (
                                        ctx.config.export.skip_constructed_inventories
                                        and resource.get("kind") == "constructed"
                                    ):
                                        logger.info(
                                            "skipping_constructed_inventory",
                                            resource_type="inventories",
                                            source_id=resource.get("_source_id")
                                            or resource.get("id"),
                                            source_name=resource.get("name"),
                                        )
                                        skipped_smart_inventories += 1
                                    else:
                                        filtered_resources.append(resource)
                                raw_resources = filtered_resources
                                if skipped_pending_deletion > 0 or skipped_smart_inventories > 0:
                                    logger.debug(
                                        "filtered_inventories",
                                        resource_type=rtype,
                                        original=original_count,
                                        filtered=len(raw_resources),
                                        skipped_pending=skipped_pending_deletion,
                                        skipped_smart=skipped_smart_inventories,
                                    )

                            # Filter out custom managed credential_types
                            # Built-in types: managed=true, NO created_by (system-created)
                            # Custom managed types: managed=true, HAS created_by (user-created)
                            # Note: created_by can be in summary_fields OR related (as URL)
                            if rtype == "credential_types":
                                original_count = len(raw_resources)
                                filtered_resources = []
                                for resource in raw_resources:
                                    is_managed = resource.get("managed", False)
                                    summary_fields = resource.get("summary_fields", {})
                                    related = resource.get("related", {})

                                    # Check both locations for created_by
                                    has_created_by_summary = "created_by" in summary_fields
                                    has_created_by_related = "created_by" in related
                                    has_created_by = (
                                        has_created_by_summary or has_created_by_related
                                    )

                                    if is_managed and has_created_by:
                                        # Custom managed type - skip it
                                        created_by_user = (
                                            summary_fields.get("created_by", {}).get("username")
                                            if has_created_by_summary
                                            else related.get("created_by", "")
                                        )
                                        logger.info(
                                            "skipping_custom_managed_credential_type",
                                            resource_type="credential_types",
                                            source_id=resource.get("_source_id")
                                            or resource.get("id"),
                                            source_name=resource.get("name"),
                                            created_by=created_by_user,
                                            in_summary_fields=has_created_by_summary,
                                            in_related=has_created_by_related,
                                            message="Managed credential type with created_by - not built-in",
                                        )
                                        skipped_custom_managed += 1
                                    else:
                                        filtered_resources.append(resource)
                                raw_resources = filtered_resources
                                if skipped_custom_managed > 0:
                                    logger.info(
                                        "filtered_custom_managed_credential_types",
                                        resource_type=rtype,
                                        original=original_count,
                                        filtered=len(raw_resources),
                                        skipped=skipped_custom_managed,
                                    )

                            # Filter out dynamic hosts (only when config flag is set)
                            if rtype == "hosts" and ctx.config.export.skip_dynamic_hosts:
                                original_count = len(raw_resources)
                                filtered_resources = []
                                for resource in raw_resources:
                                    if resource.get("has_inventory_sources"):
                                        logger.info(
                                            "skipping_dynamic_host",
                                            resource_type="hosts",
                                            source_id=resource.get("_source_id")
                                            or resource.get("id"),
                                            source_name=resource.get("name"),
                                        )
                                        skipped_dynamic_hosts += 1
                                    else:
                                        filtered_resources.append(resource)
                                raw_resources = filtered_resources
                                if skipped_dynamic_hosts > 0:
                                    logger.debug(
                                        "filtered_dynamic_hosts",
                                        resource_type=rtype,
                                        original=original_count,
                                        filtered=len(raw_resources),
                                        skipped=skipped_dynamic_hosts,
                                    )

                            # Note: Orphan host filtering (hosts with unmapped inventories)
                            # is handled during import phase when id_mappings has data

                            # Transform each resource
                            transformed_batch = []
                            for resource in raw_resources:
                                try:
                                    # Transform resource (in-memory)
                                    transformed = transformer.transform_resource(rtype, resource)

                                    # Preserve _source_id for mapping
                                    source_id = resource.get("_source_id") or resource.get("id")
                                    transformed["_source_id"] = source_id

                                    transformed_batch.append(transformed)
                                    transformed_count += 1

                                    # Track credentials with null organization removed
                                    if rtype == "credentials":
                                        had_null_org = resource.get("organization") is None
                                        no_org_after = "organization" not in transformed
                                        if had_null_org and no_org_after:
                                            cred_name = resource.get("name") or f"ID:{source_id}"
                                            null_org_credentials.append(cred_name)

                                except SkipResourceError as e:
                                    logger.warning(
                                        "resource_skipped_error",
                                        resource_type=rtype,
                                        source_id=e.source_id,
                                        reason=str(e),
                                    )
                                    skipped_from_transformer += 1

                                except Exception as e:
                                    logger.warning(
                                        "transformation_failed",
                                        resource_type=rtype,
                                        source_id=resource.get("_source_id") or resource.get("id"),
                                        source_name=resource.get("name"),
                                        error=str(e),
                                    )
                                    failed_count += 1

                                # Update progress with all skipped types
                                total_skipped = (
                                    skipped_pending_deletion
                                    + skipped_smart_inventories
                                    + skipped_dynamic_hosts
                                    + skipped_missing_inventory
                                    + skipped_from_transformer
                                )
                                if progress_enabled:
                                    # completed = transformed + failed (NOT skipped)
                                    # Progress bar calculates: completed + skipped = total processed
                                    progress.update_phase(
                                        phase_id,
                                        transformed_count + failed_count,
                                        failed_count,
                                        total_skipped,
                                    )

                            # Filter hosts whose inventory is not in id_mappings
                            # This eliminates hosts belonging to non-exported inventories
                            # (e.g., those with pending_deletion=true)
                            if rtype == "hosts" and ctx.config_path:
                                try:
                                    state = ctx.migration_state
                                    filtered_batch = []
                                    for host in transformed_batch:
                                        inventory_id = host.get("inventory")
                                        if inventory_id and state.has_source_mapping(
                                            "inventories", inventory_id
                                        ):
                                            filtered_batch.append(host)
                                        else:
                                            logger.info(
                                                "host_skipped_missing_inventory",
                                                resource_type="hosts",
                                                source_id=host.get("_source_id"),
                                                source_name=host.get("name"),
                                                inventory_id=inventory_id,
                                                message="Host's inventory not in id_mappings",
                                            )
                                            skipped_missing_inventory += 1
                                    transformed_batch = filtered_batch
                                except Exception as e:
                                    logger.warning(
                                        "host_filtering_failed",
                                        error=str(e),
                                        message="Could not filter hosts - writing all",
                                    )

                            # Pre-populate ID mappings for credentials/credential_types
                            # This queries the target environment to find matching resources
                            # and saves id_mappings for dependency resolution during import
                            if rtype in ["credentials", "credential_types"] and ctx.config_path:
                                try:
                                    if hasattr(ctx, "target_client") and ctx.target_client:
                                        mapped_count = 0
                                        for resource in transformed_batch:
                                            source_id = resource.get("_source_id")
                                            if source_id:
                                                await transformer.populate_target_id_from_target(
                                                    resource,
                                                    ctx.target_client,
                                                    state,
                                                    source_id,
                                                )
                                                mapped_count += 1
                                        if mapped_count > 0:
                                            logger.info(
                                                "populated_target_id_mappings",
                                                resource_type=rtype,
                                                count=mapped_count,
                                                message="Pre-populated ID mappings from target",
                                            )
                                except Exception as e:
                                    logger.warning(
                                        "populate_target_id_failed",
                                        resource_type=rtype,
                                        error=str(e),
                                        message="Could not pre-populate ID mappings - import will handle",
                                    )

                            # Split constructed inventories into separate directory
                            if rtype == "inventories":
                                constructed_batch = [
                                    r for r in transformed_batch if r.get("kind") == "constructed"
                                ]
                                if constructed_batch:
                                    constructed_dir = output_dir / "constructed_inventories"
                                    constructed_dir.mkdir(parents=True, exist_ok=True)
                                    constructed_file = (
                                        constructed_dir
                                        / f"constructed_inventories_{output_file_num:04d}.json"
                                    )
                                    with open(constructed_file, "w") as f:
                                        json.dump(constructed_batch, f, indent=2)
                                    logger.info(
                                        "constructed_inventories_split",
                                        count=len(constructed_batch),
                                        file=str(constructed_file),
                                    )
                                    # Remove constructed from regular batch
                                    transformed_batch = [
                                        r
                                        for r in transformed_batch
                                        if r.get("kind") != "constructed"
                                    ]

                            # Write transformed batch (preserve same file numbering)
                            output_file_num += 1
                            output_file = output_type_dir / f"{rtype}_{output_file_num:04d}.json"
                            with open(output_file, "w") as f:
                                json.dump(transformed_batch, f, indent=2)

                            logger.debug(
                                "transform_file_written",
                                resource_type=rtype,
                                file=str(output_file),
                                records=len(transformed_batch),
                            )

                        except Exception as e:
                            echo_error(f"❌ Failed to transform {json_file}: {e}")
                            logger.error(
                                "transform_file_failed",
                                file=str(json_file),
                                error=str(e),
                                exc_info=True,
                            )
                            continue

                    total_transformed += transformed_count
                    total_failed += failed_count
                    total_skipped_by_transformer += skipped_from_transformer
                    transform_stats[rtype] = {
                        "count": transformed_count,
                        "files": output_file_num,
                        "failed": failed_count,
                        "skipped_pending_deletion": skipped_pending_deletion,
                        "skipped_custom_managed": skipped_custom_managed,
                        "skipped_missing_inventory": skipped_missing_inventory,
                        "skipped_smart_inventories": skipped_smart_inventories,
                        "skipped_dynamic_hosts": skipped_dynamic_hosts,
                        "skipped_from_transformer": skipped_from_transformer,
                    }

                    # Log skipped pending_deletion at end of resource type
                    if skipped_pending_deletion > 0:
                        logger.info(
                            "transform_skipped_pending_deletion",
                            resource_type=rtype,
                            count=skipped_pending_deletion,
                        )

                    # Log skipped custom managed credential_types at end of resource type
                    if skipped_custom_managed > 0:
                        logger.info(
                            "transform_skipped_custom_managed",
                            resource_type=rtype,
                            count=skipped_custom_managed,
                            message="Custom managed credential types skipped (not built-in)",
                        )

                    # Log skipped hosts with missing inventory at end of resource type
                    if skipped_missing_inventory > 0:
                        logger.info(
                            "transform_skipped_missing_inventory",
                            resource_type=rtype,
                            count=skipped_missing_inventory,
                            message="Hosts skipped - inventory not in id_mappings",
                        )
                        if not quiet:
                            echo_warning(
                                f"⚠️  {skipped_missing_inventory} hosts skipped "
                                f"(inventory not in id_mappings)"
                            )

                    # Log skipped smart inventories
                    if skipped_smart_inventories > 0:
                        logger.info(
                            "transform_skipped_smart_inventories",
                            resource_type=rtype,
                            count=skipped_smart_inventories,
                            message="Smart inventories skipped",
                        )

                    # Log skipped dynamic hosts
                    if skipped_dynamic_hosts > 0:
                        logger.info(
                            "transform_skipped_dynamic_hosts",
                            resource_type=rtype,
                            count=skipped_dynamic_hosts,
                            message="Dynamic hosts skipped",
                        )

                    # Log skipped from transformer.stats (e.g., credential type lookups)
                    if skipped_from_transformer > 0:
                        logger.info(
                            "transform_skipped_from_transformer",
                            resource_type=rtype,
                            count=skipped_from_transformer,
                            message="Resources skipped during transformer-specific logic",
                        )

                    if progress_enabled:
                        progress.complete_phase(phase_id)

            # Write transformed metadata (REQ-007)
            transformed_metadata = {
                "transform_timestamp": datetime.now(UTC).isoformat(),
                "source_version": metadata.get("source_version"),
                "target_version": metadata.get("target_version"),
                "source_url_fingerprint": metadata.get("source_url_fingerprint"),
                "source_run_fingerprint": metadata.get("run_context", {}).get("run_fingerprint"),
                "version_path_status": metadata.get("version_path_status"),
                "source_metadata": metadata,  # Keep for backward compatibility
                "total_resources": total_transformed,
                "total_failed": total_failed,
                "total_skipped": total_skipped_by_transformer,
                "records_per_file": metadata.get("records_per_file", 1000),
                "resource_types": {
                    rtype: {
                        "input_count": metadata.get("resource_types", {})
                        .get(rtype, {})
                        .get("count", 0),
                        "transformed_count": stats["count"],
                        "skipped_count": stats.get("skipped_pending_deletion", 0)
                        + stats.get("skipped_custom_managed", 0)
                        + stats.get("skipped_missing_inventory", 0)
                        + stats.get("skipped_smart_inventories", 0)
                        + stats.get("skipped_dynamic_hosts", 0)
                        + stats.get("skipped_from_transformer", 0),
                        "failed_count": stats["failed"],
                    }
                    for rtype, stats in transform_stats.items()
                },
                "schema_comparison_file": str(schema_file)
                if schema_file and Path(schema_file).exists()
                else None,
            }

            with open(output_dir / "metadata.json", "w") as f:
                json.dump(transformed_metadata, f, indent=2)

            # Log detailed transform info to file
            logger.info(
                "transform_completed",
                total_resources=total_transformed,
                total_failed=total_failed,
                resource_types=list(transform_stats.keys()),
                transform_stats=transform_stats,
                fields_removed=aggregated_trans_stats["fields_removed"],
                fields_added=aggregated_trans_stats["fields_added"],
                fields_renamed=aggregated_trans_stats["fields_renamed"],
                null_org_credentials=null_org_credentials,
            )

            # Show concise transform summary
            click.echo()
            echo_info("Transform Summary:")
            click.echo(f"  Resources transformed: {format_count(total_transformed)}")
            click.echo(f"  Resource types: {len(transform_stats)}")
            click.echo(
                f"  Fields removed: {format_count(aggregated_trans_stats['fields_removed'])}"
            )
            if total_skipped_by_transformer > 0:
                click.echo(
                    f"  Skipped by transformer: {format_count(total_skipped_by_transformer)}"
                )
            if total_failed > 0:
                click.echo(f"  Failed: {format_count(total_failed)}")
            if null_org_credentials:
                click.echo(f"  Credentials with null org removed: {len(null_org_credentials)}")

        except Exception as e:
            echo_error(f"❌ Transform failed: {e}")
            logger.error("transform_failed", error=str(e), exc_info=True)
            raise click.ClickException(str(e)) from e
        finally:
            # Restore logging handlers
            for handler in original_handlers:
                if handler not in root_logger.handlers:
                    root_logger.addHandler(handler)

    try:
        asyncio.run(run_transform())
    except RuntimeError:
        # Handle case where event loop already running
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_transform())
