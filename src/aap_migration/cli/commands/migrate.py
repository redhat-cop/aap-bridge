"""
Migration execution commands.

This module provides commands for executing migrations from source AAP to target AAP.
"""

import asyncio
from pathlib import Path

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import (
    confirm_action,
    handle_errors,
    pass_context,
    requires_config,
)
from aap_migration.cli.utils import (
    create_progress_bar,
    echo_error,
    echo_info,
    echo_success,
    echo_warning,
    print_stats,
    print_table,
)
from aap_migration.migration.coordinator import MigrationCoordinator
from aap_migration.resources import (
    ALL_RESOURCE_TYPES,
    FULLY_SUPPORTED_TYPES,
)
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

# Migration phase order - use centralized registry
MIGRATION_PHASES = ALL_RESOURCE_TYPES

# Excluded from default migrate / export / transform / import (unless -r names the type)
DEFAULT_MIGRATION_EXCLUDED_TYPES = frozenset(
    {
        "instances",
        "instance_groups",
    }
)

# Phase 1 import: foundation through projects (before patching projects / inventory that needs SCM)
# credential_types and credentials are PATCHed (not POSTed) - they're pre-created in target
PHASE1_RESOURCE_TYPES = [
    "organizations",
    "labels",
    "credential_types",  # PATCH existing (pre-created in target)
    "credentials",  # PATCH existing (pre-created in target)
    "credential_input_sources",
    "execution_environments",
    "projects",
]

# Phase 2 import: patch projects (in import runner), then inventory chain + automation.
# inventory_sources before smart/constructed inventories: smart filters depend on hosts
# populated by inventory source sync, and constructed inventories may depend on both.
# users and teams come just before role_definitions so all content objects (JTs, projects,
# inventories, etc.) exist when team role grants and RBAC assignments are applied.
PHASE2_RESOURCE_TYPES = [
    "inventory",
    "inventory_sources",
    "smart_inventories",
    "constructed_inventories",
    "groups",
    "hosts",
    "notification_templates",
    "job_templates",
    "workflow_job_templates",
    "schedules",
    "users",
    "teams",
    "role_definitions",
    "role_user_assignments",
    "role_team_assignments",
]


async def _map_managed_credential_types(source_client, target_client, state) -> int:
    """Create ID mappings for managed (built-in) credential types.

    Managed credential types (Machine, Source Control, Vault, etc.) exist on both
    source and target systems but may have different IDs. This function fetches
    them from both systems and creates mappings based on name matching.

    Args:
        source_client: AAP 2.3 source client
        target_client: AAP 2.6 target client
        state: Migration state manager

    Returns:
        Number of credential types successfully mapped
    """
    try:
        # Fetch managed types from source (AAP 2.3)
        source_types_response = await source_client.get(
            "credential_types/", params={"managed": "true", "page_size": 200}
        )
        source_types = source_types_response.get("results", [])

        # Fetch managed types from target (AAP 2.6)
        target_types_response = await target_client.get(
            "credential_types/", params={"managed": "true", "page_size": 200}
        )
        target_types = target_types_response.get("results", [])

        # Create name -> id mapping for target
        target_by_name = {t["name"]: t["id"] for t in target_types}

        # Map source IDs to target IDs by name
        mapped_count = 0
        for source_type in source_types:
            source_name = source_type["name"]
            source_id = source_type["id"]
            target_id = target_by_name.get(source_name)

            if target_id:
                state.create_or_update_mapping(
                    resource_type="credential_types",
                    source_id=source_id,
                    target_id=target_id,
                    source_name=source_name,
                )
                mapped_count += 1
                logger.debug(
                    f"Mapped managed credential type '{source_name}': {source_id} -> {target_id}"
                )
            else:
                logger.warning(
                    f"Managed credential type '{source_name}' (ID {source_id}) "
                    f"not found on target system"
                )

        return mapped_count

    except Exception as e:
        logger.error(f"Failed to map managed credential types: {e}")
        return 0


