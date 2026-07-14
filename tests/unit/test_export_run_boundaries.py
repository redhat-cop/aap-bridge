import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from aap_migration.migration.state import ExportRunContext, MigrationState


@pytest.fixture
def run_context() -> ExportRunContext:
    return ExportRunContext(
        source_url="https://source.aap.example.com",
        source_version="2.3.0",
        output_dir="/tmp/exports",
        resource_types=("organizations", "users"),
        filters=(("name__icontains", "test"),),
        state_dsn_fingerprint="abc1234567890def",
        timestamp="2026-03-24T12:00:00Z",
    )


def test_run_context_fingerprint_identity(run_context: ExportRunContext) -> None:
    """Test that run_fingerprint is stable regardless of timestamp."""
    fp1 = run_context.run_fingerprint

    # Create another context with different timestamp but same identity fields
    context2 = ExportRunContext(
        source_url=run_context.source_url,
        source_version=run_context.source_version,
        output_dir=run_context.output_dir,
        resource_types=run_context.resource_types,
        filters=run_context.filters,
        state_dsn_fingerprint=run_context.state_dsn_fingerprint,
        timestamp="2026-03-25T00:00:00Z",
    )

    assert fp1 == context2.run_fingerprint


def test_run_context_fingerprint_change(run_context: ExportRunContext) -> None:
    """Test that run_fingerprint changes when identity fields change."""
    fp1 = run_context.run_fingerprint

    # Change source URL
    context2 = ExportRunContext(
        source_url="https://other.aap.example.com",
        source_version=run_context.source_version,
        output_dir=run_context.output_dir,
        resource_types=run_context.resource_types,
        filters=run_context.filters,
        state_dsn_fingerprint=run_context.state_dsn_fingerprint,
        timestamp=run_context.timestamp,
    )

    assert fp1 != context2.run_fingerprint


@pytest.mark.asyncio
async def test_export_clears_stale_mappings(tmp_path: Path) -> None:
    """Test that non-resume export clears stale mappings for specified types."""
    from aap_migration.cli.commands.export_import import export

    mock_ctx = MagicMock()
    mock_ctx.config.paths.export_dir = str(tmp_path)
    mock_ctx.config.export.records_per_file = 100
    mock_ctx.config.export.filters = {}
    mock_ctx.config.performance.parallel_resource_types = False
    mock_ctx.migration_state.database_url = "sqlite:///:memory:"
    mock_ctx.migration_state.clear_mappings.return_value = 5

    # Use patch to inject our mock context
    with patch("aap_migration.cli.commands.export_import.pass_context", lambda x: x):
        with patch("aap_migration.cli.commands.export_import.requires_config", lambda x: x):
            with patch("aap_migration.cli.commands.export_import.handle_errors", lambda x: x):
                runner = CliRunner()
                # Run export for specific type
                with patch(
                    "aap_migration.cli.commands.export_import.asyncio.run",
                    side_effect=lambda coro: coro.close(),
                ):
                    runner.invoke(export, ["-r", "organizations", "--yes"], obj=mock_ctx)

                # Check that clear_mappings was called for the requested type
                mock_ctx.migration_state.clear_mappings.assert_any_call(
                    "organizations", phase="export"
                )


def test_migration_state_get_all_resource_types() -> None:
    """Test get_all_resource_types returns union of types from both tables."""
    from aap_migration.config import StateConfig

    config = StateConfig(db_path="sqlite:///:memory:")
    state = MigrationState(config)

    with patch("aap_migration.migration.state.get_session") as mock_get_session:
        mock_session = mock_get_session.return_value.__enter__.return_value

        # Mock queries for both tables
        mock_session.query.return_value.distinct.return_value.all.side_effect = [
            [("organizations",), ("users",)],  # progress types
            [("organizations",), ("credentials",)],  # mapping types
        ]

        types = state.get_all_resource_types()
        assert types == ["credentials", "organizations", "users"]


@pytest.mark.asyncio
async def test_resume_export_uses_mappings(tmp_path: Path) -> None:
    """REQ-008: proves resume actually skips mapped resources."""
    from aap_migration.migration.exporter import OrganizationExporter

    mock_client = AsyncMock()
    mock_state = MagicMock()
    mock_performance = MagicMock()
    mock_performance.batch_sizes = {"organizations": 200}

    # Mock state.get_all_mappings to return resource 1
    mock_state.get_all_mappings.return_value = [{"resource_type": "organizations", "source_id": 1}]

    exporter = OrganizationExporter(mock_client, mock_state, mock_performance)
    exporter._existing_mappings_cache = {("organizations", 1)}
    # Prevent overwriting by _load_existing_mappings_cache
    exporter._cache_loaded_for = "organizations"
    exporter.set_resume_checkpoint(0)  # Enable resume mode

    # Mock client.get to return two organizations
    mock_client.get.return_value = {
        "count": 2,
        "results": [{"id": 1, "name": "Org 1"}, {"id": 2, "name": "Org 2"}],
        "next": None,
    }

    # Export
    resources = []
    async for res in exporter.export():
        resources.append(res)

    # Should only have Org 2 (Org 1 skipped because it's in the cache)
    assert len(resources) == 1
    assert resources[0]["id"] == 2


