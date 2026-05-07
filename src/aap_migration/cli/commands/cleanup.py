"""
Cleanup command to delete migrated resources and reset database.

This module provides cleanup operations for:
1. Deleting imported resources from target AAP
2. Clearing migration progress records
3. Resetting ID mappings
"""

import asyncio
from collections.abc import Callable

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import (
    handle_errors,
    pass_context,
    requires_config,
)
from aap_migration.cli.utils import (
    echo_info,
    echo_warning,
    format_count,
)
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.client.bulk_operations import BulkOperations
from aap_migration.client.exceptions import APIError, NotFoundError, PendingDeletionError, ResourceInUseError
from aap_migration.config import (
    MigrationConfig,
    normalized_credential_skip_names,
    normalized_execution_environment_skip_names,
)
from aap_migration.migration.database import get_session
from aap_migration.migration.models import IDMapping, MigrationProgress
from aap_migration.reporting.live_progress import MigrationProgressDisplay
from aap_migration.resources import CLEANUP_ORDER, get_endpoint
from aap_migration.utils.logging import get_logger
from aap_migration.utils.retry import retry_on_gateway_error

logger = get_logger(__name__)

# Resource types that don't support DELETE operations
NON_DELETABLE_RESOURCES = [
    "labels",  # Labels don't support DELETE via API (405 Method Not Allowed)
    "system_job_templates",  # System job templates are built-in and cannot be deleted
    "role_user_assignments",  # Assignments are removed when the role/user/resource is deleted
    "role_team_assignments",  # Assignments are removed when the role/team/resource is deleted
    "inventory_sources",  # Automatically removed when their parent inventory is deleted
    "groups",  # Automatically removed when their parent inventory is deleted
    "hosts",  # Automatically removed when their parent inventory is deleted
    "instances",  # Not managed by this tool; controller nodes must not be deleted
    "instance_groups",  # Not managed by this tool; must exist as a prerequisite on the target
    # Job history is preserved so there is a record of what occurred on the target
    "jobs",
    "workflow_jobs",
    "project_updates",
    "inventory_updates",
    "system_jobs",
    "ad_hoc_commands",
]


async def discover_target_resources(client: AAPTargetClient) -> list[str]:
    """Discover all available resource types from target AAP at runtime.

    Queries the API root endpoint which returns ALL available endpoints.
    Pattern matches prep/export dynamic discovery approach.

    Args:
        client: AAP target client

    Returns:
        List of discovered resource type names
    """
    logger.info("Discovering available resource types from target AAP...")

    # Query API root - returns {"organizations": "/api/v2/organizations/", ...}
    response = await client.get("")  # Empty endpoint = API root

    discovered_types = []
    metadata_fields = [
        "description",
        "current_version",
        "available_versions",
        "custom_logo",
        "custom_login_info",
    ]

    for endpoint_name in response.keys():
        # Skip metadata fields
        if endpoint_name in metadata_fields:
            continue
        discovered_types.append(endpoint_name)

    logger.info(f"Discovered {len(discovered_types)} resource types from target AAP")
    return discovered_types


def filter_cleanup_resources(discovered_types: list[str]) -> list[str]:
    """Filter discovered resources to those suitable for cleanup.

    Applies same logic as export command:
    - Skip read-only endpoints (ping, config, dashboard, metrics)
    - Skip runtime data endpoints (jobs, workflow_jobs, project_updates) - job history is preserved
    - Skip non-deletable resources (labels - API returns 405)
    - Skip manual migration endpoints (settings, roles)

    Args:
        discovered_types: List of all discovered resource types

    Returns:
        Filtered list of resource types suitable for cleanup
    """
    from aap_migration.resources import (
        ResourceCategory,
        get_resource_category,
    )

    filtered = []

    for rtype in discovered_types:
        category = get_resource_category(rtype)

        # Skip read-only/never migrate endpoints
        if category == ResourceCategory.NEVER_MIGRATE:
            logger.debug(f"Skipping excluded resource: {rtype}")
            continue

        # Skip non-deletable via API
        if rtype in NON_DELETABLE_RESOURCES:
            logger.debug(f"Skipping non-deletable resource: {rtype}")
            continue

        filtered.append(rtype)

    logger.info(
        f"Filtered to {len(filtered)} cleanable resource types "
        f"(skipped {len(discovered_types) - len(filtered)})"
    )
    return filtered


def sort_by_cleanup_order(resource_types: list[str]) -> list[str]:
    """Sort resources by cleanup_order (reverse dependency order).

    Resources with cleanup_order in RESOURCE_REGISTRY are sorted first.
    Unknown resources are appended at the end (delete last).

    Args:
        resource_types: List of resource types to sort

    Returns:
        Sorted list in cleanup order (dependents before parents)
    """
    from aap_migration.resources import RESOURCE_REGISTRY, normalize_resource_type

    known = []
    unknown = []

    for rtype in resource_types:
        # Normalize endpoint name to registry key (e.g., "inventory" → "inventories")
        normalized = normalize_resource_type(rtype)
        info = RESOURCE_REGISTRY.get(normalized)
        if info and hasattr(info, "cleanup_order"):
            known.append((rtype, info.cleanup_order))  # Keep original name for API calls
        else:
            unknown.append(rtype)

    # Sort known by cleanup_order (ascending = delete dependents first)
    known.sort(key=lambda x: x[1])
    sorted_types = [rtype for rtype, _ in known]

    # Append unknown at end (safest to delete last)
    sorted_types.extend(unknown)

    logger.debug(
        f"Sorted {len(sorted_types)} resource types by cleanup order "
        f"({len(known)} known, {len(unknown)} unknown)"
    )
    return sorted_types


async def get_cleanup_resource_types(
    client: AAPTargetClient, use_discovered: bool = True
) -> list[str]:
    """Get resource types for cleanup using hybrid discovery.

    Priority:
    1. target_endpoints.json (if prep was run)
    2. Runtime discovery (query API root)
    3. Fallback to static CLEANUP_ORDER

    Args:
        client: AAP target client
        use_discovered: If True, try dynamic discovery before static fallback

    Returns:
        List of resource types in cleanup order
    """
    from pathlib import Path

    if use_discovered:
        # Try loading from prep output
        target_file = Path("schemas/target_endpoints.json")
        if target_file.exists():
            logger.info("Using discovered endpoints from 'aap-bridge prep'")
            try:
                import json

                with open(target_file) as f:
                    data = json.load(f)
                discovered = list(data.get("endpoints", {}).keys())
                filtered = filter_cleanup_resources(discovered)
                return sort_by_cleanup_order(filtered)
            except Exception as e:
                logger.warning(f"Failed to load prep endpoints: {e}")

        # Runtime discovery
        try:
            discovered = await discover_target_resources(client)
            filtered = filter_cleanup_resources(discovered)
            return sort_by_cleanup_order(filtered)
        except Exception as e:
            logger.warning(f"Runtime discovery failed: {e}")
            logger.info("Falling back to static CLEANUP_ORDER")

    # Fallback to static order
    return CLEANUP_ORDER