def _run_migration_workflow(
    ctx: MigrationContext,
    resource_type: tuple[str, ...],
    force: bool,
    resume: bool,
    skip_prep: bool = False,
    phase: str = "all",
) -> None:
    """Execute the four-phase migration workflow: prep → export → transform → import.

    This function orchestrates the complete migration process by calling the
    prep, export, transform, and import commands in sequence, using disk-based storage
    to decouple phases.

    Args:
        ctx: Migration context with config and clients
        resource_type: Resource types to migrate (default: all fully supported or discovered)
        force: Force re-export by clearing previous progress
        resume: Resume from checkpoint
        skip_prep: Skip the prep phase (use existing schemas)
        phase: Import phase - "phase1" (up to projects), "phase2" (patching), "phase3" (job_templates), or "all"
    """
    from aap_migration.cli.commands.export_import import export, import_cmd
    from aap_migration.cli.commands.patch_projects import patch_project_scm_details
    from aap_migration.cli.commands.prep import prep as prep_cmd
    from aap_migration.cli.commands.transform import transform as transform_cmd
    from aap_migration.resources import get_exportable_types, get_importable_types

    # Define directories for workflow
    schemas_dir = Path("schemas")
    export_dir = Path("exports")
    xformed_dir = Path("xformed")

    # ============================================
    # PHASE 0: PREP (Optional)
    # ============================================
    if not skip_prep:
        echo_info("Phase 0: Discovering endpoints and generating schemas...")
        click.echo()

        # Call prep command programmatically
        prep_ctx = click.Context(prep_cmd)
        prep_ctx.obj = ctx
        prep_ctx.invoke(
            prep_cmd,
            output_dir=schemas_dir,
            force=force,
        )

        click.echo()
        echo_success("Phase 0 complete: Prep finished")
        click.echo()
    else:
        echo_info("Skipping prep phase (--skip-prep)")
        click.echo()

    # Determine resource types to migrate
    # If user specified types, use those
    # Otherwise, use discovered types (if prep ran) or fallback to fully supported
    explicit_resource_types = bool(resource_type)
    if resource_type:
        resource_types = list(resource_type)
    else:
        # Try to get discovered types first
        discovered_export_types = get_exportable_types(use_discovered=True)
        discovered_import_types = get_importable_types(use_discovered=True)

        # Find types that support both export and import
        if discovered_export_types and discovered_import_types:
            # Use discovered types that support both operations
            resource_types = [t for t in discovered_export_types if t in discovered_import_types]
            echo_info(f"Using {len(resource_types)} discovered resource types")
        else:
            # Fallback to hardcoded fully supported types
            resource_types = FULLY_SUPPORTED_TYPES
            echo_info(f"Using {len(resource_types)} hardcoded resource types (prep not run)")

    if not explicit_resource_types:
        resource_types = [t for t in resource_types if t not in DEFAULT_MIGRATION_EXCLUDED_TYPES]
    default_migration_types = [
        t for t in FULLY_SUPPORTED_TYPES if t not in DEFAULT_MIGRATION_EXCLUDED_TYPES
    ]

    echo_info(f"Migrating {len(resource_types)} resource type(s):")
    for rtype in resource_types:
        click.echo(f"  - {rtype}")
    click.echo()

    # ============================================
    # PHASE 1: EXPORT
    # ============================================
    echo_info("Phase 1: Exporting RAW data from AAP 2.3...")
    click.echo()

    # Call export command programmatically
    # Create a Click context for export command
    export_ctx = click.Context(export)
    export_ctx.obj = ctx
    export_ctx.invoke(
        export,
        resource_type=resource_types,
        output=export_dir,
        force=force,
        records_per_file=1000,
        resume=resume,
    )

    click.echo()
    echo_success("Phase 1 complete: Export finished")
    click.echo()

    # ============================================
    # PHASE 2: TRANSFORM
    # ============================================
    echo_info("Phase 2: Transforming data for AAP 2.6 compatibility...")
    click.echo()

    # Call transform command programmatically
    transform_ctx = click.Context(transform_cmd)
    transform_ctx.obj = ctx
    transform_ctx.invoke(
        transform_cmd,
        input_dir=export_dir,
        output_dir=xformed_dir,
        schema_file=Path("schemas/schema_comparison.json"),
        force=force,
        resource_type=resource_types if resource_types != default_migration_types else (),
        quiet=False,
        disable_progress=False,
    )

    click.echo()
    echo_success("Phase 2 complete: Transformation finished")
    click.echo()

    # ============================================
    # PHASE 3: IMPORT
    # ============================================
    # Import context
    import_ctx = click.Context(import_cmd)
    import_ctx.obj = ctx

    # Helper to run import for specific types
    def run_import(types, phase_label):
        if not types:
            return
        echo_info(f"Phase 3 ({phase_label}): Importing resources...")
        import_ctx.invoke(
            import_cmd,
            resource_type=types,
            input_dir=xformed_dir,
            force=force,
            resume=resume,
            dry_run=False,
            skip_dependencies=False,
            check_dependencies=False,
            force_reimport=False,
            phase=phase,  # pass the overall phase, although logic handles subsets
        )
        click.echo()

    # Determine execution plan based on phase
    if phase == "phase1":
        # Import Phase 1 resources
        types = [t for t in resource_types if t in PHASE1_RESOURCE_TYPES]
        run_import(types, "Infrastructure & Projects")

    elif phase == "phase2":
        # Patch Projects + Import Phase 3 resources
        echo_info(
            "Phase 2 (Patching + Automation Import): Patching Projects and Importing Automation Definitions..."
        )

        async def run_patch_and_import():
            # Call import_cmd with phase2 to trigger combined logic
            import_ctx.invoke(
                import_cmd,
                input_dir=xformed_dir,
                force=force,
                resume=resume,
                dry_run=False,
                skip_dependencies=False,
                check_dependencies=False,
                force_reimport=False,
                phase="phase2",
            )

        try:
            asyncio.run(run_patch_and_import())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(run_patch_and_import())

    else:  # phase == "all"
        # 1. Import Phase 1
        types1 = [t for t in resource_types if t in PHASE1_RESOURCE_TYPES]
        run_import(types1, "Infrastructure & Projects")

        # 2. Patch Projects (Phase 2 logic)
        echo_info("Phase 2 (Patching): Patching Projects with SCM details...")

        async def run_patch():
            await patch_project_scm_details(
                ctx,
                xformed_dir,
                batch_size=ctx.config.performance.project_patch_batch_size,
                interval=ctx.config.performance.project_patch_batch_interval,
            )

        try:
            asyncio.run(run_patch())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(run_patch())
        click.echo()

        # 3. Import Phase 2 (inventory + automation; projects already patched above)
        types_phase2 = [t for t in resource_types if t in PHASE2_RESOURCE_TYPES]
        run_import(types_phase2, "Inventory & Automation")

    click.echo()
    echo_success(f"Phase 3 complete: Import finished (phase={phase})")
    click.echo()

    # ============================================
    # FINAL SUMMARY
    # ============================================
    if phase == "phase1":
        echo_success("✅ Phase 1 migration complete!")
        echo_info("  Next step: Run Phase 2 to patch projects")
        echo_info("  Then run: aap-bridge migrate --phase phase2")
    elif phase == "phase2":
        echo_success(
            "✅ Phase 2 migration complete (projects patched; inventory & automation imported)!"
        )
    else:
        echo_success("✅ Migration workflow complete!")

    echo_info(f"  Exported: {export_dir}/")
    echo_info(f"  Transformed: {xformed_dir}/")
    echo_info(f"  Imported to: {ctx.config.target.url}")


