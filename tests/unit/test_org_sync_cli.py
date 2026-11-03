"""The sync CLI requires scope, defaults to planning, and honors dry-run mode."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from aap_migration.cli.commands import sync as command


class TestSyncCLI(unittest.TestCase):
    def context(self, dry_run=False):
        return SimpleNamespace(
            config_path=Path("sync.yaml"),
            config=SimpleNamespace(dry_run=dry_run),
            source_client=SimpleNamespace(close=AsyncMock()),
            target_client=SimpleNamespace(close=AsyncMock()),
        )

    def test_organization_is_required(self):
        result = CliRunner().invoke(command.sync, [], obj=self.context())
        self.assertEqual(result.exit_code, 2)
        self.assertIn("--organization", result.output)

    def test_plan_never_requests_apply(self):
        ctx = self.context()
        with patch.object(command, "synchronize", new_callable=AsyncMock, return_value={}) as sync:
            result = CliRunner().invoke(command.sync, ["--organization", "aap-bridge"], obj=ctx)
        self.assertEqual(result.exit_code, 0, result.output)
        sync.assert_awaited_once_with(
            ctx.source_client, ctx.target_client, "aap-bridge", apply=False
        )
        ctx.source_client.close.assert_awaited_once()
        ctx.target_client.close.assert_awaited_once()

    def test_apply_requires_explicit_flag_and_non_dryrun_config(self):
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                ctx = self.context(dry_run=dry_run)
                with patch.object(
                    command, "synchronize", new_callable=AsyncMock, return_value={}
                ) as sync:
                    result = CliRunner().invoke(
                        command.sync, ["--organization", "aap-bridge", "--apply"], obj=ctx
                    )
                if dry_run:
                    self.assertEqual(result.exit_code, 1, result.output)
                    sync.assert_not_awaited()
                else:
                    self.assertEqual(result.exit_code, 0, result.output)
                    self.assertTrue(sync.call_args.kwargs["apply"])


if __name__ == "__main__":
    unittest.main()
