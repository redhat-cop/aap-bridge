"""Shared console primitives for setup and diagnostic output.

Three status symbols carry the whole visual model, used consistently by the
installer scripts, ``aap-bridge init``, and ``aap-bridge doctor``:

===========  ==========================================
``✔``        Ready
``!``        Optional issue, or degraded capability
``✘``        Cannot continue
===========  ==========================================

Implementation detail (tool versions, resolved paths, package managers) belongs
behind :func:`detail`, which prints only in verbose mode. The default output
answers three questions: did it work, where are my files, what do I do next.
"""

from __future__ import annotations

import os

import click

OK = "✔"
WARN = "!"
FAIL = "✘"
STEP = "→"


def verbose_enabled() -> bool:
    """Whether implementation detail should be shown."""
    return os.environ.get("AAP_BRIDGE_VERBOSE", "0") not in ("0", "", "false", "no")


def heading(text: str) -> None:
    """Start a section, separated by a blank line."""
    click.echo()
    click.secho(text, bold=True)
    click.echo()


def ok(text: str) -> None:
    click.echo(f"  {click.style(OK, fg='green')} {text}")


def warn(text: str) -> None:
    click.echo(f"  {click.style(WARN, fg='yellow')} {text}")


def fail(text: str) -> None:
    click.echo(f"  {click.style(FAIL, fg='red')} {text}")


def step(text: str) -> None:
    click.echo(f"  {click.style(STEP, dim=True)} {text}")


def detail(text: str) -> None:
    """Print only when AAP_BRIDGE_VERBOSE is set.

    For anything a user does not need in order to act: resolved source paths,
    exact tool versions, package-manager choices.
    """
    if verbose_enabled():
        click.echo(f"  {click.style(text, dim=True)}")


def field(label: str, value: str, width: int = 20) -> None:
    """Print an aligned ``label  value`` pair inside a section."""
    click.echo(f"  {label.ljust(width)}{value}")


def command(text: str) -> None:
    """Print a command the user is expected to run."""
    click.echo(f"  {text}")