async def fetch_all_resources_parallel(
    client: AAPTargetClient, endpoint: str, config: MigrationConfig
) -> list[dict]:
    """Fetch all resources with concurrent page fetching.

    Uses same pattern as exporter.py for high performance.
    Includes retry logic for Platform Gateway errors (502/503/504).

    Args:
        client: AAP client
        endpoint: Resource endpoint (e.g., "hosts/")
        config: Migration configuration with performance settings

    Returns:
        List of all resources

    Example:
        resources = await fetch_all_resources_parallel(client, "hosts/", config)
        # Fetches 270 pages concurrently instead of sequentially
    """
    # Get concurrency from config
    concurrency = config.performance.cleanup_page_fetch_concurrency
    page_size = config.performance.default_page_size

    # Create retry decorator with config values
    retry_decorator = retry_on_gateway_error(
        max_attempts=config.performance.gateway_error_retry_attempts,
        backoff_base=config.performance.gateway_error_backoff_base,
    )

    # Step 1: Get total count and first page
    first_page = await client.get(
        endpoint,
        params={
            "page_size": page_size,
            "page": 1,
        },
    )
    total_count = first_page.get("count", 0)
    total_pages = (total_count + page_size - 1) // page_size

    if total_pages <= 1:
        return first_page.get("results", [])

    logger.debug(
        f"Fetching {total_pages} pages concurrently (concurrency={concurrency}) "
        f"for {total_count} resources"
    )

    # Step 2: Fetch remaining pages concurrently
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_page(page_num: int) -> dict:
        async with semaphore:
            # Apply retry logic for gateway errors
            @retry_decorator
            async def _fetch():
                return await client.get(
                    endpoint,
                    params={
                        "page_size": page_size,
                        "page": page_num,
                    },
                )

            return await _fetch()

    # Fetch pages 2-N in parallel
    tasks = [fetch_page(p) for p in range(2, total_pages + 1)]
    results = await asyncio.gather(*tasks)

    # Combine all results
    all_resources = first_page.get("results", [])
    for result in results:
        all_resources.extend(result.get("results", []))

    logger.debug(f"Fetched {len(all_resources)} resources from {total_pages} pages")
    return all_resources


async def fetch_counts_parallel(
    client: AAPTargetClient, resource_types: list[str]
) -> dict[str, int]:
    """Fetch resource counts for all types concurrently.

    Args:
        client: AAP client
        resource_types: List of resource types to fetch counts for

    Returns:
        Dict mapping resource_type -> count

    Example:
        counts = await fetch_counts_parallel(client, ["hosts", "inventories"])
        # Returns {"hosts": 54000, "inventories": 1045}
    """

    async def get_count(rtype: str) -> tuple[str, int]:
        try:
            endpoint = get_endpoint(rtype)
            response = await client.get(endpoint, params={"page_size": 1, "page": 1})
            count = response.get("count", 0)
            return (rtype, count)
        except Exception as e:
            logger.warning(f"Failed to get count for {rtype}: {e}")
            return (rtype, 0)

    results = await asyncio.gather(*[get_count(rt) for rt in resource_types])
    return dict(results)


def is_method_not_allowed_error(error: Exception) -> bool:
    """Check if error is a 405 Method Not Allowed response.

    Some job types (project_updates, inventory_updates, system_jobs)
    do not support the /cancel/ endpoint and return 405.

    Args:
        error: Exception raised during cancel attempt

    Returns:
        True if error is a 405 Method Not Allowed error
    """
    error_str = str(error).lower()
    return "405" in error_str or ("method" in error_str and "not allowed" in error_str)


async def cancel_all_jobs(
    client: AAPTargetClient, config: MigrationConfig
) -> tuple[int, int, int, int, int]:
    """Cancel active running and pending jobs before cleanup.

    This prevents [409] Resource conflict errors when deleting projects/templates
    that have active jobs. Job history (completed, failed, cancelled records) is
    intentionally preserved so there is a record of what occurred.

    Attempts cancellation for all job types:
    - jobs (job template executions) - ✅ Supports /cancel/
    - workflow_jobs (workflow executions) - ✅ Supports /cancel/
    - project_updates (project SCM sync) - ❌ May not support /cancel/ (405 error)
    - inventory_updates (inventory source sync) - ❌ May not support /cancel/ (405 error)
    - system_jobs (system cleanup/management) - ❌ May not support /cancel/ (405 error)

    For jobs that cannot be cancelled (405 Method Not Allowed), the function waits
    for them to complete naturally using wait_for_jobs_to_finish().

    Cancellable jobs transition: running → canceling → canceled.
    Non-cancellable jobs must reach terminal status naturally: running → successful/failed/error.

    Wait behavior:
    - After cancellation attempts, polls job status every config.performance.cleanup_job_poll_interval seconds
    - Waits up to config.performance.cleanup_job_finish_timeout seconds (default: 300s = 5 minutes)
    - Logs warning if jobs still running after timeout

    Uses configurable concurrency to prevent Platform Gateway overload.

    Args:
        client: AAP target client
        config: Migration configuration with performance settings

    Returns:
        Tuple of (jobs, workflow_jobs, project_updates, inventory_updates, system_jobs) canceled counts
    """
    from aap_migration.client.exceptions import APIError
    from aap_migration.resources import JOB_ACTIVE_STATUSES, JOB_TERMINAL_STATUSES, JOB_TRANSIENT_STATUSES

    logger.info("Querying active jobs (will cancel running/pending)...")

    # Define all job types to query and cancel
    job_types = [
        ("jobs", "jobs"),
        ("workflow_jobs", "workflow jobs"),
        ("project_updates", "project updates"),
        ("inventory_updates", "inventory updates"),
        ("system_jobs", "system jobs"),
    ]

    canceled_counts = {}
    page_size = config.performance.default_page_size

    for endpoint, display_name in job_types:
        # Query only active jobs - we cancel running/pending ones and leave history intact
        all_jobs = []
        page = 1
        while True:
            try:
                response = await client.get(
                    f"{endpoint}/",
                    params={
                        "status__in": ",".join(JOB_ACTIVE_STATUSES + JOB_TRANSIENT_STATUSES),
                        "page_size": page_size,
                        "page": page,
                    },
                )
                jobs = response.get("results", [])
                all_jobs.extend(jobs)

                if not response.get("next"):
                    break
                page += 1
            except Exception as e:
                logger.warning(f"Failed to query {display_name}: {e}")
                break

        if not all_jobs:
            canceled_counts[endpoint] = 0
            logger.debug(f"No active {display_name} found")
            continue

        logger.info(f"Found {len(all_jobs)} active {display_name} (cancelling before cleanup)")

        # Cancel all jobs for this type CONCURRENTLY
        # Use config-driven concurrency to prevent Platform Gateway overload
        max_concurrent = config.performance.cleanup_job_cancel_concurrency
        semaphore = asyncio.Semaphore(max_concurrent)

        async def cancel_with_semaphore(
            job, semaphore=semaphore, display_name=display_name, endpoint=endpoint
        ):
            """Cancel a single job with proper error handling.

            Uses the new client.cancel_job() method which:
            - Checks status automatically
            - Verifies can_cancel field
            - Handles race conditions

            Skips jobs already in terminal status (successful, failed, error, canceled).
            """
            async with semaphore:
                job_id = job["id"]
                job_name = job.get("name", f"{display_name.title()}-{job_id}")
                job_status = job.get("status", "unknown")

                # Skip jobs already in terminal status - no need to cancel
                if job_status in JOB_TERMINAL_STATUSES:
                    logger.debug(
                        f"Skipping cancel for {display_name} {job_id} "
                        f"(already in terminal status: {job_status})"
                    )
                    return False  # Not cancelled, but not an error

                try:
                    # Use new cancel_job() method - handles status check internally
                    await client.cancel_job(job_id, endpoint_prefix=endpoint)
                    logger.debug(f"Cancelled {display_name}: {job_name} (id={job_id})")
                    return True
                except APIError as e:
                    # Distinguish 405 (not supported) from real errors
                    if hasattr(e, "status_code") and e.status_code == 405:
                        logger.debug(
                            f"{display_name.title()} {job_id} does not support cancel "
                            f"(405 Method Not Allowed)"
                        )
                    else:
                        logger.warning(
                            f"Failed to cancel {display_name} {job_id}: {e}",
                            error_type=type(e).__name__,
                            status_code=getattr(e, "status_code", None),
                        )
                    return False
                except Exception as e:
                    logger.warning(
                        f"Unexpected error canceling {display_name} {job_id}: {e}",
                        error_type=type(e).__name__,
                    )
                    return False

        # Cancel all jobs concurrently
        results = await asyncio.gather(*[cancel_with_semaphore(job) for job in all_jobs])
        canceled = sum(1 for r in results if r)

        canceled_counts[endpoint] = canceled
        if canceled > 0:
            logger.info(f"Canceled {canceled} {display_name}")

            # Wait for jobs to finish canceling
            timeout = config.performance.cleanup_job_finish_timeout
            finished, still_running = await wait_for_jobs_to_finish(
                client=client,
                job_type=endpoint,
                expected_count=canceled,
                timeout=timeout,
                poll_interval=config.performance.cleanup_job_poll_interval,
            )

            if still_running > 0:
                logger.warning(
                    f"{still_running} {display_name} still running after timeout", timeout=timeout
                )

        # Job history is intentionally preserved — jobs are not deleted after cancellation.

    # Calculate total
    total_canceled = sum(canceled_counts.values())

    if total_canceled == 0:
        logger.info(
            "No active jobs needed cancellation (all were in terminal status or none found)"
        )

    return (
        canceled_counts.get("jobs", 0),
        canceled_counts.get("workflow_jobs", 0),
        canceled_counts.get("project_updates", 0),
        canceled_counts.get("inventory_updates", 0),
        canceled_counts.get("system_jobs", 0),
    )


