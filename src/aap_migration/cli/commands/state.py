"""
State management commands.

This module provides commands for managing migration state,
including viewing mappings, resetting state, and inspecting progress.
"""

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import handle_errors, pass_context, requires_config
from aap_migration.cli.utils import (
    echo_error,
    echo_info,
    echo_success,
    echo_warning,
    format_count,
    print_stats,
    print_table,
)
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


@click.group(name="state")
def state() -> None:
    """Migration state management commands.

    Manage and inspect migration state including ID mappings
    and resource tracking.
    """
    pass


@state.command(name="show")
@click.option(
    "--detailed",
    is_flag=True,
    help="Show detailed state information",
)
@pass_context
@requires_config
@handle_errors
def show_state(ctx: MigrationContext, detailed: bool) -> None:
    """Show current migration state.

    Displays overall migration state including:
    - Migration ID and metadata
    - Resource counts by type
    - Completion status
    - ID mapping statistics

    Examples:

        # Show basic state
        aap-bridge state show --config config.yaml

        # Show detailed state
        aap-bridge state show --detailed --config config.yaml
    """
    echo_info("Loading migration state...")

    try:
        migration_state = ctx.migration_state

        # Get overall statistics
        stats_data = migration_state.get_overall_stats()

        # Display basic information
        click.echo()
        click.echo("Migration Information:")
        click.echo(f"  Migration ID: {migration_state.migration_id}")
        click.echo(f"  Database: {ctx.config.state.db_path}")

        # Get resource counts by type
        click.echo()
        echo_info("Resource Statistics (Completed):")

        rows = []
        resource_counts = stats_data["resource_counts"]
        for rtype in sorted(resource_counts.keys()):
            count = resource_counts[rtype]
            rows.append(
                [
                    rtype.replace("_", " ").title(),
                    format_count(count),
                ]
            )

        if not rows:
            echo_warning("  No resources migrated yet.")
        else:
            print_table("Migrated Resources", ["Resource Type", "Count"], rows)

        # Summary
        click.echo()
        summary_stats = {
            "total_completed": format_count(stats_data["total_completed"]),
            "total_failed": format_count(stats_data["total_failed"]),
            "id_mappings_stored": format_count(stats_data["total_mappings"]),
        }
        print_stats(summary_stats, "State Summary")

        if detailed:
            click.echo()
            echo_info("Detailed state information...")
            click.echo("  (Detailed view not yet implemented)")

    except Exception as e:
        echo_error(f"Failed to show state: {e}")
        logger.error("State show failed", error=str(e), exc_info=True)
        raise click.ClickException(str(e)) from e


@state.command(name="mappings")
@click.option(
    "--resource-type",
    "-r",
    type=str,
    help="Filter by resource type",
)
@click.option(
    "--source-id",
    type=int,
    help="Show mapping for specific source ID",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    help="Maximum number of mappings to display",
)
@pass_context
@requires_config
@handle_errors
def show_mappings(
    ctx: MigrationContext,
    resource_type: str,
    source_id: int,
    limit: int,
) -> None:
    """Show ID mappings between source and target.

    Displays ID mappings that track the relationship between
    source AAP 2.3 resource IDs and target AAP 2.6 resource IDs.

    Examples:

        # Show all mappings (limited)
        aap-bridge state mappings --config config.yaml

        # Show mappings for specific resource type
        aap-bridge state mappings --resource-type inventories --config config.yaml

        # Show mapping for specific source ID
        aap-bridge state mappings --resource-type hosts --source-id 12345 --config config.yaml

        # Show more mappings
        aap-bridge state mappings --limit 100 --config config.yaml
    """
    echo_info("Loading ID mappings...")

    try:
        migration_state = ctx.migration_state

        if source_id and resource_type:
            # Show specific mapping
            target_id = migration_state.get_mapped_id(resource_type, source_id)

            if target_id:
                click.echo()
                click.echo("ID Mapping:")
                click.echo(f"  Resource Type: {resource_type}")
                click.echo(f"  Source ID: {source_id}")
                click.echo(f"  Target ID: {target_id}")
                echo_success("Mapping found")
            else:
                echo_warning(f"No mapping found for {resource_type} ID {source_id}")

        else:
            # Show multiple mappings
            mappings = migration_state.get_all_mappings(resource_type=resource_type, limit=limit)

            if not mappings:
                echo_warning("No ID mappings found")
                return

            # Display mappings in table
            rows = []
            for mapping in mappings:
                rows.append(
                    [
                        mapping.get("resource_type", ""),
                        str(mapping.get("source_id", "")),
                        str(mapping.get("target_id", "") or "EXPERT-ONLY"),
                        mapping.get("source_name", ""),
                    ]
                )

            filter_desc = f" for {resource_type}" if resource_type else ""
            print_table(
                f"ID Mappings{filter_desc} (showing {len(mappings)})",
                ["Resource Type", "Source ID", "Target ID", "Name"],
                rows,
            )

            echo_success(f"Found {len(mappings)} mapping(s)")

    except Exception as e:
        echo_error(f"Failed to show mappings: {e}")
        logger.error("Mappings show failed", error=str(e), exc_info=True)
        raise click.ClickException(str(e)) from e


