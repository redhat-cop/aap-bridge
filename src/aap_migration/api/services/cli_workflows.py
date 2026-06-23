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
from aap_migration.config import DEFAULT_SKIP_EXECUTION_ENVIRONMENT_NAMES, resolve_config_path
from aap_migration.cli.commands.cleanup import (
    cancel_all_jobs,
    clear_database,
    delete_resources,
    get_cleanup_resource_types,
)
from aap_migration.cli.context import MigrationContext
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.cli.commands.migrate import DEFAULT_MIGRATION_EXCLUDED_TYPES
from aap_migration.resources import (
    ORGANIZATION_SCOPED_RESOURCES,
    PARENT_SCOPED_RESOURCES,
    RESOURCE_REGISTRY,
    ResourceCategory,
    FULLY_SUPPORTED_TYPES,
    get_endpoint,
    get_exportable_types,
    get_importable_types,
    get_resource_category,
    normalize_resource_type,
)

LogFn = Callable[[str], None]

PREVIEW_DETAIL_LIMIT = 200
PREVIEW_TRUNCATE_TYPES = frozenset({"hosts", "groups"})


def _web_migration_context() -> MigrationContext:
    """Build a MigrationContext shell with config path for Web UI CLI invocations."""
    ctx = MigrationContext()
    ctx.config_path = resolve_config_path()
    return ctx


def build_migration_context(conn: Connection, db_url: str) -> MigrationContext:
    """Build a MigrationContext for a single saved connection."""
    ctx = _web_migration_context()
    ctx._config = load_runtime_config(conn, conn, db_url)
    return ctx


def build_migration_context_pair(
    source: Connection, dest: Connection, db_url: str
) -> MigrationContext:
    """Build a MigrationContext for a source/destination migration pair."""
    ctx = _web_migration_context()
    ctx._config = load_runtime_config(source, dest, db_url)
    return ctx


def migration_resource_types() -> list[str]:
    """Return exportable migration resource types in migration order."""
    return filtered_migration_resource_types()


def filtered_migration_resource_types() -> list[str]:
    """Return resource types using the same filters as CLI export/migrate."""
    discovered_export = get_exportable_types(use_discovered=True)
    discovered_import = get_importable_types(use_discovered=True)

    if discovered_export and discovered_import:
        import_types = {normalize_resource_type(name) for name in discovered_import}
        candidate_types = [
            normalize_resource_type(name)
            for name in discovered_export
            if normalize_resource_type(name) in import_types
        ]
    else:
        candidate_types = [normalize_resource_type(name) for name in FULLY_SUPPORTED_TYPES]

    types_to_process: list[str] = []
    seen: set[str] = set()
    for resource_type in candidate_types:
        if resource_type in DEFAULT_MIGRATION_EXCLUDED_TYPES or resource_type in seen:
            continue
        if get_resource_category(resource_type) == ResourceCategory.NEVER_MIGRATE:
            continue
        try:
            get_endpoint(resource_type)
        except KeyError:
            continue
        seen.add(resource_type)
        types_to_process.append(resource_type)

    types_to_process.sort(
        key=lambda rt: RESOURCE_REGISTRY[rt].migration_order if rt in RESOURCE_REGISTRY else 999
    )
    return types_to_process


def _export_resource_types() -> list[str]:
    return filtered_migration_resource_types()


@dataclass
class PrepWorkflowResult:
    status: str
    message: str = ""
    skipped: bool = False


def schema_comparison_path(ctx: MigrationContext) -> Path:
    """Return the schema comparison file path for a migration context."""
    return Path(ctx.config.paths.schema_dir) / "schema_comparison.json"


def migration_schemas_exist(ctx: MigrationContext) -> bool:
    """Return True when schema comparison artifacts are present."""
    return schema_comparison_path(ctx).exists()