async def wait_for_jobs_to_finish(
    client: AAPTargetClient,
    job_type: str,
    expected_count: int,
    timeout: int = 300,
    poll_interval: int = 5,
) -> tuple[int, int]:
    """Wait for canceled jobs to reach terminal status.

    Polls job status every poll_interval seconds until all jobs
    are in terminal status (successful, failed, error, canceled)
    or timeout is reached.

    Args:
        client: AAP target client
        job_type: Job endpoint (e.g., "project_updates", "jobs")
        expected_count: Number of jobs we expect to finish
        timeout: Maximum wait time in seconds (default: 300)
        poll_interval: Seconds between status checks (default: 5)

    Returns:
        Tuple of (finished_count, still_running_count)
    """
    import time

    from aap_migration.resources import JOB_ACTIVE_STATUSES, JOB_TRANSIENT_STATUSES

    logger.info(f"Waiting for {expected_count} {job_type} to finish...")

    start_time = time.time()
    last_count = expected_count
    active_statuses = ",".join(JOB_ACTIVE_STATUSES + JOB_TRANSIENT_STATUSES)

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            logger.warning(
                f"Timeout waiting for {job_type} to finish",
                timeout=timeout,
                elapsed=int(elapsed),
                still_running=last_count,
            )
            break

        # Query jobs still in active/transient status (i.e. not yet finished)
        try:
            response = await client.get(
                f"{job_type}/",
                params={
                    "status__in": active_statuses,
                    "page_size": 200,
                },
            )
            running_jobs = response.get("results", [])
            running_count = len(running_jobs)

            if running_count == 0:
                logger.info(f"All {job_type} have finished")
                return (expected_count, 0)

            # Log progress if count changed
            if running_count != last_count:
                logger.info(
                    f"Still waiting for {running_count} {job_type} to finish", elapsed=int(elapsed)
                )
                last_count = running_count

        except Exception as e:
            logger.warning(f"Error checking {job_type} status: {e}")

        await asyncio.sleep(poll_interval)

    # Timeout reached - return best estimate
    return (expected_count - last_count, last_count)


async def delete_active_jobs(
    client: AAPTargetClient,
    job_type: str,
    jobs: list[dict],
    config: MigrationConfig,
) -> tuple[int, int]:
    """Delete jobs that couldn't be cancelled.

    Used as a fallback when jobs don't support cancellation (405 error)
    or when jobs are stuck and won't reach terminal status.

    Args:
        client: AAP target client
        job_type: Job endpoint (e.g., "project_updates", "jobs")
        jobs: List of job dictionaries to delete
        config: Migration configuration

    Returns:
        Tuple of (deleted_count, failed_count)
    """
    if not jobs:
        return (0, 0)

    logger.info(f"Deleting {len(jobs)} {job_type}...")

    deleted_count = 0
    failed_count = 0

    # Use concurrency from config
    max_concurrent = config.performance.cleanup_job_cancel_concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def delete_job(job: dict) -> bool:
        """Delete a single job."""
        async with semaphore:
            job_id = job["id"]
            try:
                await client.delete(f"{job_type}/{job_id}/")
                logger.debug(f"Deleted {job_type} {job_id}")
                return True
            except Exception as e:
                # 404 means already deleted - treat as success
                if "404" in str(e):
                    logger.debug(f"{job_type} {job_id} already deleted")
                    return True
                logger.warning(f"Failed to delete {job_type} {job_id}: {e}")
                return False

    results = await asyncio.gather(*[delete_job(job) for job in jobs])
    deleted_count = sum(1 for r in results if r)
    failed_count = len(jobs) - deleted_count

    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} {job_type}")
    if failed_count > 0:
        logger.warning(f"Failed to delete {failed_count} {job_type}")

    return (deleted_count, failed_count)


