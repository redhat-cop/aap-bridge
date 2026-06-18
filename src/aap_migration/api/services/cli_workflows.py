"""CLI-equivalent workflows for web API background jobs."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import click

from aap_migration.api.models import Connection
from aap_migration.api.services.engine_adapter import load_runtime_config
from aap_migration.cli.commands.cleanup import (
    cancel_all_jobs,
    clear_database,
    delete_resources,
    get_cleanup_resource_types,
)
from aap_migration.cli.context import MigrationContext
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.migration.parallel_exporter import ParallelExportCoordinator
from aap_migration.cli.commands.migrate import DEFAULT_MIGRATION_EXCLUDED_TYPES
from aap_migration.resources import (
    RESOURCE_REGISTRY,
    get_exportable_types,
    normalize_resource_type,
)

LogFn = Callable[[str], None]


def build_migration_context(conn: Connection, db_url: str) -> MigrationContext:
    """Build a MigrationContext for a single saved connection."""
    ctx = MigrationContext()
    ctx._config = load_runtime_config(conn, conn, db_url)
    return ctx


def build_migration_context_pair(
    source: Connection, dest: Connection, db_url: str
) -> MigrationContext:
    """Build a MigrationContext for a source/destination migration pair."""
    ctx = MigrationContext()
    ctx._config = load_runtime_config(source, dest, db_url)
    return ctx


def migration_resource_types() -> list[str]:
    """Return exportable migration resource types in migration order."""
    return _export_resource_types()


def _export_resource_types() -> list[str]:
    types_to_export: list[str] = []
    for resource_type in get_exportable_types(use_discovered=True):
        normalized = normalize_resource_type(resource_type)
        if normalized not in DEFAULT_MIGRATION_EXCLUDED_TYPES:
            types_to_export.append(normalized)
    types_to_export.sort(
        key=lambda rt: RESOURCE_REGISTRY[rt].migration_order if rt in RESOURCE_REGISTRY else 999
    )
    return types_to_export


@dataclass
class ExportWorkflowResult:
    output_dir: Path
    total_resources: int
    resource_types: int
    errors: int


@dataclass
class CleanupWorkflowResult:
    deleted: int
    skipped: int
    errors: int
    cleared_progress: int = 0
    deleted_mappings: int = 0
    directories_removed: list[str] = field(default_factory=list)


def _clean_workflow_directories(ctx: MigrationContext, log: LogFn | None = None) -> list[str]:
    """Remove local export and transform directories, matching CLI cleanup."""
    directories = {
        "exports": Path(ctx.config.paths.export_dir),
        "xformed": Path(ctx.config.paths.transform_dir),
    }
    removed: list[str] = []
    for label, path in directories.items():
        if not path.exists() or not path.is_dir():
            continue
        try:
            shutil.rmtree(path)
            removed.append(label)
            if log:
                log(f"Removed {label} directory: {path}")
        except OSError as exc:
            if log:
                log(f"Failed to remove {label} directory {path}: {exc}")
    return removed


async def run_connection_export(
    conn: Connection,
    db_url: str,
    output_dir: Path,
    *,
    log: LogFn | None = None,
) -> ExportWorkflowResult:
    """Export resources from a connection using the CLI parallel export coordinator."""
    ctx = build_migration_context(conn, db_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    types_to_export = _export_resource_types()

    if log:
        log(f"Exporting {len(types_to_export)} resource types to {output_dir}")

    coordinator = ParallelExportCoordinator(
        source_client=ctx.source_client,
        migration_state=ctx.migration_state,
        performance_config=ctx.config.performance,
        output_dir=output_dir,
        records_per_file=ctx.config.export.records_per_file,
        export_config=ctx.config.export,
    )

    def progress_callback(resource_type: str, stats: dict) -> None:
        if not log:
            return
        exported = stats.get("exported", 0)
        failed = stats.get("failed", 0)
        if exported or failed:
            log(f"  {resource_type}: exported={exported} failed={failed}")

    if ctx.config.performance.parallel_resource_types:
        parallel_results = await coordinator.export_all_parallel(
            resource_types=types_to_export,
            resume=False,
            progress_callback=progress_callback,
        )
    else:
        parallel_results = {}
        for resource_type in types_to_export:
            if log:
                log(f"Exporting {resource_type}...")
            parallel_results[resource_type] = await coordinator.export_resource_type(
                resource_type,
                resume=False,
                progress_callback=progress_callback,
            )

    total_resources = 0
    total_errors = 0
    exported_types = 0
    for resource_type, stats in parallel_results.items():
        exported_count = stats.get("exported", 0)
        failed_count = stats.get("failed", 0)
        total_resources += exported_count
        total_errors += failed_count
        if exported_count > 0:
            exported_types += 1

    metadata = {
        "export_timestamp": datetime.now(UTC).isoformat(),
        "source_url": ctx.config.source.url,
        "source_version": ctx.config.source.version,
        "target_version": ctx.config.target.version,
        "total_resources": total_resources,
        "resource_types": parallel_results,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    await ctx.source_client.close()
    return ExportWorkflowResult(
        output_dir=output_dir,
        total_resources=total_resources,
        resource_types=exported_types,
        errors=total_errors,
    )


async def run_connection_cleanup(
    conn: Connection,
    db_url: str,
    *,
    log: LogFn | None = None,
) -> CleanupWorkflowResult:
    """Run CLI-equivalent cleanup for a destination connection.

    Saved web connections are not modified. Migration progress tables and local
    export/transform directories are cleared so the next run starts fresh.
    """
    ctx = build_migration_context(conn, db_url)
    target_client = AAPTargetClient(
        config=ctx.config.target,
        rate_limit=ctx.config.performance.rate_limit,
    )

    total_deleted = 0
    total_skipped = 0
    total_errors = 0
    cleared_progress = 0
    deleted_mappings = 0
    directories_removed: list[str] = []

    try:
        if log:
            log("Clearing migration state database tables...")
        cleared_progress, deleted_mappings = clear_database(str(ctx.config.state.db_path))
        if log:
            log(
                "Database cleared: "
                f"{cleared_progress} progress records, {deleted_mappings} id mappings"
            )

        if log:
            log("Cancelling active jobs...")
        cancel_result = await cancel_all_jobs(client=target_client, config=ctx.config)
        if log:
            log(f"Cancelled jobs: {cancel_result}")

        resource_types = await get_cleanup_resource_types(target_client, use_discovered=True)
        if log:
            log(f"Cleaning up {len(resource_types)} resource types on target...")

        for resource_type in resource_types:
            if log:
                log(f"Cleaning up {resource_type}...")
            try:
                deleted, skipped, errors, _failed = await delete_resources(
                    client=target_client,
                    resource_type=resource_type,
                    config=ctx.config,
                    skip_default=True,
                )
                total_deleted += deleted
                total_skipped += skipped
                total_errors += errors
                if log:
                    log(f"  {resource_type}: deleted={deleted} skipped={skipped} errors={errors}")
            except Exception as exc:
                total_errors += 1
                if log:
                    log(f"  {resource_type}: error - {exc}")

        directories_removed = _clean_workflow_directories(ctx, log=log)

        return CleanupWorkflowResult(
            deleted=total_deleted,
            skipped=total_skipped,
            errors=total_errors,
            cleared_progress=cleared_progress,
            deleted_mappings=deleted_mappings,
            directories_removed=directories_removed,
        )
    finally:
        await target_client.close()


@dataclass
class PhasedMigrationResult:
    status: str
    message: str = ""


@contextmanager
def _route_click_output_to_log(log: LogFn | None) -> Iterator[None]:
    if log is None:
        yield
        return

    original_echo = click.echo

    def _log_echo(message: object = "", *args: object, **kwargs: object) -> None:
        text = str(message)
        if args:
            try:
                text = text % args
            except (TypeError, ValueError):
                text = f"{text} {' '.join(str(arg) for arg in args)}"
        if text.strip():
            log(text)

    click.echo = _log_echo
    try:
        yield
    finally:
        click.echo = original_echo


def _run_phased_migration_workflow(
    ctx: MigrationContext,
    *,
    force: bool,
    resume: bool,
    skip_prep: bool,
    log: LogFn | None,
) -> None:
    from aap_migration.cli.commands.migrate import _run_migration_workflow

    with _route_click_output_to_log(log):
        _run_migration_workflow(
            ctx,
            resource_type=(),
            force=force,
            resume=resume,
            skip_prep=skip_prep,
            phase="all",
        )


async def run_phased_migration(
    source: Connection,
    dest: Connection,
    db_url: str,
    *,
    log: LogFn | None = None,
    force: bool = False,
    resume: bool = False,
    skip_prep: bool = True,
) -> PhasedMigrationResult:
    """Run export → transform → import using the CLI migration workflow."""
    ctx = build_migration_context_pair(source, dest, db_url)
    try:
        await asyncio.to_thread(
            _run_phased_migration_workflow,
            ctx,
            force=force,
            resume=resume,
            skip_prep=skip_prep,
            log=log,
        )
        return PhasedMigrationResult(status="completed")
    except click.ClickException as exc:
        return PhasedMigrationResult(status="failed", message=str(exc))
    except Exception as exc:
        return PhasedMigrationResult(status="failed", message=str(exc))
