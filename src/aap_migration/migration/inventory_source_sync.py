"""Trigger inventory source updates and poll sync status on the inventory_source object.

The controller does not reliably expose live job status on ``inventory_updates/<id>/``;
status is read from repeated ``GET inventory_sources/<id>/`` responses (and common
``summary_fields`` fallbacks).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from aap_migration.client.exceptions import AAPMigrationError, APIError
from aap_migration.utils.logging import get_logger

if TYPE_CHECKING:
    from aap_migration.client.base_client import BaseAPIClient
    from aap_migration.config import PerformanceConfig

logger = get_logger(__name__)

# Unified job lifecycle (inventory_update uses the same status strings as other jobs)
_ACTIVE_STATUSES = frozenset({"pending", "waiting", "running", "new", "never updated"})
_SUCCESS_STATUSES = frozenset({"successful"})

# summary_fields keys that may carry the current or last inventory_update job
_JOB_SUMMARY_KEYS = ("last_job", "last_update", "current_job", "current_update")

# Heartbeat interval for poll-state logs when status is unchanged (seconds)
_POLL_HEARTBEAT_SECONDS = 30.0


def _sync_status_from_inventory_source_payload(data: dict[str, Any]) -> str:
    """Read sync/job status from an ``inventory_sources/<id>/`` GET response.

    The controller exposes status on the inventory source (not reliably on
    ``inventory_updates/<id>/`` in all deployments). Try common locations.
    """
    if not isinstance(data, dict):
        return ""
    s = (data.get("status") or "").strip().lower()
    if s:
        return s
    sf = data.get("summary_fields")
    if isinstance(sf, dict):
        for key in ("inventory_source", "last_job", "last_update", "current_job", "current_update"):
            block = sf.get(key)
            if isinstance(block, dict):
                st = (block.get("status") or "").strip().lower()
                if st:
                    return st
    return ""


def _job_ids_from_summary_fields(data: dict[str, Any] | None) -> list[int]:
    """Collect inventory_update job ids from common ``summary_fields`` blocks."""
    if not isinstance(data, dict):
        return []
    sf = data.get("summary_fields")
    if not isinstance(sf, dict):
        return []
    ids: list[int] = []
    for key in _JOB_SUMMARY_KEYS:
        block = sf.get(key)
        if not isinstance(block, dict):
            continue
        job_id = block.get("id")
        if job_id is None:
            continue
        try:
            ids.append(int(job_id))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(ids))


def _extract_completed_job_id(data: dict[str, Any] | None) -> int | None:
    """Extract completed-run job id from ``last_job`` / ``last_update`` only."""
    if not isinstance(data, dict):
        return None
    sf = data.get("summary_fields")
    if not isinstance(sf, dict):
        return None
    for key in ("last_job", "last_update"):
        block = sf.get(key)
        if not isinstance(block, dict):
            continue
        job_id = block.get("id")
        if job_id is None:
            continue
        try:
            return int(job_id)
        except (TypeError, ValueError):
            continue
    return None


def _extract_run_markers(data: dict[str, Any] | None) -> tuple[Any, Any, Any]:
    """Extract markers that indicate a *new sync run* occurred."""
    if not isinstance(data, dict):
        return (None, None, None)
    return (
        data.get("last_job_run"),
        data.get("last_updated"),
        _extract_completed_job_id(data),
    )


def _extract_last_job_id(data: dict[str, Any] | None) -> int | None:
    """Extract a representative job id from ``summary_fields`` (last_job preferred)."""
    ids = _job_ids_from_summary_fields(data)
    return ids[0] if ids else None


def _payload_has_expected_job(data: dict[str, Any] | None, expected_job_id: int) -> bool:
    """Return True when expected_job_id appears in any job summary field."""
    return expected_job_id in _job_ids_from_summary_fields(data)


def _sync_run_changed_since_baseline(
    current: dict[str, Any], baseline: dict[str, Any] | None
) -> bool:
    """Return true only when run-specific markers changed."""
    if not baseline:
        return True
    current_markers = _extract_run_markers(current)
    baseline_markers = _extract_run_markers(baseline)
    # If all markers are absent, we cannot claim this is a new run yet.
    if all(m is None for m in current_markers):
        return False
    return current_markers != baseline_markers


def _job_id_from_update_response(data: dict[str, Any] | None) -> int | None:
    """Parse inventory_update job id from a launch response.

    Accepts ``inventory_update`` explicitly, or ``id`` only when the payload
    looks like an inventory update (not an inventory source retrieve).
    """
    if not isinstance(data, dict):
        return None
    job_id = data.get("inventory_update")
    if job_id is not None:
        return int(job_id)
    # Full InventoryUpdateDetailSerializer body (POST update merges this in)
    if data.get("type") == "inventory_update" or data.get("inventory_source") is not None:
        raw_id = data.get("id")
        if raw_id is not None:
            return int(raw_id)
    return None


def collect_inventory_source_target_ids_for_sync(
    import_results: list[dict[str, Any]] | None,
) -> list[int]:
    """Return target inventory_source IDs that should run an update after import.

    Skips policy skips and entries without a concrete ``id`` (e.g. already-mapped skips).
    """
    if not import_results:
        return []
    ids: list[int] = []
    for r in import_results:
        if not r or not isinstance(r, dict):
            continue
        if r.get("_skipped") and r.get("policy_skip"):
            continue
        rid = r.get("id")
        if rid is not None:
            ids.append(int(rid))
    return list(dict.fromkeys(ids))


async def trigger_inventory_source_update(client: BaseAPIClient, inventory_source_id: int) -> int:
    """Launch ``inventory_sources/<id>/update/`` and return inventory_update job id.

    AAP returns 405 when the source cannot be updated (``can_update`` is false).
    GET on the update endpoint only retrieves the source and does not launch a job,
    so we fail closed instead of mistaking the source id for an inventory_update id.
    """
    path = f"inventory_sources/{inventory_source_id}/update/"
    try:
        data = await client.post(path)
    except APIError as e:
        if e.status_code == 405:
            raise AAPMigrationError(
                f"inventory_sources/{inventory_source_id}/update/ returned 405 "
                f"(source cannot be updated — check source type, credentials, "
                f"and source_project). Refusing GET fallback because it does not "
                f"launch a sync."
            ) from e
        raise
    job_id = _job_id_from_update_response(data if isinstance(data, dict) else None)
    if job_id is None:
        logger.error(
            "inventory_source_update_no_job_id",
            inventory_source_id=inventory_source_id,
            response_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        raise ValueError(f"inventory_sources/{inventory_source_id}/update/ did not return a job id")
    return job_id


async def wait_for_inventory_source_sync(
    client: BaseAPIClient,
    inventory_source_id: int,
    *,
    poll_interval: float,
    timeout_seconds: int,
    expected_job_id: int | None = None,
    baseline_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Poll ``inventory_sources/<id>/`` until sync status leaves active states."""
    deadline = time.monotonic() + timeout_seconds
    path = f"inventory_sources/{inventory_source_id}/"
    last: dict[str, Any] = {}
    seen_active = False
    seen_expected_job = expected_job_id is None
    last_status = ""
    last_job_seen: int | None = None
    last_heartbeat = time.monotonic()
    while time.monotonic() < deadline:
        last = await client.get(path)
        status = _sync_status_from_inventory_source_payload(last)
        current_job_id = _extract_last_job_id(last)
        prev_job_seen = last_job_seen
        if current_job_id is not None:
            last_job_seen = current_job_id
        if expected_job_id is not None and _payload_has_expected_job(last, expected_job_id):
            seen_expected_job = True
        now = time.monotonic()
        state_changed = status != last_status or current_job_id != prev_job_seen
        heartbeat_due = (now - last_heartbeat) >= _POLL_HEARTBEAT_SECONDS
        if state_changed or heartbeat_due:
            logger.info(
                "inventory_source_sync_poll_state",
                inventory_source_id=inventory_source_id,
                status=status,
                seen_expected_job=seen_expected_job,
                expected_job_id=expected_job_id,
                current_last_job_id=current_job_id,
                heartbeat=heartbeat_due and not state_changed,
            )
            last_status = status
            last_heartbeat = now
        if status in _ACTIVE_STATUSES:
            seen_active = True
        if status and status not in _ACTIVE_STATUSES:
            run_changed = _sync_run_changed_since_baseline(last, baseline_source)
            # Don't accept an old terminal status from before launch.
            # Prefer matching the launched job; fall back when a real run completed
            # but last_job id never matched expected_job_id (avoids hour-long hangs).
            if seen_active or run_changed:
                if seen_expected_job:
                    return last
                if expected_job_id is not None:
                    logger.warning(
                        "inventory_source_sync_expected_job_mismatch",
                        inventory_source_id=inventory_source_id,
                        status=status,
                        expected_job_id=expected_job_id,
                        current_last_job_id=current_job_id,
                        seen_active=seen_active,
                        run_changed=run_changed,
                    )
                    return last
        await asyncio.sleep(poll_interval)
    last_status = _sync_status_from_inventory_source_payload(last)
    raise TimeoutError(
        f"inventory_source {inventory_source_id} sync did not finish within {timeout_seconds}s "
        f"(last status={last_status!r}, expected_job_id={expected_job_id}, "
        f"last_seen_job_id={last_job_seen})"
    )


