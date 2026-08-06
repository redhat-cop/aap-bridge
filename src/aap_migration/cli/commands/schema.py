"""Schema management CLI commands."""

import asyncio
from pathlib import Path

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import handle_errors, pass_context, requires_config
from aap_migration.cli.utils import echo_info, echo_success
from aap_migration.schema.comparator import SchemaComparator
from aap_migration.schema.persistence import get_schema_info, save_schemas, schema_files_exist


@click.group(name="schema")
def schema_group():
    """Schema management commands for AAP migration."""


@schema_group.command(name="generate")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default="schemas/",
    help="Output directory for schema files (default: schemas/)",
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Re-fetch schemas even if they already exist",
)
@pass_context
@requires_config
@handle_errors
def generate_schemas(
    ctx: MigrationContext,
    output: Path,
    refresh: bool,
) -> None:
    """Generate API schemas from AAP 2.3 and 2.6 instances.

    Fetches schemas using OPTIONS HTTP method and saves to JSON files:
    - aap_2.3_schemas.json: AAP 2.3 field definitions
    - aap_2.6_schemas.json: AAP 2.6 field definitions
    - schema_comparison.json: Gap analysis for transformer

    Examples:

        # Generate schemas
        aap-bridge --config config.yaml schema generate

        # Force refresh (re-fetch)
        aap-bridge --config config.yaml schema generate --refresh

        # Custom output directory
        aap-bridge --config config.yaml schema generate --output /path/to/schemas/
    """
    output_dir = Path(output)

    # Check if schemas already exist
    if not refresh and schema_files_exist(output_dir):
        echo_info("📋 Schema files already exist")

        info = get_schema_info(output_dir)
        if info:
            echo_info(f"  Generated: {info['generated_at']}")
            echo_info(f"  Resources: {info['resource_count']}")
            echo_info(f"  Breaking changes: {info['breaking_changes']}")

        if not click.confirm("\n🔄 Regenerate schemas?", default=False):
            echo_info("Using existing schemas")
            return

    # Fetch and compare schemas with Rich progress display
    async def run_generation():
        import logging

        from aap_migration.migration.coordinator import MigrationCoordinator
        from aap_migration.reporting.live_progress import MigrationProgressDisplay
        from aap_migration.reporting.schema_report import display_schema_comparison_summary
        from aap_migration.utils.logging import get_logger

        logger = get_logger(__name__)

        # STEP 1: Suppress console logging during progress display
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        for handler in root_logger.handlers[:]:
            if hasattr(handler, "__class__") and "RichHandler" in handler.__class__.__name__:
                root_logger.removeHandler(handler)

        try:
            # STEP 2: Pre-fetch resource types
            resource_types = []
            for phase in MigrationCoordinator.MIGRATION_PHASES:
                resource_types.extend(phase["resource_types"])

            # Build phases list (one phase per resource type, 3 steps each)
            phases = []
            for rtype in resource_types:
                description = rtype.replace("_", " ").title()
                phases.append((rtype, description, 3))  # 3 steps: source + target + compare

            # STEP 3: Create progress display
            comparator = SchemaComparator()
            source_schemas = {}
            target_schemas = {}
            comparisons = {}

            with MigrationProgressDisplay(
                title="🔍 AAP Schema Generation Progress", enabled=True
            ) as progress:
                # Set total phases BEFORE initialize_phases to avoid jitter
                progress.set_total_phases(len(phases))
                progress.initialize_phases(phases)

                # STEP 4: Process each resource type
                for rtype, description, _ in phases:
                    phase_id = progress.start_phase(rtype, description, 3)
                    completed = 0
                    failed = 0

                    try:
                        # Fetch source schema (step 1)
                        source_schema = await comparator.fetch_schema(ctx.source_client, rtype)
                        source_schemas[rtype] = source_schema
                        completed += 1
                        progress.update_phase(phase_id, completed, failed)

                        # Fetch target schema (step 2)
                        target_schema = await comparator.fetch_schema(ctx.target_client, rtype)
                        target_schemas[rtype] = target_schema
                        completed += 1
                        progress.update_phase(phase_id, completed, failed)

                        # Compare schemas (step 3)
                        comparison = comparator.compare_schemas(rtype, source_schema, target_schema)
                        comparisons[rtype] = comparison
                        completed += 1
                        progress.update_phase(phase_id, completed, failed)

                    except Exception as e:
                        failed += 1
                        progress.update_phase(phase_id, completed, failed)
                        logger.error(
                            "schema_operation_failed",
                            resource_type=rtype,
                            error=str(e),
                        )

                    progress.complete_phase(phase_id)

            # STEP 5: Save schemas (outside progress display)
            click.echo()
            echo_info("💾 Saving schemas...")

            # Discover versions for provenance
            source_version = ctx.config.source.version or await ctx.source_client.get_version()
            target_version = ctx.config.target.version or await ctx.target_client.get_version()

            created_files = await save_schemas(
                source_schemas,
                target_schemas,
                comparisons,
                output_dir,
                ctx.config.source.url,
                ctx.config.target.url,
                source_version,
                target_version,
            )

            for _file_type, file_path in created_files.items():
                echo_success(f"  ✓ {file_path}")

            # STEP 6: Display summary using schema_report
            click.echo()
            display_schema_comparison_summary(comparisons)

            click.echo()
            echo_success("✅ Schema generation complete!")
            click.echo()
            echo_info("🚀 Schema files ready for schema-driven transformations")

        finally:
            # STEP 7: Restore logging handlers
            for handler in original_handlers:
                if handler not in root_logger.handlers:
                    root_logger.addHandler(handler)

    asyncio.run(run_generation())