async def ensure_no_active_jobs(
    client: AAPTargetClient,
    config: MigrationConfig,
    cancel_timeout: int = 60,
    delete_if_stuck: bool = True,
) -> dict:
    """Ensure no active jobs exist before proceeding with import.

    Implements a 3-phase escalation strategy:
    1. Cancel: Attempt to cancel all active jobs
    2. Wait: Wait up to cancel_timeout seconds for jobs to reach terminal status
    3. Delete: If delete_if_stuck=True, delete jobs that won't finish

    This is required before import to prevent 409 Conflict errors when
    importing resources that may have associated running jobs.

    Args:
        client: AAP target client
        config: Migration configuration
        cancel_timeout: Seconds to wait for jobs to cancel (default: 60)
        delete_if_stuck: If True, delete jobs that won't cancel (default: True)

    Returns:
        Dictionary with summary:
        {
            "total_active": int,      # Jobs found initially
            "total_cancelled": int,   # Jobs successfully cancelled
            "total_deleted": int,     # Jobs deleted (fallback)
            "total_cleared": int,     # Total jobs cleared (cancelled + deleted)
            "still_running": int,     # Jobs still active (if delete_if_stuck=False)
            "by_type": {              # Breakdown by job type
                "jobs": {"found": N, "cancelled": N, "deleted": N},
                ...
            }
        }
    """
    from aap_migration.resources import (
        JOB_ACTIVE_STATUSES,
        JOB_DELETABLE_TYPES,
        JOB_TRANSIENT_STATUSES,
    )

    logger.info("Ensuring no active jobs exist before import...")

    summary = {
        "total_active": 0,
        "total_cancelled": 0,
        "total_deleted": 0,
        "total_cleared": 0,
        "still_running": 0,
        "by_type": {},
    }

    page_size = config.performance.default_page_size

    # Query all job types
    for job_type in JOB_DELETABLE_TYPES:
        type_summary = {"found": 0, "cancelled": 0, "deleted": 0}

        # Query active jobs (including those being cancelled)
        all_active_statuses = JOB_ACTIVE_STATUSES + JOB_TRANSIENT_STATUSES
        try:
            all_jobs = []
            page = 1
            while True:
                response = await client.get(
                    f"{job_type}/",
                    params={
                        "status__in": ",".join(all_active_statuses),
                        "page_size": page_size,
                        "page": page,
                    },
                )
                jobs = response.get("results", [])
                all_jobs.extend(jobs)
                if not response.get("next"):
                    break
                page += 1

            type_summary["found"] = len(all_jobs)
            summary["total_active"] += len(all_jobs)

            if not all_jobs:
                summary["by_type"][job_type] = type_summary
                continue

            logger.info(f"Found {len(all_jobs)} active {job_type}")

            # Phase 1: Attempt to cancel
            cancelled = 0
            for job in all_jobs:
                if job.get("status") in JOB_TRANSIENT_STATUSES:
                    # Already cancelling
                    continue
                try:
                    await client.cancel_job(job["id"], endpoint_prefix=job_type)
                    cancelled += 1
                except Exception as e:
                    # 405 = cancel not supported, will delete later
                    if "405" not in str(e):
                        logger.debug(f"Cancel failed for {job_type} {job['id']}: {e}")

            type_summary["cancelled"] = cancelled
            summary["total_cancelled"] += cancelled

            if cancelled > 0:
                logger.info(f"Cancelled {cancelled} {job_type}")

        except Exception as e:
            logger.warning(f"Failed to query {job_type}: {e}")
            summary["by_type"][job_type] = type_summary
            continue

        summary["by_type"][job_type] = type_summary

    # Phase 2: Wait for cancellation to complete
    if summary["total_cancelled"] > 0:
        logger.info(f"Waiting up to {cancel_timeout}s for jobs to finish cancelling...")

        import time

        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > cancel_timeout:
                logger.warning(f"Timeout waiting for jobs to cancel after {cancel_timeout}s")
                break

            # Count remaining active jobs
            total_remaining = 0
            for job_type in JOB_DELETABLE_TYPES:
                try:
                    response = await client.get(
                        f"{job_type}/",
                        params={
                            "status__in": ",".join(JOB_ACTIVE_STATUSES + JOB_TRANSIENT_STATUSES),
                            "page_size": 1,
                        },
                    )
                    total_remaining += response.get("count", 0)
                except Exception:
                    pass

            if total_remaining == 0:
                logger.info("All jobs have finished")
                break

            logger.debug(f"Still {total_remaining} jobs active, waiting...")
            await asyncio.sleep(5)

    # Phase 3: Delete stuck jobs (if enabled)
    if delete_if_stuck:
        for job_type in JOB_DELETABLE_TYPES:
            try:
                # Query remaining active jobs
                all_active_statuses = JOB_ACTIVE_STATUSES + JOB_TRANSIENT_STATUSES
                response = await client.get(
                    f"{job_type}/",
                    params={
                        "status__in": ",".join(all_active_statuses),
                        "page_size": page_size,
                    },
                )
                remaining_jobs = response.get("results", [])

                if remaining_jobs:
                    logger.info(f"Deleting {len(remaining_jobs)} stuck {job_type}...")
                    deleted, _ = await delete_active_jobs(client, job_type, remaining_jobs, config)
                    summary["by_type"][job_type]["deleted"] = deleted
                    summary["total_deleted"] += deleted

            except Exception as e:
                logger.warning(f"Failed to delete stuck {job_type}: {e}")

    # Calculate totals
    summary["total_cleared"] = summary["total_cancelled"] + summary["total_deleted"]

    # Count any remaining (if delete was disabled or failed)
    if not delete_if_stuck:
        for job_type in JOB_DELETABLE_TYPES:
            try:
                response = await client.get(
                    f"{job_type}/",
                    params={
                        "status__in": ",".join(JOB_ACTIVE_STATUSES + JOB_TRANSIENT_STATUSES),
                        "page_size": 1,
                    },
                )
                summary["still_running"] += response.get("count", 0)
            except Exception:
                pass

    logger.info(
        f"Job cleanup complete: {summary['total_active']} found, "
        f"{summary['total_cancelled']} cancelled, {summary['total_deleted']} deleted"
    )

    return summary


