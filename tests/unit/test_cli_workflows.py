"""Unit tests for web CLI workflow helpers."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aap_migration.api.models import Connection
from aap_migration.api.services.cli_workflows import (
    _is_exportable_schedule,
    build_migration_context_pair,
    filtered_migration_resource_types,
    migration_resource_types,
    migration_schemas_exist,
    run_connection_cleanup,
    run_migration_prep,
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


def test_build_migration_context_pair_sets_config_path_for_cli_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _connection(role="source", version="2.5")
    dest = _connection(role="destination", version="2.6")
    config_path = Path("/tmp/config.yaml")
    monkeypatch.setenv("AAP_BRIDGE_CONFIG", str(config_path))

    with patch(
        "aap_migration.api.services.cli_workflows.load_runtime_config",
        return_value=MagicMock(),
    ):
        ctx = build_migration_context_pair(source, dest, "sqlite:///test.db")

    assert ctx.config_path == config_path.resolve()
    assert ctx._config is not None


def test_is_exportable_schedule_excludes_system_job_schedules() -> None:
    cleanup = {
        "name": "Cleanup Job Schedule",
        "enabled": True,
        "summary_fields": {
            "unified_job_template": {"unified_job_type": "system_job", "id": 1},
        },
    }
    demo = {
        "name": "Demo Schedule",
        "enabled": True,
        "summary_fields": {
            "unified_job_template": {"unified_job_type": "job_template", "id": 6},
        },
    }
    disabled = {
        "name": "Old Schedule",
        "enabled": False,
        "summary_fields": {
            "unified_job_template": {"unified_job_type": "job_template", "id": 7},
        },
    }

    assert not _is_exportable_schedule(cleanup)
    assert _is_exportable_schedule(demo)
    assert not _is_exportable_schedule(disabled)


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
    (tmp_path / "exports" / "metadata.json").write_text("{}")
    (tmp_path / "xformed" / "metadata.json").write_text("{}")
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
    assert (tmp_path / "exports").exists()
    assert not any((tmp_path / "exports").iterdir())
    assert (tmp_path / "xformed").exists()
    assert not any((tmp_path / "xformed").iterdir())
    assert mock_client.close.await_count == 1


def test_migration_resource_types_excludes_default_migration_exclusions() -> None:
    types = migration_resource_types()

    assert "organizations" in types
    assert "instances" not in types
    assert "instance_groups" not in types


def test_filtered_migration_resource_types_skips_never_migrate_discoveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "aap_migration.api.services.cli_workflows.get_exportable_types",
        lambda use_discovered=False: ["organizations", "legacy_auth", "authenticators"],
    )
    monkeypatch.setattr(
        "aap_migration.api.services.cli_workflows.get_importable_types",
        lambda use_discovered=False: ["organizations", "legacy_auth", "authenticators"],
    )

    types = filtered_migration_resource_types()

    assert "organizations" in types
    assert "legacy_auth" not in types
    assert "authenticators" not in types


@pytest.mark.asyncio
async def test_run_phased_migration_skips_prep_when_schemas_exist() -> None:
    source = _connection(role="source", version="2.5")
    dest = _connection(role="destination", version="2.6")
    mock_ctx = MagicMock()
    mock_ctx.source_client.close = AsyncMock()
    mock_ctx.target_client.close = AsyncMock()

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context_pair",
            return_value=mock_ctx,
        ),
        patch(
            "aap_migration.api.services.cli_workflows.migration_schemas_exist",
            return_value=True,
        ),
        patch(
            "aap_migration.api.services.cli_workflows._run_phased_migration_workflow",
        ) as workflow,
    ):
        result = await run_phased_migration(source, dest, "sqlite:///test.db")

    assert result.status == "completed"
    workflow.assert_called_once()
    assert workflow.call_args.kwargs["skip_prep"] is True


@pytest.mark.asyncio
async def test_run_phased_migration_runs_prep_when_schemas_missing() -> None:
    source = _connection(role="source", version="2.5")
    dest = _connection(role="destination", version="2.6")
    mock_ctx = MagicMock()
    mock_ctx.source_client.close = AsyncMock()
    mock_ctx.target_client.close = AsyncMock()

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context_pair",
            return_value=mock_ctx,
        ),
        patch(
            "aap_migration.api.services.cli_workflows.migration_schemas_exist",
            return_value=False,
        ),
        patch(
            "aap_migration.api.services.cli_workflows._run_phased_migration_workflow",
        ) as workflow,
    ):
        result = await run_phased_migration(source, dest, "sqlite:///test.db")

    assert result.status == "completed"
    workflow.assert_called_once()
    assert workflow.call_args.kwargs["skip_prep"] is False


@pytest.mark.asyncio
async def test_run_migration_prep_delegates_to_prep_workflow() -> None:
    source = _connection(role="source", version="2.5")
    dest = _connection(role="destination", version="2.6")
    mock_ctx = MagicMock()
    mock_ctx.config.paths.schema_dir = "schemas"
    mock_ctx.source_client.close = AsyncMock()
    mock_ctx.target_client.close = AsyncMock()
    prep_result = MagicMock(status="completed", message="", skipped=False)

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context_pair",
            return_value=mock_ctx,
        ),
        patch(
            "aap_migration.prep.workflow.run_prep_workflow",
            new_callable=AsyncMock,
            return_value=prep_result,
        ) as prep,
    ):
        result = await run_migration_prep(source, dest, "sqlite:///test.db", log=print)

    assert result.status == "completed"
    prep.assert_awaited_once()
    mock_ctx.source_client.close.assert_awaited_once()
    mock_ctx.target_client.close.assert_awaited_once()


def test_migration_schemas_exist_checks_comparison_file(tmp_path: Path) -> None:
    mock_ctx = MagicMock()
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    mock_ctx.config.paths.schema_dir = str(schema_dir)

    assert migration_schemas_exist(mock_ctx) is False

    (schema_dir / "schema_comparison.json").write_text("{}")
    assert migration_schemas_exist(mock_ctx) is True


@pytest.mark.asyncio
async def test_run_phased_migration_invokes_cli_workflow() -> None:
    source = _connection(role="source", version="2.5")
    dest = _connection(role="destination", version="2.6")
    logs: list[str] = []

    with (
        patch(
            "aap_migration.api.services.cli_workflows.build_migration_context_pair",
            return_value=MagicMock(
                source_client=AsyncMock(),
                target_client=AsyncMock(),
            ),
        ),
        patch(
            "aap_migration.api.services.cli_workflows._run_phased_migration_workflow",
            side_effect=lambda *args, **kwargs: logs.append("workflow"),
        ) as workflow,
    ):
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