async def run_migration_prep(
    source: Connection,
    dest: Connection,
    db_url: str,
    *,
    force: bool = False,
    skip_if_exists: bool = True,
    log: LogFn | None = None,
) -> PrepWorkflowResult:
    """Run endpoint discovery and schema generation for a connection pair."""
    from aap_migration.prep.workflow import run_prep_workflow

    ctx = build_migration_context_pair(source, dest, db_url)
    output_dir = Path(ctx.config.paths.schema_dir)
    try:
        result = await run_prep_workflow(
            ctx,
            output_dir,
            force=force,
            skip_if_exists=skip_if_exists,
            log=log,
        )
        if result.status == "failed":
            return PrepWorkflowResult(status="failed", message=result.message)
        return PrepWorkflowResult(status="completed", skipped=result.skipped)
    finally:
        await ctx.source_client.close()
        await ctx.target_client.close()


def _preview_summary_field_name(item: dict, field_name: str) -> str | None:
    summary_fields = item.get("summary_fields") or {}
    field_summary = summary_fields.get(field_name)
    if isinstance(field_summary, dict):
        return field_summary.get("name") or field_summary.get("username")
    return None


def _preview_summary_field_value(item: dict, field_name: str, value_name: str) -> str | None:
    summary_fields = item.get("summary_fields") or {}
    field_summary = summary_fields.get(field_name)
    if isinstance(field_summary, dict):
        value = field_summary.get(value_name)
        if isinstance(value, str):
            return value
    return None


def _preview_resource_identifier(resource_type: str, item: dict) -> str:
    username = item.get("username")
    if resource_type == "users" and isinstance(username, str) and username:
        return username
    name = item.get("name")
    if isinstance(name, str) and name:
        return name
    if isinstance(username, str) and username:
        return username
    return f"id-{item.get('id', '?')}"


def _preview_match_key(resource_type: str, item: dict) -> str | tuple[str, str]:
    canonical_type = normalize_resource_type(resource_type)
    if canonical_type == "credentials":
        return f"credential:{item.get('id', '?')}"
    identifier = _preview_resource_identifier(resource_type, item)
    if canonical_type in ORGANIZATION_SCOPED_RESOURCES:
        org_name = _preview_summary_field_name(item, "organization")
        if org_name:
            return (identifier, org_name)
    if canonical_type in PARENT_SCOPED_RESOURCES:
        parent_field = PARENT_SCOPED_RESOURCES[canonical_type]
        parent_name = _preview_summary_field_name(item, parent_field)
        if parent_name:
            if parent_field == "unified_job_template":
                parent_type = (
                    item.get("_ujt_resource_type")
                    or _preview_summary_field_value(item, parent_field, "unified_job_type")
                    or parent_field
                )
                return (identifier, f"{parent_type}:{parent_name}")
            return (identifier, parent_name)
    return identifier


@dataclass
class MigrationPreviewResult:
    resources: dict[str, list[dict]]
    resource_summaries: dict[str, dict]
    host_counts: dict[str, int]
    group_counts: dict[str, int]
    warnings: list[str]


# Built-in maintenance schedules — same list as ScheduleExporter.SYSTEM_SCHEDULES.
_SYSTEM_SCHEDULE_NAMES = frozenset({
    "Cleanup Job Schedule",
    "Cleanup Activity Schedule",
    "Cleanup Expired Sessions",
    "Cleanup Expired OAuth 2 Tokens",
    "Cleanup Orphaned OAuth 2 Tokens",
})


def _is_exportable_schedule(schedule_item: dict) -> bool:
    """Return True if preview should include this schedule.

    Mirrors ScheduleExporter._process_resource: system-job schedules and the
  built-in cleanup schedule names are never exported.
    """
    name = str(schedule_item.get("name", "")).strip()
    if name in _SYSTEM_SCHEDULE_NAMES:
        return False

    ujt_summary = (schedule_item.get("summary_fields") or {}).get("unified_job_template") or {}
    if ujt_summary.get("unified_job_type") == "system_job":
        return False

    # Export only requests enabled schedules.
    if schedule_item.get("enabled") is False:
        return False

    return True


