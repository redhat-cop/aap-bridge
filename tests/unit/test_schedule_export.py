"""Unit tests for schedule export behavior."""

from unittest.mock import MagicMock

import pytest

from aap_migration.config import PerformanceConfig
from aap_migration.migration.exporter import ScheduleExporter


@pytest.mark.asyncio
async def test_schedule_exporter_does_not_force_enabled_filter():
    """Export must include disabled schedules; do not inject enabled=true."""
    client = MagicMock()
    state = MagicMock()
    performance = PerformanceConfig(batch_sizes={"schedules": 200})
    exporter = ScheduleExporter(client, state, performance)

    captured: dict = {}

    async def fake_export_resources(**kwargs):
        captured.clear()
        captured.update(kwargs)
        if False:  # pragma: no cover — async generator protocol
            yield {}

    exporter.export_resources = fake_export_resources  # type: ignore[method-assign]

    results = [item async for item in exporter.export()]
    assert results == []
    assert captured.get("filters") is None

    results = [item async for item in exporter.export(filters={"page_size": 50})]
    assert results == []
    assert captured.get("filters") == {"page_size": 50}
    assert "enabled" not in captured["filters"]
