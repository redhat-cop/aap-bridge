"""
Utility functions for CLI commands.

This module provides helper functions for common CLI operations like
formatting output, progress tracking, and validation.
"""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()


def echo_success(message: str) -> None:
    """Print success message in green."""
    click.secho(f"✓ {message}", fg="green")


def echo_error(message: str) -> None:
    """Print error message in red."""
    click.secho(f"✗ {message}", fg="red", err=True)


def echo_warning(message: str) -> None:
    """Print warning message in yellow."""
    click.secho(f"⚠ {message}", fg="yellow")


def echo_info(message: str) -> None:
    """Print info message in blue."""
    click.secho(f"ℹ {message}", fg="blue")


def echo_step_complete(message: str) -> None:
    """Print completed step with green checkmark."""
    click.secho(f"✓ {message}", fg="green")


def echo_step_running(message: str) -> None:
    """Print running/in-progress step with cyan double colon."""
    click.secho(f":: {message}", fg="cyan")


def echo_step_pending(message: str) -> None:
    """Print pending step with bullet point."""
    click.secho(f"• {message}", fg="white")


@contextmanager
def step_progress(message: str) -> Generator[None, None, None]:
    """Context manager with live spinner for step progress.

    Shows a Rich spinner with message while the context is active,
    then shows "✓ message" on success or "✗ message" on failure.

    Args:
        message: The step description to display

    Example:
        with step_progress("Connecting to servers"):
            await client.ping()
        # Output: [spinner] Connecting to servers... → ✓ Connecting to servers
    """
    from rich.status import Status

    status = Status(f"[cyan]{message}...[/cyan]", spinner="dots", console=console)
    status.start()

    try:
        yield
        status.stop()
        console.print(f"[green]✓[/green] {message}")
    except Exception:
        status.stop()
        console.print(f"[red]✗[/red] {message}")
        raise


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "2h 30m 15s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)

    if minutes < 60:
        return f"{minutes}m {remaining_seconds}s"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    return f"{hours}h {remaining_minutes}m {remaining_seconds}s"


def format_timestamp(dt: datetime) -> str:
    """
    Format timestamp in human-readable format.

    Args:
        dt: Datetime object

    Returns:
        Formatted timestamp string
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_count(count: int) -> str:
    """
    Format large numbers with thousands separator.

    Args:
        count: Number to format

    Returns:
        Formatted number (e.g., "1,234,567")
    """
    return f"{count:,}"


def print_table(
    title: str,
    columns: list[str],
    rows: list[list[Any]],
    show_header: bool = True,
) -> None:
    """
    Print a formatted table using rich.

    Args:
        title: Table title
        columns: Column headers
        rows: List of row data
        show_header: Whether to show header row
    """
    table = Table(title=title, show_header=show_header)

    # Add columns
    for col in columns:
        table.add_column(col)

    # Add rows
    for row in rows:
        table.add_row(*[str(cell) for cell in row])

    console.print(table)


def print_stats(stats: dict[str, Any], title: str = "Statistics") -> None:
    """
    Print migration statistics in a formatted table.

    Args:
        stats: Dictionary of statistics
        title: Table title
    """
    rows = [[key.replace("_", " ").title(), str(value)] for key, value in stats.items()]
    print_table(title, ["Metric", "Value"], rows)


def create_progress_bar(description: str = "Processing") -> Progress:
    """
    Create a progress bar with standard formatting.

    Args:
        description: Description text for progress bar

    Returns:
        Rich Progress object
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    )


def validate_path(
    path: Path,
    must_exist: bool = False,
    must_be_file: bool = False,
    must_be_dir: bool = False,
) -> None:
    """
    Validate file or directory path.

    Args:
        path: Path to validate
        must_exist: Whether path must exist
        must_be_file: Whether path must be a file
        must_be_dir: Whether path must be a directory

    Raises:
        click.BadParameter: If validation fails
    """
    if must_exist and not path.exists():
        raise click.BadParameter(f"Path does not exist: {path}")

    if must_be_file and not path.is_file():
        raise click.BadParameter(f"Path is not a file: {path}")

    if must_be_dir and not path.is_dir():
        raise click.BadParameter(f"Path is not a directory: {path}")


def confirm_overwrite(path: Path, force: bool = False) -> bool:
    """
    Confirm overwrite of existing file.

    Args:
        path: Path to check
        force: Skip confirmation if True

    Returns:
        True if should proceed, False otherwise
    """
    if not path.exists():
        return True

    if force:
        return True

    return click.confirm(f"File {path} already exists. Overwrite?")


def confirm_overwrite_directory(
    path: Path,
    *,
    force: bool = False,
    yes: bool = False,
    message: str | None = None,
) -> bool:
    """Confirm overwriting a directory that already contains migration data.

    Empty directories (e.g. volume mount points after cleanup) do not prompt.
    """
    from aap_migration.utils.directories import directory_has_contents

    if not directory_has_contents(path):
        return True

    if force or yes:
        return True

    prompt = message or f"Directory {path} exists. Overwrite?"
    return click.confirm(prompt)


def load_json_or_yaml(path: Path) -> dict[str, Any]:
    """
    Load JSON or YAML file based on extension.

    Args:
        path: Path to file

    Returns:
        Parsed data

    Raises:
        click.BadParameter: If file format is unsupported
    """
    import json

    import yaml

    suffix = path.suffix.lower()

    if suffix == ".json":
        with open(path) as f:
            return json.load(f)

    elif suffix in [".yaml", ".yml"]:
        with open(path) as f:
            return yaml.safe_load(f)

    else:
        raise click.BadParameter(f"Unsupported file format: {suffix}. Use .json, .yaml, or .yml")