async def run_migration_preview(
    source: Connection,
    dest: Connection,
    db_url: str,
    *,
    log: LogFn | None = None,
) -> MigrationPreviewResult:
    """Compare source and destination resources using CLI-equivalent type filters."""
    from aap_migration.api.services.connection_client import (
        create_connection_client,
        fetch_resources_with_client,
    )
    from aap_migration.client.exceptions import NotFoundError
    from aap_migration.config import normalized_credential_skip_names

    ctx = build_migration_context_pair(source, dest, db_url)
    skip_credential_names = normalized_credential_skip_names(
        ctx.config.export.skip_credential_names
    )
    resource_types = filtered_migration_resource_types()
    parallel_enabled = ctx.config.performance.parallel_resource_types
    max_concurrent = ctx.config.performance.max_concurrent_types

    if log:
        mode = "parallel" if parallel_enabled else "sequential"
        log(f"Previewing {len(resource_types)} resource types ({mode}, max {max_concurrent})")

    resources: dict[str, list[dict]] = {}
    resource_summaries: dict[str, dict] = {}
    host_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    warnings: list[str] = []

    src_client = create_connection_client(source)
    dst_client = create_connection_client(dest)
    semaphore = asyncio.Semaphore(max_concurrent)

    async def preview_resource_type(resource_type: str) -> None:
        canonical_type = normalize_resource_type(resource_type)
        try:
            if log:
                log(f"Fetching {resource_type} from source and destination...")
            src_items, dst_items = await asyncio.gather(
                fetch_resources_with_client(src_client, source, resource_type),
                fetch_resources_with_client(dst_client, dest, resource_type),
            )
        except NotFoundError as exc:
            warning = f"Skipping {resource_type}: {exc}"
            warnings.append(warning)
            if log:
                log(f"  {warning}")
            return

        if not src_items:
            return

        if resource_type == "credentials" and skip_credential_names:
            original_count = len(src_items)
            src_items = [
                item
                for item in src_items
                if str(item.get("name", "")).strip().casefold() not in skip_credential_names
            ]
            skipped_by_policy = original_count - len(src_items)
            if skipped_by_policy:
                warnings.append(
                    f"Excluded {skipped_by_policy} credentials based on export.skip_credential_names."
                )

        # Mirror export: skip built-in execution environments.
        if canonical_type == "execution_environments":
            skip_ee_names = {n.casefold() for n in DEFAULT_SKIP_EXECUTION_ENVIRONMENT_NAMES}
            original_count = len(src_items)
            src_items = [
                item
                for item in src_items
                if str(item.get("name", "")).strip().casefold() not in skip_ee_names
            ]
            if original_count - len(src_items):
                warnings.append(
                    f"Excluded {original_count - len(src_items)} built-in execution environments "
                    "(same as export)."
                )

        if not src_items:
            return

        # Filter source schedules tied to management/system job templates — these are built-in
        # AAP maintenance schedules. The destination Gateway API does not expose them through
        # the schedules endpoint, so they can never match and will always appear as "create".
        # We detect them by checking for the absence of a standard unified_job_template name
        # (management schedules have a different parent type not visible via the Gateway).
        if canonical_type == "schedules":
            original_count = len(src_items)
            src_items = [item for item in src_items if _is_exportable_schedule(item)]
            n_excluded = original_count - len(src_items)
            if n_excluded:
                warnings.append(
                    f"Excluded {n_excluded} system/maintenance schedules "
                    "(same rules as export)."
                )

        if not src_items:
            return

        if log:
            log(f"  Found {len(src_items)} {resource_type} on source")
            log(f"  Found {len(dst_items)} {resource_type} on destination")

        dst_keys = (
            set()
            if canonical_type == "credentials"
            else {_preview_match_key(resource_type, item) for item in dst_items}
        )
        # Fallback: match by name alone for parent-scoped resources (e.g. schedules) where
        # the destination API may return the parent with different metadata, causing the
        # composite key to miss even when the resource clearly already exists.
        dst_names_fallback = (
            {_preview_resource_identifier(resource_type, item) for item in dst_items}
            if canonical_type in PARENT_SCOPED_RESOURCES
            else set()
        )

        display_resources: list[dict] = []
        total_count = 0
        create_count = 0
        should_truncate = resource_type in PREVIEW_TRUNCATE_TYPES
        for item in src_items:
            item_key = _preview_match_key(resource_type, item)
            item_name = _preview_resource_identifier(resource_type, item)
            action = (
                "create"
                if canonical_type == "credentials"
                else "skip_exists"
                if item_key in dst_keys or item_name in dst_names_fallback
                else "create"
            )
            total_count += 1
            if action == "create":
                create_count += 1
            if not should_truncate or len(display_resources) < PREVIEW_DETAIL_LIMIT:
                display_resources.append(
                    {
                        "source_id": item.get("id", 0),
                        "name": _preview_resource_identifier(resource_type, item),
                        "type": resource_type,
                        "action": action,
                    }
                )

        if total_count:
            summary = {
                "total": total_count,
                "create": create_count,
                "skip_exists": total_count - create_count,
                "displayed": len(display_resources),
                "truncated": should_truncate and total_count > PREVIEW_DETAIL_LIMIT,
            }
            if summary["truncated"]:
                warnings.append(
                    f"{resource_type} preview is truncated to the first {PREVIEW_DETAIL_LIMIT} rows."
                )
            resources[resource_type] = display_resources
            resource_summaries[resource_type] = summary

        if resource_type == "inventories":
            for item in src_items:
                inv_name = item.get("name", "")
                host_counts[inv_name] = item.get("total_hosts", 0)
                group_counts[inv_name] = item.get("total_groups", 0)

    async def preview_with_limit(resource_type: str) -> None:
        if parallel_enabled:
            async with semaphore:
                await preview_resource_type(resource_type)
        else:
            await preview_resource_type(resource_type)

    try:
        await asyncio.gather(*(preview_with_limit(rt) for rt in resource_types))
    finally:
        await src_client.close()
        await dst_client.close()

    total_create = sum(1 for items in resources.values() for item in items if item["action"] == "create")
    total_skip = sum(1 for items in resources.values() for item in items if item["action"] != "create")
    if log:
        log(f"Preview complete: {total_create} to create, {total_skip} to skip")

    return MigrationPreviewResult(
        resources=resources,
        resource_summaries=resource_summaries,
        host_counts=host_counts,
        group_counts=group_counts,
        warnings=warnings,
    )


