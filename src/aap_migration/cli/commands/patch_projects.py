"""
Patch projects command (Phase 2).

This module provides the logic for Phase 2 of the migration:
Hydrating/patching projects that were imported as "Manual" with their original
SCM configuration in controlled batches to prevent controller resource exhaustion.
"""

import asyncio
import json
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import handle_errors, pass_context, requires_config
from aap_migration.cli.utils import (
    echo_error,
    echo_info,
    echo_success,
    echo_warning,
    step_progress,
)
from aap_migration.migration.importer import wait_for_project_sync
from aap_migration.reporting.live_progress import MigrationProgressDisplay
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


class ProjectSyncFailedError(Exception):
    """Raised when one or more projects fail to sync after all retries.

    Projects are hard dependencies of job templates and workflow job templates.
    Continuing the import after project sync failures would result in downstream
    errors for any resource that references those projects.
    """

    def __init__(self, failed_names: list[str]) -> None:
        self.failed_names = failed_names
        names_str = ", ".join(f'"{n}"' for n in failed_names)
        super().__init__(
            f"{len(failed_names)} project(s) failed to sync after all retries and "
            f"are required by downstream resources: {names_str}. "
            "Fix the SCM configuration on the target and re-run Phase 2."
        )


async def _retry_project_sync(
    ctx: MigrationContext,
    failed_ids: list[int],
    timeout: int,
    poll_interval: int,
) -> tuple[list[int], list[int]]:
    """Trigger a manual sync for failed projects and wait for completion.

    Args:
        ctx: Migration context (provides client and config)
        failed_ids: Target project IDs that previously failed
        timeout: Seconds to wait for sync completion
        poll_interval: Seconds between status polls

    Returns:
        Tuple of (still_failed_ids, recovered_ids)
    """
    triggered: list[int] = []
    for project_id in failed_ids:
        try:
            await ctx.target_client.post(f"projects/{project_id}/update/", json_data={})
            triggered.append(project_id)
            logger.info("project_sync_retry_triggered", project_id=project_id)
        except Exception as e:
            logger.warning(
                "project_sync_retry_trigger_failed",
                project_id=project_id,
                error=str(e),
            )

    if not triggered:
        return failed_ids, []

    _, retry_failed_count, retry_failed_ids = await wait_for_project_sync(
        client=ctx.target_client,
        project_ids=triggered,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    still_failed = retry_failed_ids
    recovered = [pid for pid in triggered if pid not in still_failed]
    return still_failed, recovered


async def patch_project_scm_details(
    ctx: MigrationContext,
    input_dir: Path,
    batch_size: int = 100,
    interval: int = 600,
    progress_display: MigrationProgressDisplay | None = None,
) -> None:
    """Execute Phase 2: Patch projects with SCM details.

    1. Reads transformed project files.
    2. Identifies projects with _deferred_scm_details.
    3. PATCHes them in batches.
    4. Waits for each batch to sync, retrying failed projects up to
       performance.project_sync_max_retries times.
    5. If projects still fail after all retries and
       performance.project_sync_fail_on_sync_failure is True, raises
       ProjectSyncFailedError to abort the import (projects are dependencies
       of job templates and workflows).

    Args:
        ctx: Migration context
        input_dir: Directory containing transformed project files
        batch_size: Number of projects to patch at once (default 100)
        interval: Seconds to sleep between batches (default 600)
        progress_display: Optional existing progress display to use
    """
    projects_dir = input_dir / "projects"
    if not projects_dir.exists():
        echo_warning("No projects directory found in transformed output. Skipping Phase 2.")
        return

    # Find all project files
    json_files = sorted(projects_dir.glob("projects_*.json"))
    if not json_files:
        echo_warning("No project files found. Skipping Phase 2.")
        return

    # Load all projects with deferred details
    projects_to_patch = []

    # If progress_display is active, suppress step_progress to avoid Live display conflicts
    scan_ctx = (
        step_progress("Scanning projects for deferred SCM details")
        if not progress_display
        else nullcontext()
    )

    with scan_ctx:
        for json_file in json_files:
            try:
                with open(json_file) as f:
                    resources = json.load(f)
                    for resource in resources:
                        if "_deferred_scm_details" in resource:
                            projects_to_patch.append(resource)
            except Exception as e:
                echo_error(f"Failed to load {json_file}: {e}")

    if not projects_to_patch:
        if not progress_display:
            echo_info("No projects found with deferred SCM details. Phase 2 not required.")
        return

    total_projects = len(projects_to_patch)
    max_retries = ctx.config.performance.project_sync_max_retries
    fail_on_failure = ctx.config.performance.project_sync_fail_on_sync_failure
    poll_interval = ctx.config.performance.project_sync_poll_interval

    if not progress_display:
        echo_info(f"Found {total_projects} projects requiring SCM activation.")
        echo_info(f"Starting Phase 2: Patching {batch_size} projects every {interval}s")

    # Define phases for progress display (matches Phase 3 pattern)
    # phases = [
    #     ("patching", "Patching Projects", total_projects),
    # ]

    # Use existing display or create new one
    progress_ctx: AbstractContextManager[MigrationProgressDisplay]
    if progress_display:
        progress_ctx = nullcontext(progress_display)
    else:
        progress_ctx = MigrationProgressDisplay(title="🔄 Phase 2: Project Patching", enabled=True)

    with progress_ctx as progress:
        # If new display, initialize layout
        if not progress_display:
            progress.set_total_phases(1)
            # Use specialized method for single-phase initialization to prevent artifacts
            progress.initialize_and_start_single_phase(
                "patching", "Patching Projects", total_projects
            )
        else:
            # If re-using existing display (e.g. from import all), use standard start
            progress.start_phase("patching", "Patching Projects", total_projects)

        patched_count = 0
        failed_patch_count = 0
        all_target_ids = []
        # Maps target_id → project name for human-readable error messages
        target_id_to_name: dict[int, str] = {}
        # Accumulates target IDs that failed sync across all batches after all retries
        permanently_failed_ids: list[int] = []

        # Process in batches
        for i in range(0, total_projects, batch_size):
            batch = projects_to_patch[i : i + batch_size]
            batch_target_ids = []

            # Patch this batch
            for project in batch:
                source_id = project.get("_source_id")
                name = project.get("name")
                deferred = project.get("_deferred_scm_details", {})

                # Get Target ID
                target_id = ctx.migration_state.get_mapped_id("projects", source_id)

                if not target_id:
                    logger.warning(
                        "project_patch_skipped_no_mapping",
                        source_id=source_id,
                        name=name,
                        message="Project not found in map (not imported?)",
                    )
                    failed_patch_count += 1
                    progress.update_phase("patching", patched_count, failed_patch_count)
                    continue

                try:
                    # Prepare PATCH payload
                    patch_data = {
                        "scm_type": deferred.get("scm_type"),
                        "scm_url": deferred.get("scm_url"),
                        "scm_branch": deferred.get("scm_branch", ""),
                        "scm_clean": deferred.get("scm_clean", False),
                        "scm_delete_on_update": deferred.get("scm_delete_on_update", False),
                        "scm_update_on_launch": deferred.get("scm_update_on_launch", False),
                        "scm_update_cache_timeout": deferred.get("scm_update_cache_timeout", 0),
                    }

                    # Resolve credential dependency
                    source_cred_id = deferred.get("credential")
                    if source_cred_id:
                        target_cred_id = ctx.migration_state.get_mapped_id(
                            "credentials", source_cred_id
                        )
                        if target_cred_id:
                            patch_data["credential"] = target_cred_id
                        else:
                            logger.warning(
                                "project_patch_credential_missing",
                                source_id=source_id,
                                credential_id=source_cred_id,
                                message="Credential not mapped",
                            )

                    # Perform PATCH
                    await ctx.target_client.patch(f"projects/{target_id}/", json_data=patch_data)

                    patched_count += 1
                    batch_target_ids.append(target_id)
                    all_target_ids.append(target_id)
                    target_id_to_name[target_id] = name or f"project_{target_id}"

                    logger.info(
                        "project_patched_scm",
                        source_id=source_id,
                        target_id=target_id,
                        name=name,
                    )

                except Exception as e:
                    failed_patch_count += 1
                    logger.error(
                        "project_patch_failed",
                        source_id=source_id,
                        target_id=target_id,
                        error=str(e),
                    )

                progress.update_phase("patching", patched_count, failed_patch_count)

            # After batch is patched, wait for SCM sync and retry failures
            if batch_target_ids:
                logger.info(
                    "phase2_batch_wait",
                    batch_size=len(batch_target_ids),
                    timeout=interval,
                    message=f"Waiting up to {interval}s for batch sync to complete.",
                )

                _, batch_failed_count, batch_failed_ids = await wait_for_project_sync(
                    client=ctx.target_client,
                    project_ids=batch_target_ids,
                    timeout=interval,
                    poll_interval=poll_interval,
                )

                batch_synced = len(batch_target_ids) - batch_failed_count
                logger.info(
                    "phase2_batch_complete",
                    synced=batch_synced,
                    failed=batch_failed_count,
                )

                # Retry failed syncs
                still_failed_ids = batch_failed_ids
                for attempt in range(1, max_retries + 1):
                    if not still_failed_ids:
                        break
                    failed_names = [
                        target_id_to_name.get(pid, str(pid)) for pid in still_failed_ids
                    ]
                    logger.warning(
                        "project_sync_retrying",
                        attempt=attempt,
                        max_retries=max_retries,
                        failed_count=len(still_failed_ids),
                        failed_names=failed_names,
                    )
                    still_failed_ids, recovered = await _retry_project_sync(
                        ctx=ctx,
                        failed_ids=still_failed_ids,
                        timeout=interval,
                        poll_interval=poll_interval,
                    )
                    if recovered:
                        logger.info(
                            "project_sync_retry_recovered",
                            attempt=attempt,
                            recovered_count=len(recovered),
                        )

                if still_failed_ids:
                    failed_names = [
                        target_id_to_name.get(pid, str(pid)) for pid in still_failed_ids
                    ]
                    logger.error(
                        "project_sync_permanently_failed",
                        failed_count=len(still_failed_ids),
                        failed_names=failed_names,
                        retries_attempted=max_retries,
                    )
                    permanently_failed_ids.extend(still_failed_ids)

                # Small delay before next batch to avoid overwhelming controller
                await asyncio.sleep(5)

        progress.complete_phase("patching")

        if patched_count > 0:
            if not progress_display:
                echo_success(f"Phase 2 Complete: {patched_count} projects patched.")
        else:
            if not progress_display:
                echo_warning("Phase 2 completed but no projects were patched.")

        # Abort if any projects permanently failed and fail_on_failure is set
        if permanently_failed_ids and fail_on_failure:
            failed_names = [
                target_id_to_name.get(pid, str(pid)) for pid in permanently_failed_ids
            ]
            echo_error(
                f"{len(permanently_failed_ids)} project(s) failed to sync after "
                f"{max_retries} retries. Aborting import — fix SCM configuration "
                "on the target and re-run Phase 2."
            )
            raise ProjectSyncFailedError(failed_names)
        elif permanently_failed_ids:
            failed_names = [
                target_id_to_name.get(pid, str(pid)) for pid in permanently_failed_ids
            ]
            echo_warning(
                f"{len(permanently_failed_ids)} project(s) failed to sync after "
                f"{max_retries} retries. Downstream resources that depend on these "
                "projects may fail to import."
            )


@click.command(name="patch-projects")
@click.option(
    "--input",
    "-i",
    "input_dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Input directory with transformed projects (default: xformed/)",
)
@click.option(
    "--batch-size",
    type=int,
    default=None,
    help="Number of projects to patch at once (default: from config)",
)
@click.option(
    "--interval",
    type=int,
    default=None,
    help="Seconds to wait between batches (default: from config)",
)
@pass_context
@requires_config
@handle_errors
def patch_projects(
    ctx: MigrationContext,
    input_dir: Path | None,
    batch_size: int | None,
    interval: int | None,
) -> None:
    """Execute Phase 2: Patch projects with SCM details.

    Hydrates projects that were imported as 'Manual' with their original
    SCM configuration. Runs in controlled batches to prevent controller overload.
    """
    if input_dir is None:
        input_dir = Path(ctx.config.paths.transform_dir)
    else:
        input_dir = Path(input_dir)

    # Use config values if not specified via CLI
    if batch_size is None:
        batch_size = ctx.config.performance.project_patch_batch_size
    if interval is None:
        interval = ctx.config.performance.project_patch_batch_interval

    async def run() -> None:
        await patch_project_scm_details(ctx, input_dir, batch_size, interval)

    try:
        asyncio.run(run())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run())
