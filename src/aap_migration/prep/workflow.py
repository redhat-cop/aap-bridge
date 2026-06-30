"""Shared prep workflow for CLI and web API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aap_migration.cli.context import MigrationContext
from aap_migration.prep import (
    compare_schemas,
    discover_endpoints,
    generate_schema,
    save_comparison,
    save_endpoints,
    save_schema,
)
from aap_migration.resources import get_version_path
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)

LogFn = Callable[[str], None]


@dataclass
class PrepWorkflowResult:
    status: str
    message: str = ""
    output_dir: Path | None = None
    skipped: bool = False


def _log(log: LogFn | None, message: str) -> None:
    if log:
        log(message)


async def run_prep_workflow(
    ctx: MigrationContext,
    output_dir: Path,
    *,
    force: bool = False,
    skip_if_exists: bool = False,
    log: LogFn | None = None,
) -> PrepWorkflowResult:
    """Discover endpoints, generate schemas, and compare them."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source_endpoints_file = output_dir / "source_endpoints.json"
    target_endpoints_file = output_dir / "target_endpoints.json"

    if not force and source_endpoints_file.exists() and target_endpoints_file.exists():
        if skip_if_exists:
            _log(log, "Schema files already exist; skipping prep.")
            return PrepWorkflowResult(
                status="completed",
                output_dir=output_dir,
                skipped=True,
            )

    source_host = ctx.config.source.url.split("//")[-1].split("/")[0]
    target_host = ctx.config.target.url.split("//")[-1].split("/")[0]

    try:
        _log(log, f"Connecting to {source_host} and {target_host}...")
        await ctx.source_client.get("ping/")
        await ctx.target_client.get("ping/")

        _log(log, "Discovering and validating versions...")
        source_version = ctx.config.source.version or await ctx.source_client.get_version()
        target_version = ctx.config.target.version or await ctx.target_client.get_version()
        ctx.source_version = source_version
        ctx.target_version = target_version

        version_path = get_version_path(source_version, target_version)
        if version_path is None:
            if not force:
                message = f"Unsupported migration path: {source_version} → {target_version}"
                _log(log, message)
                return PrepWorkflowResult(status="failed", message=message, output_dir=output_dir)
            _log(
                log,
                f"Unknown migration path {source_version} → {target_version}; proceeding (--force).",
            )
        elif version_path.status == "partial":
            _log(log, f"⚠ Partial support for {source_version} → {target_version}")
            if version_path.notes:
                _log(log, f"  {version_path.notes}")
        else:
            _log(log, f"Migration path {source_version} → {target_version}: fully supported")
            if version_path.notes:
                _log(log, f"  {version_path.notes}")

        if version_path is not None and version_path.known_exceptions:
            _log(log, "Known exceptions for this migration path:")
            for exc in version_path.known_exceptions:
                _log(log, f"  ⚠ {exc}")

        common_ignored = ctx.config.ignored_endpoints.get("common", [])
        source_ignored = common_ignored + ctx.config.ignored_endpoints.get("source", [])
        target_ignored = common_ignored + ctx.config.ignored_endpoints.get("target", [])

        _log(log, "Discovering endpoints...")
        source_endpoints = await discover_endpoints(
            ctx.source_client,
            api_version=source_version,
            ignored_endpoints=source_ignored,
            instance="source",
        )
        target_endpoints = await discover_endpoints(
            ctx.target_client,
            api_version=target_version,
            ignored_endpoints=target_ignored,
            instance="target",
        )
        logger.info(
            "endpoints_discovered",
            source_count=len(source_endpoints["endpoints"]),
            target_count=len(target_endpoints["endpoints"]),
        )
        _log(
            log,
            f"Discovered {len(source_endpoints['endpoints'])} source and "
            f"{len(target_endpoints['endpoints'])} target endpoints",
        )

        save_endpoints(source_endpoints, source_endpoints_file)
        save_endpoints(target_endpoints, target_endpoints_file)

        _log(log, "Generating schemas...")
        source_schema = await generate_schema(ctx.source_client, source_endpoints)
        target_schema = await generate_schema(ctx.target_client, target_endpoints)
        logger.info(
            "schemas_generated",
            source_count=len(source_schema["schemas"]),
            target_count=len(target_schema["schemas"]),
        )

        source_schema_file = output_dir / "source_schema.json"
        target_schema_file = output_dir / "target_schema.json"
        save_schema(source_schema, source_schema_file)
        save_schema(target_schema, target_schema_file)

        _log(log, "Comparing schemas...")
        comparison = compare_schemas(source_schema, target_schema)

        comparison_file = output_dir / "schema_comparison.json"
        save_comparison(comparison, comparison_file)

        from aap_migration.schema.models import ComparisonResult
        from aap_migration.schema.persistence import save_schemas

        comparisons = {
            rtype: ComparisonResult.from_transformation_dict(
                resource_type=rtype,
                data=data,
                source_schema=source_schema["schemas"].get(rtype, {}),
                target_schema=target_schema["schemas"].get(rtype, {}),
            )
            for rtype, data in comparison["transformations"].items()
        }

        await save_schemas(
            source_schemas=source_schema["schemas"],
            target_schemas=target_schema["schemas"],
            comparisons=comparisons,
            output_dir=output_dir,
            source_url=ctx.config.source.url,
            target_url=ctx.config.target.url,
            source_version=source_version,
            target_version=target_version,
        )

        _log(log, f"Prep complete. Output: {output_dir}/")
        return PrepWorkflowResult(status="completed", output_dir=output_dir)
    except Exception as exc:
        logger.error("prep_failed", error=str(exc), exc_info=True)
        return PrepWorkflowResult(status="failed", message=str(exc), output_dir=output_dir)


def run_prep_workflow_sync(
    ctx: MigrationContext,
    output_dir: Path,
    *,
    force: bool = False,
    skip_if_exists: bool = False,
    log: LogFn | None = None,
) -> PrepWorkflowResult:
    """Run :func:`run_prep_workflow` from synchronous code."""
    try:
        return asyncio.run(
            run_prep_workflow(
                ctx,
                output_dir,
                force=force,
                skip_if_exists=skip_if_exists,
                log=log,
            )
        )
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            run_prep_workflow(
                ctx,
                output_dir,
                force=force,
                skip_if_exists=skip_if_exists,
                log=log,
            )
        )


def suppress_verbose_prep_logging() -> None:
    """Hide verbose API logs during prep unless DEBUG is explicitly enabled."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if handler.__class__.__name__ == "RichHandler":
            if handler.level == logging.INFO or handler.level == logging.NOTSET:
                handler.setLevel(logging.WARNING)