@dataclass
class CleanupWorkflowResult:
    deleted: int
    skipped: int
    errors: int
    cleared_progress: int = 0
    deleted_mappings: int = 0
    directories_removed: list[str] = field(default_factory=list)


def _clean_workflow_directories(ctx: MigrationContext, log: LogFn | None = None) -> list[str]:
    """Clear local export and transform directories, matching CLI cleanup.

    The directories themselves are preserved because they may be bind-mount
    points inside the container (rmtree on a mount point raises EBUSY).
    All contents are removed recursively instead.
    """
    directories = {
        "exports": Path(ctx.config.paths.export_dir),
        "xformed": Path(ctx.config.paths.transform_dir),
    }
    cleared: list[str] = []
    for label, path in directories.items():
        if not path.exists() or not path.is_dir():
            continue
        try:
            for child in path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            cleared.append(label)
            if log:
                log(f"Cleared {label} directory: {path}")
        except OSError as exc:
            if log:
                log(f"Failed to clear {label} directory {path}: {exc}")
    return cleared


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
    resource_results: list[tuple[str, int, int, int]] = []

    try:
        if log:
            log("Clearing migration state database tables...")
        cleared_progress, deleted_mappings = clear_database(str(ctx.config.state.db_path))
        if log:
            log(f"  ✓ {cleared_progress} progress records, {deleted_mappings} id mappings cleared")

        if log:
            log("Cancelling active jobs on target...")
        cancel_result = await cancel_all_jobs(client=target_client, config=ctx.config)
        cancelled = sum(v for v in cancel_result if isinstance(v, int))
        if log:
            log(f"  ✓ {cancelled} job(s) cancelled")

        resource_types = await get_cleanup_resource_types(target_client, use_discovered=True)
        if log:
            log(f"Deleting migrated resources ({len(resource_types)} types)...")

        for resource_type in resource_types:
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
                resource_results.append((resource_type, deleted, skipped, errors))
                if log:
                    ts = datetime.now(UTC).strftime("%H:%M:%S")
                    icon = "⚠" if errors else "✓"
                    name = resource_type.replace("_", " ").title()
                    log(
                        f"  [{ts}] {icon}  {name:<28}"
                        f"  deleted: {deleted:>5}  skipped: {skipped:>5}  errors: {errors:>3}"
                    )
            except Exception as exc:
                total_errors += 1
                resource_results.append((resource_type, 0, 0, 1))
                if log:
                    ts = datetime.now(UTC).strftime("%H:%M:%S")
                    name = resource_type.replace("_", " ").title()
                    log(f"  [{ts}] ✗  {name:<28}  error: {exc}")

        if log and resource_results:
            ts = datetime.now(UTC).strftime("%H:%M:%S")
            icon = "⚠" if total_errors else "✓"
            log(
                f"  [{ts}] {icon}  {'TOTAL':<28}"
                f"  deleted: {total_deleted:>5}  skipped: {total_skipped:>5}  errors: {total_errors:>3}"
            )

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
    skip_prep: bool | None = None,
) -> PhasedMigrationResult:
    """Run export → transform → import using the CLI migration workflow."""
    ctx = build_migration_context_pair(source, dest, db_url)
    if skip_prep is None:
        skip_prep = migration_schemas_exist(ctx)
    try:
        if not skip_prep and log:
            log("Running prep (endpoint discovery and schema generation)...")
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
    finally:
        await ctx.source_client.close()
        await ctx.target_client.close()


