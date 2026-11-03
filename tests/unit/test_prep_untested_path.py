"""Untested paths require an explicit discovery override, including in the menu."""

import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from aap_migration.cli import menu
from aap_migration.cli.commands import prep as prep_module
from aap_migration.prep import workflow
from aap_migration.resources import get_version_path


class TestUntestedPrep(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "schemas"
        self.config = SimpleNamespace(
            source=SimpleNamespace(url="https://source/api/v2", version="2.4"),
            target=SimpleNamespace(url="https://target/api/controller/v2", version="9.9"),
            ignored_endpoints={"common": [], "source": [], "target": []},
        )
        self.ctx = SimpleNamespace(
            config_path=Path("lab.yaml"),
            config=self.config,
            source_client=SimpleNamespace(get=AsyncMock(return_value={})),
            target_client=SimpleNamespace(get=AsyncMock(return_value={})),
        )

    def invoke(self, *flags):
        return CliRunner().invoke(
            prep_module.prep,
            ["--output-dir", str(self.output), *flags],
            obj=self.ctx,
        )

    def test_default_rejects_untested_path_without_traceback(self):
        with (
            patch.object(workflow, "discover_endpoints", new_callable=AsyncMock) as discover,
            patch.object(workflow.logger, "error") as log,
        ):
            result = self.invoke()
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("prep --allow-untested-path", result.output)
        self.assertNotIn("Traceback", result.output)
        self.assertNotIn("Unexpected Error", result.output)
        discover.assert_not_awaited()
        log.assert_not_called()

    def test_explicit_override_runs_discovery_and_retains_untested_status(self):
        with self.discovery() as discover:
            result = self.invoke("--allow-untested-path")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("migration compatibility remains unverified", result.output)
        self.assertIn("Prep complete!", result.output)
        self.assertEqual(discover.await_count, 2)
        self.ctx.source_client.get.assert_awaited_once_with("ping/")
        self.ctx.target_client.get.assert_awaited_once_with("ping/")
        self.assertIsNone(get_version_path("2.4", "9.9"))

    @contextmanager
    def discovery(self):
        with (
            patch.object(
                workflow,
                "discover_endpoints",
                new_callable=AsyncMock,
                return_value={"endpoints": {}},
            ) as discover,
            patch.object(
                workflow, "generate_schema", new_callable=AsyncMock, return_value={"schemas": {}}
            ),
            patch.object(workflow, "compare_schemas", return_value={"transformations": {}}),
            patch.object(workflow, "save_endpoints"),
            patch.object(workflow, "save_schema"),
            patch.object(workflow, "save_comparison"),
            patch("aap_migration.schema.persistence.save_schemas", new_callable=AsyncMock),
        ):
            yield discover

    def test_supported_pair_does_not_require_override(self):
        self.config.target.version = "2.7"
        with self.discovery() as discover:
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("unverified", result.output)
        self.assertEqual(discover.await_count, 2)
        self.assertIsNotNone(get_version_path("2.4", "2.7"))

    def test_force_still_allows_unknown_pair_and_overwrites_schemas(self):
        self.output.mkdir()
        for filename in ("source_endpoints.json", "target_endpoints.json"):
            (self.output / filename).write_text("{}")
        with self.discovery() as discover, patch.object(prep_module.click, "confirm") as confirm:
            result = self.invoke("--force")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("migration compatibility remains unverified", result.output)
        self.assertEqual(discover.await_count, 2)
        confirm.assert_not_called()

    def test_override_uses_discovered_versions_when_not_configured(self):
        self.config.source.version = None
        self.config.target.version = None
        self.ctx.source_client.get_version = AsyncMock(return_value="2.4")
        self.ctx.target_client.get_version = AsyncMock(return_value="9.9")
        with self.discovery() as discover:
            result = self.invoke("--allow-untested-path")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(discover.await_args_list[0].kwargs["api_version"], "2.4")
        self.assertEqual(discover.await_args_list[1].kwargs["api_version"], "9.9")

    def test_shared_workflow_defaults_still_reject_unknown_pairs(self):
        with self.discovery() as discover:
            result = workflow.run_prep_workflow_sync(self.ctx, self.output)
        self.assertEqual(result.status, "failed")
        discover.assert_not_awaited()

    def test_override_does_not_overwrite_existing_schemas_without_confirmation(self):
        self.output.mkdir()
        for filename in ("source_endpoints.json", "target_endpoints.json"):
            (self.output / filename).write_text("{}")
        with patch.object(prep_module.click, "confirm", return_value=False):
            result = self.invoke("--allow-untested-path")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Cancelled", result.output)
        self.ctx.source_client.get.assert_not_awaited()

    def test_menu_asks_before_running_discovery_for_untested_path(self):
        for accepted in (True, False):
            with (
                self.subTest(accepted=accepted),
                patch.object(
                    menu.Prompt, "ask", side_effect=["1", "", "q"] if accepted else ["1", "q"]
                ),
                patch.object(menu.Confirm, "ask", return_value=accepted) as confirm,
                patch.object(menu, "Console"),
                patch.object(menu, "run_command") as run,
            ):
                click_ctx = SimpleNamespace(obj=self.ctx)
                menu.interactive_menu(click_ctx)
                confirm.assert_called_once()
                if accepted:
                    run.assert_called_once_with(["prep", "--allow-untested-path"], click_ctx)
                else:
                    run.assert_not_called()

    def test_menu_runs_known_pair_without_confirmation(self):
        self.config.target.version = "2.7"
        with (
            patch.object(menu.Prompt, "ask", side_effect=["1", "", "q"]),
            patch.object(menu.Confirm, "ask") as confirm,
            patch.object(menu, "Console"),
            patch.object(menu, "run_command") as run,
        ):
            click_ctx = SimpleNamespace(obj=self.ctx)
            menu.interactive_menu(click_ctx)
        confirm.assert_not_called()
        run.assert_called_once_with(["prep"], click_ctx)


if __name__ == "__main__":
    unittest.main()