def test_resume_context_mismatch_aborts(
    tmp_path: Path, run_context: ExportRunContext
) -> None:
    """REQ-008: proves mismatched fingerprint blocks resume."""
    from aap_migration.cli.commands.export_import import export

    # Create metadata with a different fingerprint
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    metadata = {"run_context": {"run_fingerprint": "different_fingerprint"}}
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f)

    mock_ctx = MagicMock()
    mock_ctx.config.source.url = run_context.source_url
    mock_ctx.config.source.version = run_context.source_version
    mock_ctx.config.export.filters = dict(run_context.filters)
    mock_ctx.config.export.records_per_file = 100
    mock_ctx.config.performance.parallel_resource_types = False
    mock_ctx.config.paths.export_dir = str(output_dir)
    mock_ctx.migration_state.database_url = "sqlite:///:memory:"

    with patch("aap_migration.cli.commands.export_import.pass_context", lambda x: x):
        with patch("aap_migration.cli.commands.export_import.requires_config", lambda x: x):
            with patch("aap_migration.cli.commands.export_import.handle_errors", lambda x: x):
                runner = CliRunner()
                result = runner.invoke(export, ["--resume", "--yes"], obj=mock_ctx)

                assert result.exit_code != 0
                assert "Resume mismatch" in result.output


def test_resume_context_mismatch_force_override(
    tmp_path: Path, run_context: ExportRunContext
) -> None:
    """REQ-008: proves --force bypasses the block."""
    from aap_migration.cli.commands.export_import import export

    # Create metadata with a different fingerprint
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    metadata = {"run_context": {"run_fingerprint": "different_fingerprint"}}
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f)

    mock_ctx = MagicMock()
    mock_ctx.config.source.url = run_context.source_url
    mock_ctx.config.source.version = run_context.source_version
    mock_ctx.config.export.filters = dict(run_context.filters)
    mock_ctx.config.export.records_per_file = 100
    mock_ctx.config.performance.parallel_resource_types = False
    mock_ctx.config.paths.export_dir = str(output_dir)
    mock_ctx.migration_state.database_url = "sqlite:///:memory:"

    def consume_asyncio_run(coro):
        coro.close()

    # Mock asyncio.run to avoid actual API calls after resume validation passes
    with patch("aap_migration.cli.commands.export_import.pass_context", lambda x: x):
        with patch("aap_migration.cli.commands.export_import.requires_config", lambda x: x):
            with patch("aap_migration.cli.commands.export_import.handle_errors", lambda x: x):
                with patch(
                    "aap_migration.cli.commands.export_import.asyncio.run",
                    side_effect=consume_asyncio_run,
                ):
                    runner = CliRunner()
                    result = runner.invoke(export, ["--resume", "--force", "--yes"], obj=mock_ctx)

                    assert result.exit_code == 0
                    assert "Resume mismatch detected but --force is set" in result.output


def test_complete_phase_zero_shows_warning() -> None:
    """REQ-008: proves the progress display fix works (zero items phase)."""
    from aap_migration.reporting.live_progress import PhaseProgressState

    # Test that status_text returns 'complete' even for 0 items if processed
    state = PhaseProgressState(
        phase_name="test",
        resource_type="test",
        total_items=0,
        completed=0,
        failed=0,
        skipped=0,
    )

    # guidellm pattern: total_processed >= total_items means complete
    assert state.status_text == "complete"
    assert state.progress_percentage == 100.0


def test_state_reset_clears_progress_and_mappings() -> None:
    """REQ-008: proves reset actually clears data."""
    from aap_migration.cli.commands.state import reset_state

    mock_ctx = MagicMock()
    mock_ctx.migration_state.get_all_resource_types.return_value = ["organizations"]

    with patch("aap_migration.cli.commands.state.pass_context", lambda x: x):
        with patch("aap_migration.cli.commands.state.requires_config", lambda x: x):
            with patch("aap_migration.cli.commands.state.handle_errors", lambda x: x):
                runner = CliRunner()
                runner.invoke(reset_state, ["--yes"], obj=mock_ctx)

                mock_ctx.migration_state.clear_progress.assert_called_with("organizations")
                mock_ctx.migration_state.clear_mappings.assert_called_with("organizations")


def test_state_reset_resource_type_granularity() -> None:
    """REQ-008: proves per-type reset doesn't affect others."""
    from aap_migration.cli.commands.state import reset_state

    mock_ctx = MagicMock()

    with patch("aap_migration.cli.commands.state.pass_context", lambda x: x):
        with patch("aap_migration.cli.commands.state.requires_config", lambda x: x):
            with patch("aap_migration.cli.commands.state.handle_errors", lambda x: x):
                runner = CliRunner()
                # Reset only organizations
                runner.invoke(reset_state, ["-r", "organizations", "--yes"], obj=mock_ctx)

                mock_ctx.migration_state.clear_progress.assert_called_once_with("organizations")
                # Ensure no other types were cleared
                # (assuming get_all_resource_types would be called otherwise)
                assert not mock_ctx.migration_state.get_all_resource_types.called