@contextmanager
def _web_progress_display(log: LogFn | None) -> Iterator[None]:
    """Route Rich progress panels to TUI-style log lines for Web UI jobs.

    The class is imported directly (``from ... import MigrationProgressDisplay``)
    in every module that uses it, so we must patch the name in each importer —
    patching only the source module has no effect on already-bound names.
    """
    from aap_migration.api.services import web_progress
    from aap_migration.reporting import live_progress

    def _factory(**kwargs) -> web_progress.LogMigrationProgressDisplay:
        return web_progress.LogMigrationProgressDisplay(
            log=log,
            enabled=kwargs.get("enabled", True),
            show_stats=kwargs.get("show_stats", False),
            title=kwargs.get("title", "AAP Migration Progress"),
        )

    # All modules that bind MigrationProgressDisplay at import time.
    import importlib
    _target_modules = [
        "aap_migration.reporting.live_progress",
        "aap_migration.reporting.progress_orchestrator",
        "aap_migration.cli.commands.export_import",
        "aap_migration.cli.commands.transform",
        "aap_migration.cli.commands.cleanup",
        "aap_migration.cli.commands.patch_projects",
        "aap_migration.migration.coordinator",
    ]
    originals: dict[str, object] = {}
    for mod_name in _target_modules:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "MigrationProgressDisplay"):
            originals[mod_name] = mod.MigrationProgressDisplay
            mod.MigrationProgressDisplay = _factory  # type: ignore[attr-defined]

    try:
        yield
    finally:
        for mod_name, original in originals.items():
            mod = importlib.import_module(mod_name)
            mod.MigrationProgressDisplay = original  # type: ignore[attr-defined]


def _run_export_command(
    ctx: MigrationContext,
    *,
    force: bool,
    resume: bool,
    log: LogFn | None,
) -> None:
    from aap_migration.cli.commands.export_import import export

    resource_types = filtered_migration_resource_types()
    export_ctx = click.Context(export)
    export_ctx.obj = ctx
    with _route_click_output_to_log(log), _web_progress_display(log):
        export_ctx.invoke(
            export,
            resource_type=tuple(resource_types),
            output=Path(ctx.config.paths.export_dir),
            force=force,
            records_per_file=ctx.config.export.records_per_file,
            resume=resume,
            yes=True,
        )


