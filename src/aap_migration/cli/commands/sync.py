"""Experimental organization-scoped add/update sync, with a read-only plan default."""

import asyncio
import json
from typing import Any

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import handle_errors, pass_context, requires_config
from aap_migration.org_sync import SyncError, synchronize


@click.command("sync")
@click.option("--organization", required=True, help="Exact source and target organization name")
@click.option(
    "--apply", is_flag=True, help="Apply creates/updates; requires dry_run: false in config"
)
@pass_context
@requires_config
@handle_errors
def sync(ctx: MigrationContext, organization: str, apply: bool) -> None:
    """Plan or apply adds/updates for one organization's supported resources.

    Experimental lab path: static inventories/hosts, credential-free Git projects
    and job templates. No deletes, job launches, RBAC, schedules, or
    execution-environment migration.
    """
    if apply and ctx.config.dry_run:
        raise click.ClickException("--apply requires dry_run: false in the configuration.")

    async def run() -> dict[str, Any]:
        source, target = ctx.source_client, ctx.target_client
        try:
            return await synchronize(source, target, organization, apply=apply)
        finally:
            try:
                await source.close()
            finally:
                await target.close()

    try:
        report = asyncio.run(run())
    except SyncError as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps(report, indent=2))
