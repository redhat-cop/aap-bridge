"""Tests for inventory source post-import sync."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aap_migration.client.exceptions import AAPMigrationError, APIError
from aap_migration.config import PerformanceConfig
from aap_migration.migration.inventory_source_sync import (
    _extract_run_markers,
    _job_id_from_update_response,
    _sync_run_changed_since_baseline,
    _sync_status_from_inventory_source_payload,
    collect_inventory_source_target_ids_for_sync,
    sync_inventory_sources_after_import,
    trigger_inventory_source_update,
    wait_for_inventory_source_sync,
)


def test_collect_inventory_source_target_ids_for_sync() -> None:
    assert collect_inventory_source_target_ids_for_sync(None) == []
    assert collect_inventory_source_target_ids_for_sync([]) == []
    assert collect_inventory_source_target_ids_for_sync(
        [
            {"id": 1},
            {"id": 2, "_skipped": True},
            {"_skipped": True, "policy_skip": True, "id": 99},
            {"id": 1},
        ]
    ) == [1, 2]


def test_job_id_from_update_response_rejects_inventory_source_retrieve() -> None:
    # Bare source retrieve (GET update/ when can_update is false) must not be treated
    # as an inventory_update job id — that caused the poll hang (expected_job_id=source id).
    assert _job_id_from_update_response({"id": 106, "name": "my-source", "source": "scm"}) is None
    assert _job_id_from_update_response({"inventory_update": 66, "id": 66}) == 66
    assert _job_id_from_update_response({"type": "inventory_update", "id": 77}) == 77
    assert _job_id_from_update_response({"id": 88, "inventory_source": 12}) == 88


@pytest.mark.asyncio
async def test_trigger_inventory_source_update_reads_inventory_update_field() -> None:
    client = MagicMock()
    client.post = AsyncMock(return_value={"inventory_update": 66, "id": 66})
    assert await trigger_inventory_source_update(client, 226) == 66
    client.post.assert_awaited_once_with("inventory_sources/226/update/")


@pytest.mark.asyncio
async def test_trigger_inventory_source_update_raises_on_405_without_get_fallback() -> None:
    client = MagicMock()
    client.post = AsyncMock(
        side_effect=APIError("method not allowed", status_code=405, response={"detail": "405"})
    )
    client.get = AsyncMock(return_value={"id": 226, "name": "src", "source": "scm"})
    with pytest.raises(AAPMigrationError, match="405"):
        await trigger_inventory_source_update(client, 226)
    client.get.assert_not_awaited()


def test_sync_status_from_inventory_source_payload_nested() -> None:
    assert (
        _sync_status_from_inventory_source_payload(
            {"summary_fields": {"inventory_source": {"status": "pending"}}}
        )
        == "pending"
    )
    assert (
        _sync_status_from_inventory_source_payload(
            {"summary_fields": {"last_job": {"status": "successful"}}}
        )
        == "successful"
    )
    assert (
        _sync_status_from_inventory_source_payload({"status": "never updated"}) == "never updated"
    )


def test_extract_run_markers_ignores_modified_churn() -> None:
    baseline = {
        "status": "successful",
        "modified": "2026-04-20T10:00:00Z",
        "last_job_run": "2026-04-20T09:00:00Z",
        "last_updated": "2026-04-20T09:01:00Z",
    }
    changed_only_modified = {
        "status": "successful",
        "modified": "2026-04-20T10:00:10Z",
        "last_job_run": "2026-04-20T09:00:00Z",
        "last_updated": "2026-04-20T09:01:00Z",
    }
    assert _extract_run_markers(baseline) == _extract_run_markers(changed_only_modified)
    assert not _sync_run_changed_since_baseline(changed_only_modified, baseline)


@pytest.mark.asyncio
async def test_wait_for_inventory_source_sync_polls_until_terminal() -> None:
    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            {"status": "pending"},
            {"status": "running"},
            {"status": "successful"},
        ]
    )
    with patch(
        "aap_migration.migration.inventory_source_sync.asyncio.sleep", new_callable=AsyncMock
    ):
        final = await wait_for_inventory_source_sync(
            client, 228, poll_interval=1.0, timeout_seconds=60
        )
    assert final["status"] == "successful"
    assert client.get.await_count == 3
    assert client.get.await_args_list[0].args[0] == "inventory_sources/228/"


@pytest.mark.asyncio
async def test_wait_for_inventory_source_sync_ignores_stale_terminal_status() -> None:
    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            {"status": "successful", "last_updated": "2026-01-01T00:00:00Z"},
            {"status": "pending", "last_updated": "2026-01-01T00:01:00Z"},
            {"status": "successful", "last_updated": "2026-01-01T00:01:30Z"},
        ]
    )
    baseline = {"status": "successful", "last_updated": "2026-01-01T00:00:00Z"}
    with patch(
        "aap_migration.migration.inventory_source_sync.asyncio.sleep", new_callable=AsyncMock
    ):
        final = await wait_for_inventory_source_sync(
            client, 228, poll_interval=1.0, timeout_seconds=60, baseline_source=baseline
        )
    assert final["status"] == "successful"
    assert client.get.await_count == 3


@pytest.mark.asyncio
async def test_wait_for_inventory_source_sync_requires_expected_job_id() -> None:
    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            {"status": "successful", "summary_fields": {"last_job": {"id": 400}}},
            {"status": "pending", "summary_fields": {"last_job": {"id": 401}}},
            {"status": "successful", "summary_fields": {"last_job": {"id": 401}}},
        ]
    )
    with patch(
        "aap_migration.migration.inventory_source_sync.asyncio.sleep", new_callable=AsyncMock
    ):
        final = await wait_for_inventory_source_sync(
            client,
            228,
            poll_interval=1.0,
            timeout_seconds=60,
            expected_job_id=401,
            baseline_source={"status": "successful", "summary_fields": {"last_job": {"id": 400}}},
        )
    assert final["status"] == "successful"
    assert client.get.await_count == 3


@pytest.mark.asyncio
async def test_wait_exits_on_mismatch_when_run_completed() -> None:
    """Terminal + seen active recovers even if expected_job_id never matches last_job."""
    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            {"status": "pending", "summary_fields": {"current_job": {"id": 5001}}},
            {
                "status": "successful",
                "last_updated": "2026-01-01T00:02:00Z",
                "summary_fields": {"last_job": {"id": 5001}},
            },
        ]
    )
    baseline = {
        "status": "never updated",
        "last_updated": None,
        "summary_fields": {},
    }
    with patch(
        "aap_migration.migration.inventory_source_sync.asyncio.sleep", new_callable=AsyncMock
    ):
        # Wrong expected id (e.g. source id mistaken for update id)
        final = await wait_for_inventory_source_sync(
            client,
            106,
            poll_interval=1.0,
            timeout_seconds=60,
            expected_job_id=106,
            baseline_source=baseline,
        )
    assert final["status"] == "successful"
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_wait_matches_expected_job_via_current_job() -> None:
    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            {
                "status": "running",
                "summary_fields": {"current_job": {"id": 401, "status": "running"}},
            },
            {
                "status": "successful",
                "last_updated": "2026-01-01T00:02:00Z",
                "summary_fields": {"last_job": {"id": 401}},
            },
        ]
    )
    with patch(
        "aap_migration.migration.inventory_source_sync.asyncio.sleep", new_callable=AsyncMock
    ):
        final = await wait_for_inventory_source_sync(
            client,
            228,
            poll_interval=1.0,
            timeout_seconds=60,
            expected_job_id=401,
            baseline_source={"status": "never updated"},
        )
    assert final["status"] == "successful"
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_wait_still_ignores_stale_success_without_active_or_marker_change() -> None:
    client = MagicMock()
    # Only stale successful responses — never enters active, markers unchanged
    stale = {
        "status": "successful",
        "last_updated": "2026-01-01T00:00:00Z",
        "summary_fields": {"last_job": {"id": 400}},
    }
    client.get = AsyncMock(return_value=stale)
    baseline = dict(stale)

    # Loop: check deadline (t), heartbeat calc (t), sleep... until t >= timeout
    mono = {"t": 0.0}

    def fake_monotonic() -> float:
        return mono["t"]

    async def advance_time(_interval: float) -> None:
        mono["t"] += 20.0

    with (
        patch(
            "aap_migration.migration.inventory_source_sync.asyncio.sleep",
            side_effect=advance_time,
        ),
        patch(
            "aap_migration.migration.inventory_source_sync.time.monotonic",
            side_effect=fake_monotonic,
        ),
    ):
        with pytest.raises(TimeoutError):
            await wait_for_inventory_source_sync(
                client,
                228,
                poll_interval=1.0,
                timeout_seconds=60,
                expected_job_id=401,
                baseline_source=baseline,
            )
    assert client.get.await_count >= 2


@pytest.mark.asyncio
async def test_sync_inventory_sources_fail_on_job_failure() -> None:
    client = MagicMock()
    client.post = AsyncMock(return_value={"inventory_update": 1, "id": 1})
    client.get = AsyncMock(
        side_effect=[
            {"status": "never updated", "summary_fields": {"last_job": {"id": 0}}},
            {"status": "pending", "summary_fields": {"last_job": {"id": 1}}},
            {"status": "failed", "summary_fields": {"last_job": {"id": 1}}},
        ]
    )
    perf = PerformanceConfig(
        inventory_source_update_poll_interval_seconds=1.0,
        inventory_source_update_job_timeout_seconds=60,
        inventory_source_sync_max_concurrent=2,
        inventory_source_sync_fail_on_job_failure=True,
    )
    with patch(
        "aap_migration.migration.inventory_source_sync.asyncio.sleep", new_callable=AsyncMock
    ):
        with pytest.raises(AAPMigrationError):
            await sync_inventory_sources_after_import(client, [10], perf)


@pytest.mark.asyncio
async def test_sync_inventory_sources_continues_on_failure_when_configured() -> None:
    client = MagicMock()
    client.post = AsyncMock(return_value={"inventory_update": 1, "id": 1})
    client.get = AsyncMock(
        side_effect=[
            {"status": "never updated", "summary_fields": {"last_job": {"id": 0}}},
            {"status": "pending", "summary_fields": {"last_job": {"id": 1}}},
            {"status": "failed", "summary_fields": {"last_job": {"id": 1}}},
        ]
    )
    perf = PerformanceConfig(
        inventory_source_update_poll_interval_seconds=1.0,
        inventory_source_update_job_timeout_seconds=60,
        inventory_source_sync_max_concurrent=2,
        inventory_source_sync_fail_on_job_failure=False,
    )
    with patch(
        "aap_migration.migration.inventory_source_sync.asyncio.sleep", new_callable=AsyncMock
    ):
        await sync_inventory_sources_after_import(client, [10], perf)


@pytest.mark.asyncio
async def test_sync_continues_on_405_when_fail_on_error_false() -> None:
    client = MagicMock()
    client.post = AsyncMock(
        side_effect=APIError("method not allowed", status_code=405, response={"detail": "405"})
    )
    client.get = AsyncMock(return_value={"status": "never updated", "id": 10})
    perf = PerformanceConfig(
        inventory_source_update_poll_interval_seconds=1.0,
        inventory_source_update_job_timeout_seconds=60,
        inventory_source_sync_max_concurrent=2,
        inventory_source_sync_fail_on_job_failure=False,
    )
    await sync_inventory_sources_after_import(client, [10], perf)


@pytest.mark.asyncio
async def test_sync_raises_on_405_when_fail_on_error_true() -> None:
    client = MagicMock()
    client.post = AsyncMock(
        side_effect=APIError("method not allowed", status_code=405, response={"detail": "405"})
    )
    client.get = AsyncMock(return_value={"status": "never updated", "id": 10})
    perf = PerformanceConfig(
        inventory_source_update_poll_interval_seconds=1.0,
        inventory_source_update_job_timeout_seconds=60,
        inventory_source_sync_max_concurrent=2,
        inventory_source_sync_fail_on_job_failure=True,
    )
    with pytest.raises(AAPMigrationError, match="405"):
        await sync_inventory_sources_after_import(client, [10], perf)