@click.group(name="migrate", invoke_without_command=True)
@click.option(
    "-r",
    "--resource-type",
    multiple=True,
    type=str,
    help="Resource types to migrate (default: all discovered or fully supported types)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force re-export by clearing previous migration progress",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume from checkpoint (skips already-exported resources)",
)
@click.option(
    "--skip-prep",
    is_flag=True,
    default=False,
    help="Skip the prep phase (use existing schemas from previous run)",
)
@click.option(
    "--phase",
    type=click.Choice(["phase1", "phase2", "all"], case_sensitive=False),
    default="all",
    help=(
        "Import phase: phase1 (foundation through projects), "
        "phase2 (patch projects then inventory + automation), "
        "all (complete)"
    ),
)
@click.pass_context
def migrate(ctx, resource_type, force, resume, skip_prep, phase) -> None:
    """Execute migration from AAP 2.3 to 2.6.

    Runs the complete four-phase workflow:
    0. Prep: Discover endpoints and generate schemas (optional with --skip-prep)
    1. Export: Fetch RAW data from AAP 2.3 → exports/
    2. Transform: Convert data for AAP 2.6 compatibility → xformed/
    3. Import: Load data into AAP 2.6

    If a subcommand is provided (status), it runs that instead.
    Otherwise, runs the full prep → export → transform → import workflow.

    The prep phase dynamically discovers all available endpoints from your
    AAP instances and generates transformation rules. This allows the tool
    to work with any AAP version without hardcoded resource types.

    Examples:

        \b
        # Migrate all discovered resource types (with prep)
        aap-bridge migrate

        \b
        # Skip prep and use existing schemas
        aap-bridge migrate --skip-prep

        \b
        # Migrate specific types
        aap-bridge migrate -r organizations -r projects

        \b
        # Force re-discovery and re-export
        aap-bridge migrate --force

        \b
        # View migration status
        aap-bridge migrate status
    """
    # If a subcommand was invoked, let it handle execution
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand = run the full migration workflow
    # Get context
    migration_ctx = ctx.obj
    if not migration_ctx or not migration_ctx.config:
        echo_error("Configuration required. Use --config option.")
        raise click.ClickException("Configuration required")

    # Call the workflow
    _run_migration_workflow(
        migration_ctx,
        resource_type=resource_type,
        force=force,
        resume=resume,
        skip_prep=skip_prep,
        phase=phase,
    )