def _run_transform_command(
    ctx: MigrationContext,
    *,
    force: bool,
    log: LogFn | None,
) -> None:
    from aap_migration.cli.commands.transform import transform

    schema_file = schema_comparison_path(ctx)
    if not schema_file.exists():
        if log:
            log(f"  ⚠ Schema comparison file not found: {schema_file}")
            log("    Run '1. Prep Phase' first to enable schema-aware field filtering.")
            log("    Proceeding with resource-specific transformations only.")

    transform_ctx = click.Context(transform)
    transform_ctx.obj = ctx
    with _route_click_output_to_log(log), _web_progress_display(log):
        transform_ctx.invoke(
            transform,
            input_dir=Path(ctx.config.paths.export_dir),
            output_dir=Path(ctx.config.paths.transform_dir),
            schema_file=schema_file,
            force=force,
            resource_type=(),
            quiet=False,
            disable_progress=False,
            skip_pending_deletion=True,
            defer_project_sync=True,
            yes=True,
        )


def _run_import_command(
    ctx: MigrationContext,
    *,
    phase: str,
    force: bool,
    resume: bool,
    log: LogFn | None,
) -> None:
    from aap_migration.cli.commands.export_import import import_cmd

    import_ctx = click.Context(import_cmd)
    import_ctx.obj = ctx
    with _route_click_output_to_log(log), _web_progress_display(log):
        import_ctx.invoke(
            import_cmd,
            input_dir=Path(ctx.config.paths.transform_dir),
            resource_type=(),
            force=force,
            resume=resume,
            dry_run=False,
            skip_dependencies=False,
            check_dependencies=False,
            force_reimport=False,
            phase=phase,
            yes=True,
        )


async def _run_pair_command(
    source: Connection,
    dest: Connection,
    db_url: str,
    runner,
    *,
    log: LogFn | None = None,
    **kwargs,
) -> PhasedMigrationResult:
    ctx = build_migration_context_pair(source, dest, db_url)
    try:
        await asyncio.to_thread(runner, ctx, log=log, **kwargs)
        return PhasedMigrationResult(status="completed")
    except click.ClickException as exc:
        return PhasedMigrationResult(status="failed", message=str(exc))
    except Exception as exc:
        return PhasedMigrationResult(status="failed", message=str(exc))
    finally:
        # Clients may have been created inside the worker thread's event loop.
        # Closing them on the main loop can raise RuntimeError("Event loop is closed").
        # Swallow those errors — HTTP connection cleanup failures don't affect job outcome.
        for client in (ctx._source_client, ctx._target_client):
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass


async def run_migration_export(
    source: Connection,
    dest: Connection,
    db_url: str,
    *,
    log: LogFn | None = None,
    force: bool = False,
    resume: bool = False,
) -> PhasedMigrationResult:
    """Run CLI export (all) with parallel resource types when enabled in config."""
    return await _run_pair_command(
        source,
        dest,
        db_url,
        _run_export_command,
        log=log,
        force=force,
        resume=resume,
    )


async def run_migration_transform(
    source: Connection,
    dest: Connection,
    db_url: str,
    *,
    log: LogFn | None = None,
    force: bool = False,
) -> PhasedMigrationResult:
    """Run CLI transform (all) with parallel resource types when enabled in config."""
    return await _run_pair_command(
        source,
        dest,
        db_url,
        _run_transform_command,
        log=log,
        force=force,
    )


async def run_migration_import(
    source: Connection,
    dest: Connection,
    db_url: str,
    *,
    phase: str,
    log: LogFn | None = None,
    force: bool = False,
    resume: bool = False,
) -> PhasedMigrationResult:
    """Run CLI import for phase1 or phase2."""
    return await _run_pair_command(
        source,
        dest,
        db_url,
        _run_import_command,
        log=log,
        phase=phase,
        force=force,
        resume=resume,
    )


async def run_migration_cleanup(
    dest: Connection,
    db_url: str,
    *,
    log: LogFn | None = None,
) -> CleanupWorkflowResult:
    """Run CLI-equivalent cleanup on the destination connection."""
    return await run_connection_cleanup(dest, db_url, log=log)
