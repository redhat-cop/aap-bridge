"""
Main CLI entry point for AAP Bridge.

This module provides the command-line interface for migrating from
Ansible Automation Platform 2.3 to 2.6.
"""

import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from aap_migration import __version__
from aap_migration.cli.commands import checkpoint as checkpoint_commands
from aap_migration.cli.commands import cleanup as cleanup_commands
from aap_migration.cli.commands import config as config_commands
from aap_migration.cli.commands import export_import
from aap_migration.cli.commands import info as info_commands
from aap_migration.cli.commands import metadata as metadata_commands
from aap_migration.cli.commands import migrate as migrate_commands
from aap_migration.cli.commands import patch_projects as patch_projects_commands
from aap_migration.cli.commands import prep as prep_commands
from aap_migration.cli.commands import schema as schema_commands
from aap_migration.cli.commands import state as state_commands
from aap_migration.cli.commands import transform as transform_commands
from aap_migration.cli.commands import validate as validate_commands
from aap_migration.cli.context import MigrationContext
from aap_migration.cli.menu import interactive_menu
from aap_migration.utils.logging import configure_logging, get_logger

# Load environment variables from .env file
load_dotenv()

logger = get_logger(__name__)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="aap-bridge")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
    envvar="AAP_BRIDGE_CONFIG",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="ERROR",
    help="Set console logging level (file logging stays at DEBUG)",
    envvar="AAP_BRIDGE_LOG_LEVEL",
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    help="Log to file instead of stdout",
    envvar="AAP_BRIDGE_LOG_FILE",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: Path | None,
    log_level: str,
    log_file: Path | None,
) -> None:
    """AAP Bridge - Migrate from source AAP to target AAP.

    This tool helps migrate Ansible Automation Platform installations from
    one version to another, handling organizations, inventories, hosts, job
    templates, and other resources.

    Running without arguments launches an interactive menu.

    Examples:

        # Interactive menu
        aap-bridge

        # Validate configuration
        aap-bridge config validate --config config.yaml

        # Run full migration
        aap-bridge migrate full --config config.yaml

        # Export resources only
        aap-bridge export --config config.yaml --output export.json

        # Show migration status
        aap-bridge migrate status --config config.yaml
    """
    # Setup logging with optional file output
    # If --log-file is provided, use it; otherwise default to logs/migration.log
    effective_log_file = str(log_file) if log_file else "logs/migration.log"

    # Ensure logs directory exists
    log_path = Path(effective_log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    configure_logging(level=log_level, log_file=effective_log_file)

    # Create context
    ctx.obj = MigrationContext(
        config_path=config,
        log_level=log_level,
        log_file=log_file,
    )

    logger.debug(
        "CLI initialized",
        config=str(config) if config else None,
        log_level=log_level,
    )

    # Launch interactive menu if no subcommand provided
    if ctx.invoked_subcommand is None:
        interactive_menu(ctx)


# Register command groups
cli.add_command(checkpoint_commands.checkpoint)
cli.add_command(config_commands.config)
cli.add_command(info_commands.info)
cli.add_command(metadata_commands.metadata)
cli.add_command(migrate_commands.migrate)
cli.add_command(schema_commands.schema_group)
cli.add_command(state_commands.state)

# Register standalone commands
cli.add_command(cleanup_commands.cleanup)
cli.add_command(prep_commands.prep)
cli.add_command(export_import.export)
cli.add_command(transform_commands.transform)
cli.add_command(export_import.import_cmd, name="import")
cli.add_command(patch_projects_commands.patch_projects)
cli.add_command(validate_commands.validate)
cli.add_command(validate_commands.report)


def main() -> int:
    """Main entry point for CLI."""
    try:
        cli(standalone_mode=False)
        return 0
    except click.ClickException as e:
        return e.exit_code
    except Exception as e:
        logger.error("Unexpected error", error=str(e), exc_info=True)
        click.echo(f"Error: {e}", err=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