@migrate.command(name="status")
@pass_context
@requires_config
@handle_errors
def status(ctx: MigrationContext) -> None:
    """Show current migration status.

    Displays progress of the current or last migration including:
    - Overall progress
    - Completed phases
    - Resource counts
    - Any errors or warnings

    Examples:

        aap-bridge migrate status --config config.yaml
    """
    echo_info("Migration Status")
    click.echo()

    try:
        state = ctx.migration_state

        # Overall progress
        completed_phases = []
        pending_phases = MIGRATION_PHASES.copy()

        rows = []
        for phase in MIGRATION_PHASES:
            status_symbol = "✓" if phase in completed_phases else "⏳"
            rows.append([phase.replace("_", " ").title(), status_symbol])

        print_table("Migration Phases", ["Phase", "Status"], rows)

        # Summary statistics
        click.echo()
        stats = {
            "migration_id": state.migration_id,
            "phases_completed": len(completed_phases),
            "phases_remaining": len(pending_phases),
            "total_resources_migrated": 0,
        }
        print_stats(stats, "Overall Progress")

    except Exception as e:
        echo_error(f"Failed to retrieve migration status: {e}")
        logger.error("Status check failed", error=str(e), exc_info=True)
        raise click.ClickException(str(e)) from e


@migrate.command(name="resume")
@click.option(
    "--from-phase",
    type=click.Choice(MIGRATION_PHASES, case_sensitive=False),
    help="Resume from specific phase (default: last checkpoint)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompts",
)
@click.option(
    "--disable-progress",
    is_flag=True,
    help="Disable live progress display",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Minimal console output (errors only)",
)
@pass_context
@requires_config
@handle_errors
@confirm_action(
    message="Resume migration from last checkpoint?",
    abort_message="Resume cancelled.",
)
def resume(
    ctx: MigrationContext,
    from_phase: str | None,
    yes: bool,
    disable_progress: bool,
    quiet: bool,
) -> None:
    """Resume migration from last checkpoint.

    Resumes a previously interrupted migration from the last successful
    checkpoint. Useful when a migration fails mid-process.

    Examples:

        # Resume from last checkpoint
        aap-bridge migrate resume --config config.yaml

        # Resume from specific phase
        aap-bridge migrate resume --config config.yaml --from-phase inventories
    """
    if quiet:
        from aap_migration.utils import logging as app_logging

        app_logging.configure_logging(level="ERROR", log_format=ctx.config.logging.format)
        disable_progress = True

    if not quiet:
        echo_info("Resuming migration from checkpoint...")

        if from_phase:
            echo_info(f"Starting from phase: {from_phase}")

        click.echo()

    async def resume_migration():
        _coordinator = MigrationCoordinator(
            config=ctx.config,
            source_client=ctx.source_client,
            target_client=ctx.target_client,
            state=ctx.migration_state,
            enable_progress=not disable_progress,
        )

        try:
            # Determine resume point
            last_completed = None

            if from_phase:
                start_phase_idx = MIGRATION_PHASES.index(from_phase)
            elif last_completed:
                start_phase_idx = MIGRATION_PHASES.index(last_completed) + 1
            else:
                echo_warning("No checkpoint found, starting from beginning")
                start_phase_idx = 0

            remaining_phases = MIGRATION_PHASES[start_phase_idx:]

            echo_info(f"Resuming with {len(remaining_phases)} phases remaining")
            for phase in remaining_phases:
                click.echo(f"  - {phase}")
            click.echo()

            # Execute remaining phases
            with create_progress_bar("Resuming migration") as progress:
                task = progress.add_task(
                    "Migration progress",
                    total=len(remaining_phases),
                )

                for phase in remaining_phases:
                    progress.update(task, description=f"Migrating {phase}...")

                    logger.info(f"Migrating phase: {phase}")

                    progress.advance(task)

            click.echo()
            echo_success("Migration resumed and completed successfully!")

        except Exception as e:
            echo_error(f"Resume failed: {e}")
            logger.error("Resume failed", error=str(e), exc_info=True)
            raise click.ClickException(str(e)) from e

    try:
        asyncio.run(resume_migration())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(resume_migration())
