"""Diagnose an existing AAP Bridge installation.

``aap-bridge doctor`` is the single troubleshooting entry point, so a user does
not have to reason about uv, Podman, PostgreSQL, configuration files, and
network reachability separately.

``--fix`` repairs safe, local problems only: starting the bundled database,
recreating missing workspace directories, tightening file permissions. It never
changes AAP URLs, tokens, or anything on a remote system.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from aap_migration.cli import diagnostics, ui
from aap_migration.cli.diagnostics import Check
from aap_migration.config import find_workspace_root


def _render(checks: list[Check]) -> None:
    for check in checks:
        if check.status == "ok":
            ui.ok(check.name)
        elif check.status == "warn":
            ui.warn(check.name)
        else:
            ui.fail(check.name)


def _aap_settings() -> list[tuple[str, str, str, bool]]:
    """Read the source and target connection settings from the environment."""
    settings = []
    for label in ("Source", "Target"):
        prefix = label.upper()
        settings.append(
            (
                label,
                os.environ.get(f"{prefix}__URL", ""),
                os.environ.get(f"{prefix}__TOKEN", ""),
                os.environ.get(f"{prefix}__VERIFY_SSL", "true").lower() == "true",
            )
        )
    return settings


def _repair(workspace: Path, checks: list[Check]) -> list[Check]:
    """Apply the safe repairs for whatever is broken, and re-check."""
    fixable = [c for c in checks if c.status != "ok" and c.fixable]
    if not fixable:
        return checks

    ui.heading("Fixing issues")

    for check in fixable:
        if "Database not connected" in check.name:
            ui.step("Starting PostgreSQL")
            if diagnostics.start_database(workspace):
                ui.ok("PostgreSQL running")
            else:
                ui.fail("Could not start PostgreSQL")
        elif "permissions" in check.name:
            ui.step("Tightening token file permissions")
            (workspace / ".env").chmod(0o600)
            ui.ok("Token file permissions are secure")
        elif "Missing directories" in check.name:
            ui.step("Recreating workspace directories")
            for name in ("exports", "xformed", "reports", "logs", "schemas", "backups"):
                (workspace / name).mkdir(parents=True, exist_ok=True)
            ui.ok("Workspace directories present")

    return []


@click.command(name="doctor")
@click.option("--fix", is_flag=True, help="Repair safe, local problems automatically")
@click.option(
    "--brief",
    is_flag=True,
    help="Skip the banner and system section: just the workspace, database, and AAP",
)
@click.option(
    "--dir",
    "workspace",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Workspace to inspect (default: discovered from the current directory)",
)
def doctor(fix: bool, brief: bool, workspace: Path | None) -> None:
    """Check the installation, workspace, database, and AAP connections."""
    root = (workspace or find_workspace_root()).expanduser().resolve()

    # The installer calls this straight after reporting the platform and the
    # versions it found, so repeating them there is noise. Everything else is
    # identical, including the exit status.
    system = diagnostics.check_system()
    if brief:
        ui.heading("Verifying your setup")
    else:
        click.echo()
        click.secho("AAP Bridge Doctor", bold=True)
        ui.heading("System")
        _render(system)

        ui.heading("Workspace")
    # Brief mode drops the headings, not the checks: a problem that is counted
    # at the bottom but never shown is worse than a heading too many.
    workspace_checks = diagnostics.check_workspace(root)
    _render(workspace_checks)

    # A container deployment is the database plus the API engine and the Web
    # UI. Checking only the database answers "can a migration run?" rather than
    # "is my AAP Bridge healthy?", which is what was asked.
    containerised = diagnostics.installation_mode(root) == "container"

    db_url = os.environ.get("MIGRATION_STATE_DB_PATH", "")
    if not brief:
        ui.heading("Services" if containerised else "Database")
    db_checks = diagnostics.check_database(db_url, root)
    _render(db_checks)

    service_checks: list[Check] = []
    if containerised:
        service_checks = diagnostics.check_services(root)
        _render(service_checks)

    if not brief:
        ui.heading("AAP connections")
    aap_checks = [
        diagnostics.check_aap(url, token, verify, label)
        for label, url, token, verify in _aap_settings()
    ]
    _render(aap_checks)

    all_checks = system + workspace_checks + db_checks + service_checks + aap_checks
    problems = [c for c in all_checks if c.status != "ok"]

    if fix and problems:
        _repair(root, all_checks)
        # Re-run everything so the closing verdict reflects the repairs.
        ui.heading("Re-checking")
        recheck = (
            diagnostics.check_workspace(root)
            + diagnostics.check_database(db_url, root)
            + (diagnostics.check_services(root) if containerised else [])
            + [
                diagnostics.check_aap(url, token, verify, label)
                for label, url, token, verify in _aap_settings()
            ]
        )
        _render(recheck)
        problems = [c for c in recheck if c.status != "ok"]

    click.echo()
    blocking = [c for c in problems if c.status == "fail"]
    if not problems:
        click.secho("Everything looks good.", fg="green", bold=True)
        click.echo()
        return

    count = len(problems)
    click.secho(f"{count} issue{'s' if count != 1 else ''} found.", fg="yellow", bold=True)

    hints = [c.fix for c in problems if c.fix]
    if hints and not fix:
        click.echo()
        click.echo("Suggested fixes:")
        for hint in hints:
            click.echo(f"  {hint}")
        if any(c.fixable for c in problems):
            click.echo()
            click.echo("  Repair automatically:  aap-bridge doctor --fix")
    click.echo()

    if blocking:
        raise SystemExit(1)
