"""Environment and configuration checks shared by setup and diagnostics.

``aap-bridge init`` runs these to verify a freshly created workspace;
``aap-bridge doctor`` runs the same checks against an existing one. Keeping a
single implementation means setup cannot report healthy for something doctor
would later call broken.

Every check returns a :class:`Check` rather than printing, so callers decide
how to render and whether a failure is fatal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Status = Literal["ok", "warn", "fail"]

#: Seconds to wait on a network or database probe. Short: these run in front of
#: a user who is waiting, and a slow answer is as good as a failure here.
_PROBE_TIMEOUT = 8


@dataclass(slots=True, frozen=True)
class Check:
    """One diagnostic result.

    Attributes:
        name: Short label shown next to the status symbol.
        status: ``ok``, ``warn`` (degraded but usable), or ``fail``.
        fix: What would repair it, when a repair exists.
        fixable: Whether ``doctor --fix`` can repair it without touching
            remote systems or credentials.
    """

    name: str
    status: Status = "ok"
    fix: str = ""
    fixable: bool = False


def _tool_version(executable: str, *args: str) -> str:
    """Return a tool's version string, or an empty string if unavailable."""
    if shutil.which(executable) is None:
        return ""
    try:
        result = subprocess.run(
            [executable, *(args or ("--version",))],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def in_container() -> bool:
    """Whether this process is running inside a container.

    Podman writes ``/run/.containerenv``; Docker writes ``/.dockerenv``. It
    changes what advice makes sense: a container image has no Podman in it and
    is not supposed to, because whatever started it owns the other services.
    """
    return Path("/run/.containerenv").exists() or Path("/.dockerenv").exists()


def check_system() -> list[Check]:
    """Check the tools AAP Bridge depends on at run time."""
    import platform

    checks = [Check(f"{platform.system()} {platform.machine()}")]

    podman = _tool_version("podman")
    if podman:
        # "podman version 5.8.4" -> "Podman 5.8.4"
        version = podman.split()[-1]
        checks.append(Check(f"Podman {version}"))
    elif in_container():
        # The container installer's stack runs the database as a sibling
        # service, so telling the user to install Podman in here is wrong.
        # Named for the deployment, not for this process: the user chose how
        # AAP Bridge runs, and that is what the line is reporting.
        checks.append(Check("Container deployment"))
    else:
        checks.append(
            Check(
                "Podman not found - bundled database unavailable",
                status="warn",
                fix="Install Podman to use the bundled PostgreSQL database.",
            )
        )

    from aap_migration import __version__

    checks.append(Check(f"aap-bridge {__version__}"))
    return checks


#: Set by the workspace launcher to the directory the user chose, because
#: inside the CLI container that directory is mounted at /work and reporting
#: the mount point tells the user about an implementation they did not pick.
_HOST_WORKSPACE_ENV = "AAP_BRIDGE_HOST_WORKSPACE"


def display_workspace(workspace: Path) -> str:
    """The workspace path as the user knows it."""
    return os.environ.get(_HOST_WORKSPACE_ENV) or str(workspace)


def check_workspace(workspace: Path) -> list[Check]:
    """Check that a workspace is present, configured, and safely permissioned."""
    checks: list[Check] = []
    shown = display_workspace(workspace)

    if not workspace.is_dir():
        return [
            Check(
                f"No workspace at {shown}",
                status="fail",
                fix="Run: aap-bridge init",
            )
        ]
    checks.append(Check(shown))

    config = workspace / "config" / "config.yaml"
    if config.is_file():
        checks.append(Check("Configuration found"))
    else:
        checks.append(
            Check(
                "Configuration missing",
                status="fail",
                fix="Run: aap-bridge init --force",
            )
        )

    env_file = workspace / ".env"
    if not env_file.is_file():
        checks.append(
            Check("Environment file missing", status="fail", fix="Run: aap-bridge init --force")
        )
    else:
        mode = env_file.stat().st_mode & 0o777
        if mode & 0o077:
            checks.append(
                Check(
                    f"Token file permissions are loose ({mode:o})",
                    status="warn",
                    fix=f"chmod 600 {env_file}",
                    fixable=True,
                )
            )
        else:
            checks.append(Check("Token file permissions are secure"))

    missing = [d for d in ("exports", "xformed", "reports", "logs") if not (workspace / d).is_dir()]
    if missing:
        checks.append(
            Check(
                f"Missing directories: {', '.join(missing)}",
                status="warn",
                fix="Recreate them",
                fixable=True,
            )
        )

    return checks


def installation_mode(workspace: Path) -> str:
    """How AAP Bridge was installed here: "cli", "container", or "unknown".

    Written by the installer into ``.aap-bridge-install``. Read rather than
    guessed, so the checks match the installation the user actually has.
    """
    record = workspace / ".aap-bridge-install"
    try:
        for line in record.read_text(errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "installation_mode" and value.strip() in ("cli", "container"):
                return value.strip()
    except OSError:
        pass
    return "unknown"


def _http_ok(url: str) -> bool:
    """Whether a URL answers at all. Any HTTP response means the service is up."""
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(url, timeout=_PROBE_TIMEOUT)  # noqa: S310 - fixed localhost URL
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def check_services(workspace: Path) -> list[Check]:
    """Check the services a container deployment runs.

    The database alone is what a migration needs; the API engine and Web UI are
    what the user installed. Reporting only the first answers a narrower
    question than "is my AAP Bridge healthy?".
    """
    api_port = os.environ.get("AAP_BRIDGE_API_PORT", "8000")
    ui_port = os.environ.get("AAP_BRIDGE_UI_PORT", "8080")

    checks = []
    if _http_ok(f"http://localhost:{api_port}/docs"):
        checks.append(Check("API engine responding"))
    else:
        checks.append(
            Check(
                "API engine not responding",
                status="fail",
                fix="Start it: aap-bridge start",
            )
        )

    if _http_ok(f"http://localhost:{ui_port}/"):
        checks.append(Check("Web UI responding"))
    else:
        checks.append(
            Check(
                "Web UI not responding",
                status="fail",
                fix="Start it: aap-bridge start",
            )
        )
    return checks


def check_database(db_url: str, workspace: Path | None = None) -> list[Check]:
    """Check that the migration state database is reachable.

    The repair hint depends on who owns the database: a bundled one can be
    started for the user, an external one can only be pointed at correctly.
    """
    if not db_url:
        return [Check("No database configured", status="fail", fix="Run: aap-bridge init --force")]

    try:
        from sqlalchemy import create_engine, text
    except ImportError:  # pragma: no cover - sqlalchemy is a hard dependency
        return [Check("SQLAlchemy unavailable", status="fail")]

    connect_args = {"connect_timeout": _PROBE_TIMEOUT} if db_url.startswith("postgres") else {}
    try:
        engine = create_engine(db_url, connect_args=connect_args)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        bundled = workspace is not None and (workspace / "compose.yml").is_file()
        if bundled:
            return [
                Check(
                    "Database not connected",
                    status="fail",
                    fix="Start the bundled database",
                    fixable=True,
                )
            ]
        return [
            Check(
                "Database not connected",
                status="fail",
                fix="Check MIGRATION_STATE_DB_PATH in .env",
            )
        ]
    return [Check("Database connected")]


#: Endpoints that answer only for an authenticated caller. Tried in order so
#: both the controller API and the 2.5+ gateway are covered.
_IDENTITY_PATHS = ("/api/v2/me/", "/api/gateway/v1/me/", "/api/controller/v2/me/")


def check_aap(url: str, token: str, verify_ssl: bool, label: str) -> Check:
    """Check that one AAP instance answers *and* accepts the token.

    Reachability alone is misleading: a TCP connection can succeed while the
    token is wrong, which would only surface much later in a migration. This
    probes an authenticated endpoint and distinguishes the two failures.
    """
    if not url:
        return Check(f"{label} AAP not configured", status="fail")

    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a hard dependency
        return Check(f"{label} AAP check unavailable", status="warn")

    base = url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    unauthorized = False

    with httpx.Client(verify=verify_ssl, timeout=_PROBE_TIMEOUT, follow_redirects=True) as client:
        for path in _IDENTITY_PATHS:
            try:
                response = client.get(f"{base}{path}", headers=headers)
            except Exception:
                # Network-level failure: no endpoint will answer, so stop here.
                return Check(
                    f"{label} AAP unreachable",
                    status="fail",
                    fix=f"Check the {label.lower()} URL in .env, and that the instance is running",
                )
            if response.status_code == 200:
                return Check(f"{label} AAP connected")
            if response.status_code in (401, 403):
                unauthorized = True

    if unauthorized:
        return Check(
            f"{label} AAP rejected the token",
            status="fail",
            fix=f"Check {label.upper()}__TOKEN in .env",
        )

    # Answered, but no identity endpoint matched: an unexpected shape rather
    # than a definite failure, so do not block on it.
    return Check(f"{label} AAP reachable, identity endpoint not found", status="warn")


def start_database(workspace: Path) -> bool:
    """Bring up the bundled PostgreSQL service. Returns True on success."""
    if shutil.which("podman") is None or not (workspace / "compose.yml").is_file():
        return False
    try:
        result = subprocess.run(
            ["podman", "compose", "up", "-d", "db"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def wait_for_database(db_url: str, workspace: Path | None = None, timeout: int = 90) -> bool:
    """Poll until the database accepts connections.

    ``podman compose up -d`` returns once the container has *started*, not once
    PostgreSQL is ready to serve. Reporting success on the compose exit code
    alone produces the contradiction "PostgreSQL running" immediately followed
    by "Database not reachable".

    Returns True when a connection succeeds before the timeout.
    """
    deadline = time.monotonic() + timeout
    delay = 1.0
    while True:
        if all(check.status == "ok" for check in check_database(db_url, workspace)):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)
