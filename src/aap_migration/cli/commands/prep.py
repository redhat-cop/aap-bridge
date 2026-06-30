"""Prep command for endpoint discovery and schema generation.

This module provides the `aap-bridge prep` command that discovers
all available endpoints from source and target AAP instances and
generates schemas for transformation.
"""

from pathlib import Path

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import (
    handle_errors,
    pass_context,
    requires_config,
)
from aap_migration.cli.utils import echo_info, echo_success
from aap_migration.prep.workflow import run_prep_workflow_sync, suppress_verbose_prep_logging


@click.command(name="prep")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("schemas"),
    help="Output directory for schema files (default: schemas/)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force re-discovery even if schemas exist",
)
@pass_context
@requires_config
@handle_errors
def prep(ctx: MigrationContext, output_dir: Path, force: bool) -> None:
    """Discover endpoints and generate schemas from AAP instances.

    This command:
    1. Connects to source AAP 2.3 and target AAP 2.6
    2. Discovers all available endpoints
    3. Generates schemas for each endpoint
    4. Compares schemas and generates transformation rules

    Outputs:
        schemas/source_endpoints.json - Source endpoints
        schemas/target_endpoints.json - Target endpoints
        schemas/source_schema.json - Source schema
        schemas/target_schema.json - Target schema
        schemas/schema_comparison.json - Transformation rules

    Examples:

        \\b
        # Discover and generate schemas
        aap-bridge prep --config config.yaml

        \\b
        # Force re-discovery
        aap-bridge prep --config config.yaml --force

        \\b
        # Custom output directory
        aap-bridge prep --config config.yaml --output-dir my_schemas/
    """
    suppress_verbose_prep_logging()

    source_endpoints_file = output_dir / "source_endpoints.json"
    target_endpoints_file = output_dir / "target_endpoints.json"

    if not force and source_endpoints_file.exists() and target_endpoints_file.exists():
        click.echo()
        if not click.confirm("Schema files already exist. Overwrite?", default=False):
            click.echo("Cancelled.")
            return

    result = run_prep_workflow_sync(
        ctx,
        output_dir,
        force=force,
        skip_if_exists=False,
        log=echo_info,
    )
    if result.status == "failed":
        raise click.ClickException(result.message or "Prep failed")

    click.echo()
    echo_success(f"Prep complete! Output: {output_dir}/")
