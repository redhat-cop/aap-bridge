"""Unit tests for web CLI workflow helpers."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aap_migration.api.models import Connection
from aap_migration.api.services.cli_workflows import (
    migration_resource_types,
    run_connection_cleanup,
    run_connection_export,
    run_phased_migration,
)


def _connection(**kwargs) -> Connection:
    defaults = {
        "name": "AAP",
        "type": "aap",
        "role": "destination",
        "url": "https://aap.example.com",
        "token": "token",
        "verify_ssl": True,
        "version": "2.6",
    }
    defaults.update(kwargs)
    return Connection(**defaults)


@pytest.mark.asyncio
async def test_run_connection_export_uses_parallel_export_coordinator(tmp_path: Path) -> None:
    conn = _connection(role="source", version="2.5")
    mock_ctx = MagicMock()
    mock_ctx.config.performance.parallel_resource_types = True
    mock_ctx.config.export.records_per_file = 1000
    mock_ctx.source_client.close = AsyncMock()

    coordinator = MagicMock()
    coordinator.export_all_parallel = AsyncMock(
        return_value={
            "organizations": {"exported": 2, "failed": 0},
            "projects": {"exported": 0, "failed": 1},
        }
    )

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context",
            return_value=mock_ctx,
        ),
        patch(
            "aap_migration.api.services.cli_workflows._export_resource_types",
            return_value=["organizations", "projects"],
        ),
        patch(
            "aap_migration.api.services.cli_workflows.ParallelExportCoordinator",
            return_value=coordinator,
        ),
    ):
        result = await run_connection_export(conn, "sqlite:///test.db", tmp_path)

    assert result.total_resources == 2
    assert result.resource_types == 1
    assert result.errors == 1
    assert (tmp_path / "metadata.json").exists()
    mock_ctx.source_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_connection_cleanup_uses_cli_cleanup_helpers(tmp_path: Path) -> None:
    conn = _connection(role="destination")
    mock_ctx = MagicMock()
    mock_ctx.config.performance.rate_limit = 20
    mock_ctx.config.state.db_path = "sqlite:///test.db"
    mock_ctx.config.paths.export_dir = str(tmp_path / "exports")
    mock_ctx.config.paths.transform_dir = str(tmp_path / "xformed")
    (tmp_path / "exports").mkdir()
    (tmp_path / "xformed").mkdir()
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context",
            return_value=mock_ctx,
        ),
        patch(
            "aap_migration.api.services.cli_workflows.AAPTargetClient",
            return_value=mock_client,
        ),
        patch(
            "aap_migration.api.services.cli_workflows.clear_database",
            return_value=(12, 34),
        ),
        patch(
            "aap_migration.api.services.cli_workflows.cancel_all_jobs",
            new_callable=AsyncMock,
            return_value={"jobs": 1},
        ),
        patch(
            "aap_migration.api.services.cli_workflows.get_cleanup_resource_types",
            new_callable=AsyncMock,
            return_value=["projects", "organizations"],
        ),
        patch(
            "aap_migration.api.services.cli_workflows.delete_resources",
            new_callable=AsyncMock,
            side_effect=[
                (3, 1, 0, []),
                (2, 0, 1, []),
            ],
        ),
    ):
        result = await run_connection_cleanup(conn, "sqlite:///test.db")

    assert result.deleted == 5
    assert result.skipped == 1
    assert result.errors == 1
    assert result.cleared_progress == 12
    assert result.deleted_mappings == 34
    assert set(result.directories_removed) == {"exports", "xformed"}
    assert not (tmp_path / "exports").exists()
    assert not (tmp_path / "xformed").exists()
    assert mock_client.close.await_count == 1


def test_migration_resource_types_excludes_default_migration_exclusions() -> None:
    types = migration_resource_types()

    assert "organizations" in types
    assert "instances" not in types
    assert "instance_groups" not in types


@pytest.mark.asyncio
async def test_run_phased_migration_invokes_cli_workflow() -> None:
    source = _connection(role="source", version="2.5")
    dest = _connection(role="destination", version="2.6")
    logs: list[str] = []

    with patch(
        "aap_migration.api.services.cli_workflows._run_phased_migration_workflow",
        side_effect=lambda *args, **kwargs: logs.append("workflow"),
    ) as workflow:
        result = await run_phased_migration(
            source,
            dest,
            "sqlite:///test.db",
            log=logs.append,
            skip_prep=True,
        )

    assert result.status == "completed"
    workflow.assert_called_once()
    assert logs == ["workflow"]


@pytest.mark.asyncio
async def test_run_phased_migration_reports_click_failures() -> None:
    import click

    source = _connection(role="source", version="2.5")
    dest = _connection(role="destination", version="2.6")

    with patch(
        "aap_migration.api.services.cli_workflows._run_phased_migration_workflow",
        side_effect=click.ClickException("export failed"),
    ):
        result = await run_phased_migration(source, dest, "sqlite:///test.db")

    assert result.status == "failed"
    assert result.message == "export failed"
