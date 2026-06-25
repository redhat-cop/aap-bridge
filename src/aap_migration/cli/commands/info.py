"""
Info commands for AAP Bridge.
"""

import click
from rich.console import Console
from rich.table import Table

from aap_migration.resources import (
    ENDPOINT_TO_RESOURCE_TYPE,
    NEVER_MIGRATE_RESOURCES,
    RESOURCE_REGISTRY,
    ResourceCategory,
    get_resource_category_reason,
)

console = Console()


@click.group()
def info() -> None:
    """Show information about the migration tool and resources."""
    pass


@info.command()
@click.pass_context
def resources(ctx: click.Context) -> None:
    """Show the resource support matrix."""
    table = Table(title="Resource Support Matrix")
    table.add_column("Canonical Name", style="cyan")
    table.add_column("API Endpoint", style="green")
    table.add_column("Category", style="magenta")
    table.add_column("Aliases", style="yellow")
    table.add_column("Caveats/Reason")

    # Get aliases grouped by canonical name
    aliases_by_canonical: dict[str, list[str]] = {}
    for alias, canonical in ENDPOINT_TO_RESOURCE_TYPE.items():
        if alias == canonical:
            continue
        if canonical not in aliases_by_canonical:
            aliases_by_canonical[canonical] = []
        aliases_by_canonical[canonical].append(alias)

    # 1. Migrate Category
    migrate_resources = [
        info for info in RESOURCE_REGISTRY.values() if info.category == ResourceCategory.MIGRATE
    ]
    migrate_resources.sort(key=lambda x: x.migration_order)

    for info in migrate_resources:
        aliases = ", ".join(aliases_by_canonical.get(info.name, []))
        caveats = get_resource_category_reason(info.name) or "-"
        table.add_row(info.name, info.endpoint, "migrate", aliases or "-", caveats)

    # 2. Export-Only Category
    export_only = [
        info for info in RESOURCE_REGISTRY.values() if info.category == ResourceCategory.EXPORT_ONLY
    ]
    for info in export_only:
        aliases = ", ".join(aliases_by_canonical.get(info.name, []))
        reason = get_resource_category_reason(info.name) or "-"
        table.add_row(info.name, info.endpoint, "export-only", aliases or "-", reason)

    # 3. Never Migrate Category
    # Sort them for better display
    never_migrate_names = sorted(NEVER_MIGRATE_RESOURCES.keys())
    for name in never_migrate_names:
        reason = NEVER_MIGRATE_RESOURCES[name]
        table.add_row(name, f"{name}/", "never-migrate", "-", reason)

    console.print(table)

    # Summary
    migrate_count = len(migrate_resources)
    export_count = len(export_only)
    never_count = len(NEVER_MIGRATE_RESOURCES)

    click.echo(
        f"\nSummary: {migrate_count} migrate, {export_count} export-only, {never_count} never-migrate."
    )