async def sync_inventory_sources_after_import(
    client: BaseAPIClient,
    inventory_source_ids: list[int],
    perf: PerformanceConfig,
) -> None:
    """For each target inventory source, trigger update and wait for the job to complete."""
    if not inventory_source_ids:
        return

    ids = list(dict.fromkeys(inventory_source_ids))
    interval = float(perf.inventory_source_update_poll_interval_seconds)
    timeout = int(perf.inventory_source_update_job_timeout_seconds)
    fail_on_error = perf.inventory_source_sync_fail_on_job_failure
    max_conc = min(
        int(perf.inventory_source_sync_max_concurrent),
        max(1, len(ids)),
    )
    sem = asyncio.Semaphore(max_conc)

    async def run_one(is_id: int) -> None:
        async with sem:
            try:
                baseline = await client.get(f"inventory_sources/{is_id}/")
                job_id = await trigger_inventory_source_update(client, is_id)
                logger.info(
                    "inventory_source_update_triggered",
                    inventory_source_id=is_id,
                    inventory_update_id=job_id,
                )
                final = await wait_for_inventory_source_sync(
                    client,
                    is_id,
                    poll_interval=interval,
                    timeout_seconds=timeout,
                    expected_job_id=job_id,
                    baseline_source=baseline,
                )
                status = _sync_status_from_inventory_source_payload(final)
                ok = status in _SUCCESS_STATUSES
                if ok:
                    logger.info(
                        "inventory_source_sync_finished",
                        inventory_source_id=is_id,
                        inventory_update_id=job_id,
                        status=status,
                    )
                else:
                    logger.warning(
                        "inventory_source_sync_finished_non_success",
                        inventory_source_id=is_id,
                        inventory_update_id=job_id,
                        status=status,
                    )
                    if fail_on_error:
                        raise AAPMigrationError(
                            f"Inventory update {job_id} for inventory_source {is_id} "
                            f"ended with status {status!r}"
                        )
            except TimeoutError as e:
                logger.error(
                    "inventory_source_sync_timeout",
                    inventory_source_id=is_id,
                    error=str(e),
                )
                if fail_on_error:
                    raise AAPMigrationError(str(e)) from e
            except Exception as e:
                logger.error(
                    "inventory_source_sync_failed",
                    inventory_source_id=is_id,
                    error=str(e),
                )
                if fail_on_error:
                    raise

    await asyncio.gather(*[run_one(i) for i in ids])