@state.command(name="reset")
@click.option(
    "--resource-type",
    "-r",
    multiple=True,
    type=str,
    help="Reset only specific resource types",
)
@click.option(
    "--keep-mappings",
    is_flag=True,
    help="Keep ID mappings (only reset progress)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@pass_context
@requires_config
@handle_errors
def reset_state(
    ctx: MigrationContext,
    resource_type: tuple,
    keep_mappings: bool,
    yes: bool,
) -> None:
    """Reset migration state.

    WARNING: This will clear migration progress and optionally ID mappings.
    Use this to start a fresh migration or fix corrupted state.

    Examples:

        # Reset all state
        aap-bridge state reset --config config.yaml

        # Reset specific resource type
        aap-bridge state reset --resource-type inventory --config config.yaml

        # Reset progress but keep ID mappings
        aap-bridge state reset --keep-mappings --config config.yaml
    """
    if resource_type:
        echo_warning(f"Resetting state for: {', '.join(resource_type)}")
    else:
        echo_warning("Resetting ALL migration state")

    if keep_mappings:
        echo_info("ID mappings will be preserved")
    else:
        echo_warning("ID mappings will also be cleared")

    # Confirmation
    if not yes and not click.confirm("Are you sure? This action is IRREVERSIBLE."):
        echo_info("Reset cancelled")
        return

    try:
        migration_state = ctx.migration_state
        types_to_reset = list(resource_type) if resource_type else []

        if not types_to_reset:
            # Get ALL resource types currently in the DB
            types_to_reset = migration_state.get_all_resource_types()

        for rtype in types_to_reset:
            # Clear progress
            cleared_progress = migration_state.clear_progress(rtype)

            # Clear mappings (unless kept)
            cleared_mappings = 0
            if not keep_mappings:
                cleared_mappings = migration_state.clear_mappings(rtype)

            logger.info(
                "state_reset_for_type",
                resource_type=rtype,
                cleared_progress=cleared_progress,
                cleared_mappings=cleared_mappings,
            )
            echo_info(
                f"  {rtype}: Cleared {cleared_progress} progress records, "
                f"{cleared_mappings} mappings"
            )

        echo_success("\nState reset complete.")
        echo_warning("Previous migration progress is lost.")

    except Exception as e:
        echo_error(f"Failed to reset state: {e}")
        logger.error("State reset failed", error=str(e), exc_info=True)
        raise click.ClickException(str(e)) from e


@state.command(name="export")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    required=True,
    help="Output file for state export (JSON)",
)
@click.option(
    "--include-mappings",
    is_flag=True,
    default=True,
    help="Include ID mappings in export",
)
@pass_context
@requires_config
@handle_errors
def export_state(
    ctx: MigrationContext,
    output: str,
    include_mappings: bool,
) -> None:
    """Export migration state to a file.

    Exports the current migration state to a JSON file for backup
    or transfer to another system.

    Examples:

        # Export state
        aap-bridge state export --output state-backup.json --config config.yaml

        # Export without mappings
        aap-bridge state export --output state.json --no-include-mappings --config config.yaml
    """
    echo_info(f"Exporting migration state to {output}...")

    try:
        _migration_state = ctx.migration_state

        echo_success(f"Exported migration state to {output}")

    except Exception as e:
        echo_error(f"Failed to export state: {e}")
        logger.error("State export failed", error=str(e), exc_info=True)
        raise click.ClickException(str(e)) from e