async def delete_resource_with_retry(
    client: AAPTargetClient,
    endpoint: str,
    resource_id: int,
    resource_name: str,
    max_retries: int = 2,
    retry_delay: int = 30,
) -> None:
    """Delete resource with retry logic for ResourceInUseError.

    If resource is blocked by active jobs (409 error), waits and retries
    up to max_retries times before raising exception.

    Args:
        client: AAP target client
        endpoint: Resource endpoint (e.g., "hosts")
        resource_id: Resource ID
        resource_name: Resource name (for logging)
        max_retries: Maximum retry attempts (default: 2)
        retry_delay: Delay between retries in seconds (default: 30)

    Raises:
        ResourceInUseError: Resource blocked by jobs after all retries
        PendingDeletionError: Resource already being deleted (idempotent)
        Other exceptions: Propagated unchanged
    """
    from aap_migration.client.exceptions import ConflictError

    for attempt in range(max_retries + 1):
        try:
            await client.delete_resource(endpoint.rstrip("/"), resource_id)
            return  # Success

        except PendingDeletionError:
            # Resource already being deleted - this is idempotent success
            raise

        except ResourceInUseError as e:
            # Resource blocked by active jobs
            if attempt < max_retries:
                logger.warning(
                    f"Resource {resource_name} (id={resource_id}) blocked by jobs, retrying...",
                    resource_type=endpoint,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    active_jobs_count=len(e.active_jobs) if hasattr(e, "active_jobs") else 0,
                )
                await asyncio.sleep(retry_delay)
                continue  # Retry
            else:
                # Max retries exceeded - re-raise
                logger.error(
                    f"Resource {resource_name} still blocked after {max_retries} retries",
                    resource_type=endpoint,
                    resource_id=resource_id,
                    active_jobs_count=len(e.active_jobs) if hasattr(e, "active_jobs") else 0,
                )
                raise

        except ConflictError as e:
            # Other conflict errors (not ResourceInUseError)
            error_str = str(e).lower()
            if "running jobs" in error_str or "being used" in error_str:
                # This is a ResourceInUseError that wasn't properly typed
                # Extract active jobs from error if possible
                active_jobs = []
                if hasattr(e, "response") and e.response:
                    active_jobs = e.response.get("active_jobs", [])

                if attempt < max_retries:
                    logger.warning(
                        f"Resource {resource_name} blocked by jobs, retrying...",
                        resource_type=endpoint,
                        resource_id=resource_id,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    # Convert to ResourceInUseError for better handling
                    raise ResourceInUseError(
                        f"Resource {endpoint} {resource_id} blocked by active jobs "
                        f"after {max_retries} retries",
                        status_code=409,
                        response=e.response if hasattr(e, "response") else None,
                        active_jobs=active_jobs,
                    ) from e
            else:
                # Different type of conflict - don't retry
                raise


async def delete_resources_parallel(
    client: AAPTargetClient,
    endpoint: str,
    resources_to_delete: list[dict],
    config: MigrationConfig,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> tuple[int, int, int, list[tuple[int, str, str]]]:
    """Delete resources concurrently with live progress updates.

    Includes retry logic for Platform Gateway errors (502/503/504) and
    retry logic for ResourceInUseError (jobs blocking deletion).

    Args:
        client: AAP target client
        endpoint: Resource endpoint (e.g., "hosts")
        resources_to_delete: List of resources to delete [{id, name}, ...]
        config: Migration configuration with performance settings
        progress_callback: Optional callback(deleted, skipped, errors) for progress updates

    Returns:
        Tuple of (deleted_count, skipped_count, error_count, failed_resources)
    """
    deleted_count = 0
    skipped_count = 0
    error_count = 0
    failed_resources: list[tuple[int, str, str]] = []

    # Get concurrency from config
    max_concurrent = config.performance.cleanup_max_concurrent

    # Semaphore to limit concurrent deletions
    semaphore = asyncio.Semaphore(max_concurrent)

    async def delete_with_semaphore(res_data: dict) -> None:
        """Delete a single resource with concurrency control and retry logic."""
        nonlocal deleted_count, error_count, skipped_count

        async with semaphore:
            res_id = res_data["id"]
            res_name = res_data["name"]

            try:
                logger.debug(f"Deleting {endpoint}: {res_name} (id={res_id})")

                # Use delete_resource_with_retry for ResourceInUseError retry logic
                await delete_resource_with_retry(
                    client=client,
                    endpoint=endpoint,
                    resource_id=res_id,
                    resource_name=res_name,
                    max_retries=2,
                    retry_delay=30,
                )
                deleted_count += 1

            except PendingDeletionError:
                # Resource already being deleted - this is success (idempotent)
                logger.info(
                    f"Skipped {res_name} (already pending deletion)",
                    resource_id=res_id,
                    resource_type=endpoint,
                )
                skipped_count += 1

            except NotFoundError:
                # Resource already deleted (e.g., cascade-deleted by parent)
                logger.debug(
                    f"Skipped {res_name} (already deleted / not found)",
                    resource_id=res_id,
                    resource_type=endpoint,
                )
                deleted_count += 1  # Count as success - goal achieved

            except APIError as e:
                # Some role_definitions are system-managed and return 400 on DELETE
                if e.status_code == 400 and "managed by the system" in str(e).lower():
                    logger.debug(
                        f"Skipped {res_name} (system-managed, cannot be deleted)",
                        resource_id=res_id,
                        resource_type=endpoint,
                    )
                    skipped_count += 1
                else:
                    raise

            except ResourceInUseError as e:
                # Resource blocked by jobs even after retries - log details
                active_jobs = e.active_jobs if hasattr(e, "active_jobs") else []

                if active_jobs:
                    job_details = ", ".join(
                        f"{j.get('type', 'unknown')}:{j.get('id')} ({j.get('status', 'unknown')})"
                        for j in active_jobs
                    )
                    logger.error(
                        f"Failed to delete {res_name} after retries: "
                        f"blocked by jobs: {job_details}",
                        resource_id=res_id,
                        resource_type=endpoint,
                        active_jobs=active_jobs,
                    )
                else:
                    logger.error(
                        f"Failed to delete {res_name} after retries: {e}",
                        resource_id=res_id,
                        resource_type=endpoint,
                    )

                error_count += 1
                failed_resources.append((res_id, res_name, str(e)))

            except Exception as e:
                logger.error(
                    f"Failed to delete {res_name}: {e}", resource_id=res_id, resource_type=endpoint
                )
                error_count += 1
                failed_resources.append((res_id, res_name, str(e)))

            # Progress update after each deletion
            if progress_callback:
                progress_callback(deleted_count, skipped_count, error_count)

    # Delete all resources concurrently (limited by semaphore)
    tasks = [delete_with_semaphore(res_data) for res_data in resources_to_delete]
    await asyncio.gather(*tasks, return_exceptions=True)

    return deleted_count, skipped_count, error_count, failed_resources


async def delete_resources(
    client: AAPTargetClient,
    resource_type: str,
    config: MigrationConfig,
    skip_default: bool = True,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> tuple[int, int, int, list[tuple[int, str, str]]]:
    """Delete resources of a specific type from AAP 2.6.

    Resources are deleted concurrently with live progress updates.
    Rate limiting is handled by the client (configurable via --rate-limit).

    Args:
        client: AAP target client
        resource_type: Type of resource to delete
        config: Migration configuration with performance settings
        skip_default: If True, skip built-in/system resources
        progress_callback: Optional callback(deleted, skipped, errors) for progress updates

    Returns:
        Tuple of (deleted_count, skipped_count, error_count, failed_resources)
        where failed_resources is list of (id, name, error_message) tuples
    """
    # Skip resources that don't support DELETE operations
    if resource_type in NON_DELETABLE_RESOURCES:
        logger.info(f"Skipping {resource_type} (DELETE not supported via API)")
        return 0, 0, 0, []

    logger.info(f"Fetching {resource_type} from AAP 2.6...")

    try:
        # Use correct endpoint from resource registry (e.g., "groups/" for "inventory_groups")
        endpoint = get_endpoint(resource_type)

        # Fetch ALL resources with concurrent page fetching (8-10x faster)
        all_resources = await fetch_all_resources_parallel(client, endpoint, config)

        if not all_resources:
            logger.info(f"No {resource_type} found")
            return 0, 0, 0, []

        logger.info(f"Found {len(all_resources)} {resource_type}")

        deleted_count = 0
        skipped_count = 0
        error_count = 0
        failed_resources: list[tuple[int, str, str]] = []

        ee_skip_names = normalized_execution_environment_skip_names(
            config.export.skip_execution_environment_names
        )
        cred_skip_names = normalized_credential_skip_names(
            config.export.skip_credential_names
        )

        # Filter resources to determine what to skip vs delete
        resources_to_delete = []

        for resource in all_resources:
            resource_id = resource["id"]
            resource_name = resource.get("name", f"ID-{resource_id}")
            resource_username = resource.get("username", "")
            is_managed = resource.get("managed", False)

            # Skip built-in/system resources if skip_default is True
            skip_resource = False
            skip_reason = ""

            # Execution environments: always respect both skip-name list and managed flag,
            # regardless of --full / skip_default.  The managed flag covers platform EEs like
            # "Control Plane Execution Environment"; the name list covers non-managed defaults
            # like "Default execution environment" that ship with AAP but aren't marked managed.
            if resource_type == "execution_environments":
                if ee_skip_names:
                    rn = resource.get("name")
                    if rn and isinstance(rn, str) and rn.strip().casefold() in ee_skip_names:
                        skip_resource = True
                        skip_reason = "export.skip_execution_environment_names"
                if not skip_resource and is_managed:
                    skip_resource = True
                    skip_reason = "managed execution environment"

            # Credentials: always respect the skip-name list regardless of --full / skip_default.
            # These are installer-created defaults that should not be deleted from the target.
            if resource_type == "credentials" and cred_skip_names:
                rn = resource.get("name")
                if rn and isinstance(rn, str) and rn.strip().casefold() in cred_skip_names:
                    skip_resource = True
                    skip_reason = "export.skip_credential_names"

            if skip_default:
                # Skip Default organization (by name or by ID=1)
                if resource_type == "organizations" and (
                    resource_name == "Default" or resource_id == 1
                ):
                    skip_resource = True
                    skip_reason = "built-in organization"

                # Skip only the 'admin' user (default AAP admin), system auditors, and system accounts
                # Note: Other superusers (System Administrators) CAN be deleted
                elif resource_type == "users" and (
                    resource_username == "admin"  # Only protect the default admin user
                    or resource.get("is_system_auditor", False)
                    or resource_username.startswith("_")  # System accounts
                ):
                    skip_resource = True
                    skip_reason = "admin/system user"

                # Skip managed credential types (built-in types like Machine, Source Control, etc.)
                elif resource_type == "credential_types" and is_managed:
                    skip_resource = True
                    skip_reason = "managed credential type"

                # Skip managed credentials (like Ansible Galaxy)
                elif resource_type == "credentials" and is_managed:
                    skip_resource = True
                    skip_reason = "managed credential"

                # execution_environments handled unconditionally above

                # Skip managed instance groups (like controlplane)
                elif resource_type == "instance_groups" and (
                    is_managed
                    or resource_name in ("default", "controlplane")
                    or resource_id in (1, 2)
                ):
                    skip_resource = True
                    skip_reason = "managed/system instance group"

                # Skip managed/system instances (like localhost, controlplane nodes)
                elif resource_type == "instances" and (
                    is_managed or resource_name in ("localhost", "controlplane") or resource_id == 1
                ):
                    skip_resource = True
                    skip_reason = "managed/system instance"

                # Skip schedules that belong to system jobs (built-in maintenance tasks)
                elif resource_type == "schedules":
                    ujt_summary = (resource.get("summary_fields") or {}).get(
                        "unified_job_template"
                    ) or {}
                    if ujt_summary.get("unified_job_type") == "system_job":
                        skip_resource = True
                        skip_reason = "system_job schedule"

            if skip_resource:
                logger.debug(f"Skipping {skip_reason}: {resource_name} (id={resource_id})")
                skipped_count += 1
                if progress_callback:
                    progress_callback(deleted_count, skipped_count, error_count)
                continue

            # Add to deletion list
            resources_to_delete.append(
                {
                    "id": resource_id,
                    "name": resource_name,
                }
            )

        # Delete resources concurrently with live progress updates
        max_concurrent = config.performance.cleanup_max_concurrent

        # Use bulk delete API for hosts (90-270x faster than individual deletes)
        if resource_type == "hosts" and len(resources_to_delete) > 0:
            logger.info(
                f"Using BULK DELETE API for {len(resources_to_delete)} hosts (batch_size=1000)..."
            )

            # Extract host IDs for bulk delete
            host_ids = [r["id"] for r in resources_to_delete]

            # Create BulkOperations instance
            bulk_ops = BulkOperations(client, config.performance)

            # Create progress callback wrapper for bulk delete
            def bulk_progress_cb(bulk_deleted: int, bulk_failed: int) -> None:
                """Update progress from bulk delete operation."""
                if progress_callback:
                    # Map bulk delete progress to expected callback signature
                    # (deleted, skipped, errors)
                    progress_callback(bulk_deleted, skipped_count, bulk_failed)

            # Use bulk delete with batching
            result = await bulk_ops.bulk_delete_hosts_batched(
                all_host_ids=host_ids,
                batch_size=config.performance.host_cleanup_batch_size,
                progress_callback=bulk_progress_cb,
            )

            deleted_count = result["total_deleted"]
            error_count = result["total_failed"]

            # For bulk delete, we don't have individual failure details
            if error_count > 0:
                failed_resources.append(
                    (0, f"{error_count} hosts", f"Bulk delete failed for {error_count} hosts")
                )

            logger.info(f"Bulk deleted {deleted_count} hosts, {error_count} failed")

        else:
            # Standard concurrent deletion for other resource types
            logger.info(
                f"Deleting {len(resources_to_delete)} {resource_type} concurrently "
                f"(max_concurrent={max_concurrent})..."
            )

            # Wrap the callback so the pre-filter skipped_count is always included.
            # delete_resources_parallel tracks its own local skipped (PendingDeletionError)
            # starting from 0, which would reset the live display's Skip counter.
            if progress_callback and skipped_count > 0:
                _pre_skipped = skipped_count

                def _parallel_cb(del_cnt: int, skip_cnt: int, err_cnt: int) -> None:
                    progress_callback(del_cnt, _pre_skipped + skip_cnt, err_cnt)

                parallel_callback: Callable[[int, int, int], None] | None = _parallel_cb
            else:
                parallel_callback = progress_callback

            deleted, _, errors, failed = await delete_resources_parallel(
                client,
                endpoint,
                resources_to_delete,
                config,
                progress_callback=parallel_callback,
            )

            deleted_count = deleted
            error_count = errors
            failed_resources = failed

        logger.info(
            f"Deleted {deleted_count} {resource_type}, skipped {skipped_count}, errors {error_count}"
        )
        return deleted_count, skipped_count, error_count, failed_resources

    except Exception as e:
        logger.error(f"Failed to fetch/delete {resource_type}: {e}")
        return 0, 0, 0, []


def clear_database(database_url: str) -> tuple[int, int]:
    """Clear migration database tables.

    Args:
        database_url: Database connection URL

    Returns:
        Tuple of (cleared_progress_count, deleted_mappings_count)
    """
    logger.info("Clearing database tables...")

    with get_session(database_url) as session:
        # Clear migration_progress
        deleted_progress = session.query(MigrationProgress).delete()
        logger.info(f"Deleted {deleted_progress} records from migration_progress")

        # Delete id_mappings (allow fresh export without resume conflicts)
        deleted_mappings = session.query(IDMapping).delete()
        logger.info(f"Deleted {deleted_mappings} records from id_mappings")

        session.commit()

    logger.info("Database cleanup complete")
    return deleted_progress, deleted_mappings


@click.command(name="cleanup")
@click.option(
    "-r",
    "--resource-type",
    multiple=True,
    type=str,
    help="Specific resource types to delete (default: discover all)",
)
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Delete all resources including Default org and admin users",
)
@click.option(
    "--db-only",
    is_flag=True,
    default=False,
    help="Only clear database, don't delete from AAP 2.6",
)
@click.option(
    "--exports-dir",
    type=click.Path(exists=False),
    default=None,
    help="Exports directory to clean up (default: exports/)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt (alias for --yes)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt",
)
@click.option(
    "--rate-limit",
    type=int,
    default=None,
    help="API request rate limit in requests/second (default: 100)",
)
@click.option(
    "--skip-dir",
    multiple=True,
    type=click.Choice(["exports", "xformed"], case_sensitive=False),
    help="Skip deletion of specific directories (can be used multiple times)",
)
@pass_context
@requires_config
@handle_errors
def cleanup(
    ctx: MigrationContext,
    resource_type: tuple[str, ...],
    full: bool,
    db_only: bool,
    exports_dir: str | None,
    force: bool,
    yes: bool,
    rate_limit: int | None,
    skip_dir: tuple[str, ...],
) -> None:
    """Clean up migrated resources from AAP 2.6 and reset database.

    This command will:
    1. Delete imported resources from AAP 2.6 (in reverse dependency order)
    2. Clear migration_progress table
    3. Delete id_mappings (clear all export/import tracking)
    4. Clean up exports and xformed directories (unless skipped)

    Resources are deleted in reverse dependency order to avoid FK conflicts.
    By default, deletions are performed in parallel with concurrency=50.

    Examples:

        # Clean up all resources and both directories (default)
        aap-bridge cleanup

        # Clean up but keep exports directory
        aap-bridge cleanup --skip-dir exports

        # Clean up but keep xformed directory
        aap-bridge cleanup --skip-dir xformed

        # Clean up but keep both directories
        aap-bridge cleanup --skip-dir exports --skip-dir xformed

        # Clean up specific resource types
        aap-bridge cleanup -r hosts -r inventories

        # Only clear database (don't delete from AAP or directories)
        aap-bridge cleanup --db-only

        # Delete everything including Default org (use with caution!)
        aap-bridge cleanup --full

        # Skip confirmation prompt
        aap-bridge cleanup -y

        # Custom exports directory location
        aap-bridge cleanup --exports-dir /tmp/exports

        # Custom rate limit
        aap-bridge cleanup --rate-limit 50
    """
    from pathlib import Path

    # Note: We'll determine resource_types dynamically inside run_cleanup()
    # because discovery requires async API calls

    # Use defaults from config if not provided
    if exports_dir is None:
        exports_dir = str(ctx.config.paths.export_dir)

    if rate_limit is None:
        rate_limit = ctx.config.performance.rate_limit

    # Determine which directories will be cleaned
    dirs_to_clean = []
    if "exports" not in skip_dir:
        if Path(exports_dir).exists():
            dirs_to_clean.append(f"exports ({exports_dir})")
    if "xformed" not in skip_dir:
        if Path("xformed").exists():
            dirs_to_clean.append("xformed")

    # Log cleanup operation details to file only (use debug to avoid console output)
    logger.debug(
        "cleanup_operation_planned",
        db_only=db_only,
        resource_types=list(resource_type) if resource_type else "all",
        full=full,
        dirs_to_clean=dirs_to_clean,
        skip_dirs=list(skip_dir) if skip_dir else [],
        rate_limit=rate_limit,
        max_concurrent=50,
    )

    # --force is alias for --yes
    skip_confirmation = force or yes
    if not skip_confirmation:
        if not click.confirm("Are you sure you want to proceed?", default=False):
            echo_info("Cleanup cancelled")
            return

    click.echo()

    async def run_cleanup() -> None:
        """Execute cleanup operations."""
        import logging

        # Suppress console logging for cleaner output
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        for handler in root_logger.handlers[:]:
            if hasattr(handler, "__class__") and "RichHandler" in handler.__class__.__name__:
                root_logger.removeHandler(handler)

        # Create target client with custom rate limit
        cleanup_client = AAPTargetClient(
            config=ctx.config.target,
            rate_limit=rate_limit,  # Use user-specified rate limit
        )

        try:
            total_deleted = 0
            total_skipped = 0
            total_errors = 0

            # Clear database first (log to file only)
            database_url = str(ctx.config.state.db_path)
            cleared_progress, deleted_mappings = clear_database(database_url)
            logger.info(
                "database_cleared",
                progress_records=cleared_progress,
                mappings_deleted=deleted_mappings,
            )

            if not db_only:
                # Cancel all running/pending jobs BEFORE cleanup (log to file only)
                (
                    canceled_jobs,
                    canceled_wf_jobs,
                    canceled_proj_updates,
                    canceled_inv_updates,
                    canceled_sys_jobs,
                ) = await cancel_all_jobs(cleanup_client, ctx.config)

                total_canceled = (
                    canceled_jobs
                    + canceled_wf_jobs
                    + canceled_proj_updates
                    + canceled_inv_updates
                    + canceled_sys_jobs
                )

                logger.info(
                    "jobs_canceled",
                    total=total_canceled,
                    jobs=canceled_jobs,
                    workflow_jobs=canceled_wf_jobs,
                    project_updates=canceled_proj_updates,
                    inventory_updates=canceled_inv_updates,
                    system_jobs=canceled_sys_jobs,
                )

                # Determine resource types using dynamic discovery
                if resource_type:
                    # User specified types - but STILL sort by cleanup_order
                    # to ensure dependencies are respected
                    user_order = list(resource_type)
                    resource_types = sort_by_cleanup_order(user_order)

                    # Log if order was changed
                    if user_order != resource_types:
                        logger.info(
                            "resource_types_reordered",
                            user_order=user_order,
                            sorted_order=resource_types,
                        )

                    logger.info("using_specified_resource_types", count=len(resource_types))
                else:
                    # Dynamic discovery
                    resource_types = await get_cleanup_resource_types(
                        cleanup_client, use_discovered=True
                    )
                    logger.info("discovered_resource_types", count=len(resource_types))

                logger.info("cleanup_starting", resource_type_count=len(resource_types))

                # Step 1: Pre-fetch counts for all resource types in parallel (16x faster)

                # Filter out non-deletable resources before fetching counts
                cleanable_types = [rt for rt in resource_types if rt not in NON_DELETABLE_RESOURCES]

                # Fetch all counts concurrently
                counts = await fetch_counts_parallel(cleanup_client, cleanable_types)

                # Build phases list
                from aap_migration.resources import get_description, normalize_resource_type

                phases = []
                for rtype in cleanable_types:
                    # Normalize endpoint name to resource type (e.g., "inventory" → "inventories")
                    normalized_type = normalize_resource_type(rtype)

                    # Try to get description from RESOURCE_REGISTRY
                    try:
                        description = get_description(normalized_type)
                    except KeyError:
                        # Fallback for unknown types not in registry
                        description = rtype.replace("_", " ").title()

                    count = counts.get(rtype, 0)
                    phases.append((rtype, description, count))
                    logger.debug(f"Found {count} {rtype}")

                # Filter out resources with 0 count - no value showing empty phases
                phases = [(rtype, desc, count) for rtype, desc, count in phases if count > 0]

                all_failed_resources: list[tuple[str, int, str, str]] = []

                logger.info(
                    "deletion_mode",
                    mode="concurrent",
                    max_concurrent=50,
                    rate_limit=rate_limit,
                )

                # Helper function to create progress callback for live updates
                def create_progress_callback(
                    progress_display: MigrationProgressDisplay, resource_type: str
                ):
                    """Create a callback that updates progress after each deletion.

                    Args:
                        progress_display: The MigrationProgressDisplay instance
                        resource_type: The resource type being deleted

                    Returns:
                        Callback function with signature (deleted, skipped, errors) -> None
                    """

                    def callback(deleted: int, skipped: int, errors: int) -> None:
                        """Update progress after each resource deletion.

                        Args:
                            deleted: Total count of deleted resources so far
                            skipped: Total count of skipped resources so far
                            errors: Total count of failed deletions so far
                        """
                        # Update the phase with current progress
                        # Pass completed (deleted + errors) separately from skipped
                        progress_display.update_phase(
                            resource_type, deleted + errors, errors, skipped
                        )

                    return callback

                with MigrationProgressDisplay(
                    title="🧹 AAP Cleanup Progress",
                    enabled=True,
                ) as progress:
                    # Set total phases BEFORE initialize_phases to avoid jitter
                    progress.set_total_phases(len(phases))
                    progress.initialize_phases(phases)

                    for rtype, description, total_count in phases:
                        # Start phase with actual total count
                        progress.start_phase(rtype, description, total_count)

                        # Create progress callback for live updates
                        progress_callback = create_progress_callback(progress, rtype)

                        # Delete resources with live progress updates
                        deleted, skipped, errors, failed = await delete_resources(
                            cleanup_client,
                            rtype,
                            ctx.config,
                            skip_default=not full,
                            progress_callback=progress_callback,  # Enable live updates
                        )

                        # Track failed resources across all types
                        for res_id, res_name, error_msg in failed:
                            all_failed_resources.append((rtype, res_id, res_name, error_msg))

                        # Update with actual count
                        # Pass errors as the "failed" count to show in Err: column
                        progress.update_phase(rtype, deleted + errors, errors, skipped)
                        progress.complete_phase(rtype)

                        total_deleted += deleted
                        total_skipped += skipped
                        total_errors += errors

                click.echo()
                echo_info("Cleanup Summary:")
                click.echo(f"  Resources deleted: {format_count(total_deleted)}")
                click.echo(f"  Resources skipped (protected): {format_count(total_skipped)}")
                click.echo(f"  Resources failed (errors): {format_count(total_errors)}")
                click.echo(
                    f"  Database: {cleared_progress} progress records, {deleted_mappings} mappings cleared"
                )

                # Enhanced error reporting with grouping
                if all_failed_resources:
                    click.echo()

                    # Group errors by type: blocked by jobs vs other errors
                    blocked_by_jobs = []
                    other_errors = []

                    for rtype, res_id, res_name, error_msg in all_failed_resources:
                        if (
                            "blocked by" in error_msg.lower()
                            or "active jobs" in error_msg.lower()
                            or "running jobs" in error_msg.lower()
                        ):
                            blocked_by_jobs.append((rtype, res_id, res_name, error_msg))
                        else:
                            other_errors.append((rtype, res_id, res_name, error_msg))

                    # Show resources blocked by active jobs
                    if blocked_by_jobs:
                        echo_warning(
                            f"⚠️  {len(blocked_by_jobs)} resource(s) blocked by active jobs:"
                        )
                        for rtype, res_id, res_name, error_msg in blocked_by_jobs[:10]:
                            click.echo(f"  - {rtype}: {res_name} (id={res_id})")
                            # Try to extract job info from error message
                            if ":" in error_msg:
                                # Error message might contain job details
                                click.echo(f"    Error: {error_msg[:120]}")

                        if len(blocked_by_jobs) > 10:
                            click.echo(f"  ... and {len(blocked_by_jobs) - 10} more")

                        click.echo()
                        click.echo("💡 Recommendation:")
                        click.echo(
                            "   These resources have jobs that are still running or couldn't be cancelled."
                        )
                        click.echo("   Wait for the jobs to complete, then run:")
                        click.echo("   $ aap-bridge cleanup --yes")
                        click.echo()

                    # Log other errors to file only (not console)
                    if other_errors:
                        logger.warning(
                            "cleanup_other_errors",
                            count=len(other_errors),
                            errors=[
                                {"type": rtype, "id": res_id, "name": res_name, "error": error_msg}
                                for rtype, res_id, res_name, error_msg in other_errors
                            ],
                        )

            # Clean up directories (exports/ and xformed/)
            import shutil

            directories_to_clean = {
                "exports": Path(exports_dir),
                "xformed": Path("xformed"),
            }

            # Remove skipped directories
            for skip in skip_dir:
                directories_to_clean.pop(skip, None)

            # Clean remaining directories (log to file only)
            for dir_name, dir_path in directories_to_clean.items():
                if dir_path.exists() and dir_path.is_dir():
                    try:
                        shutil.rmtree(dir_path)
                        logger.info("directory_removed", directory=dir_name, path=str(dir_path))
                    except Exception as e:
                        logger.error(
                            "directory_removal_failed",
                            directory=dir_name,
                            path=str(dir_path),
                            error=str(e),
                        )

        finally:
            # Restore original logging handlers
            for handler in original_handlers:
                if handler not in root_logger.handlers:
                    root_logger.addHandler(handler)

    try:
        asyncio.run(run_cleanup())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_cleanup())
