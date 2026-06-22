import subprocess
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt


def run_command(args: list[str], ctx: Any = None) -> None:
    """Run a CLI command in a subprocess."""
    # Use the same executable entry point
    cmd = [sys.argv[0]]

    # Pass config file if present in context - insert BEFORE subcommand args
    if ctx and ctx.obj and ctx.obj.config_path:
        cmd.extend(["--config", str(ctx.obj.config_path)])

    # Forward organization scope from context when set
    if ctx and ctx.obj and getattr(ctx.obj, "organization", None):
        cmd.extend(["--organization", str(ctx.obj.organization)])

    # Add subcommand and its args
    cmd.extend(args)

    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print(f"Error running command: {e}")


def _prompt_organization_scope(ctx: Any, console: Console) -> None:
    """Optionally set single-organization scope on the migration context."""
    if not ctx or not ctx.obj:
        return

    current = getattr(ctx.obj, "organization", None)
    if current:
        console.print(f"[dim]Organization scope: {current}[/dim]")
        if Prompt.ask("Change organization scope?", choices=["y", "n"], default="n") == "n":
            return

    org = Prompt.ask(
        "Organization name (leave blank for all organizations)",
        default="",
    ).strip()
    ctx.obj.organization = org or None
    if ctx.obj.organization:
        console.print(f"[green]Scoped to organization:[/green] {ctx.obj.organization}")
    else:
        console.print("[dim]No organization scope (full platform migration)[/dim]")


def interactive_menu(ctx: Any) -> None:
    """Display interactive menu for AAP Bridge."""
    console = Console()

    while True:
        org_label = ""
        if ctx and ctx.obj and getattr(ctx.obj, "organization", None):
            org_label = f"\n[dim]Organization scope: {ctx.obj.organization}[/dim]"

        console.clear()
        console.print(
            Panel.fit(
                "[bold cyan]AAP Bridge[/bold cyan]"
                f"{org_label}\n\n"
                "0. Cleanup\n"
                "1. Prep Phase (Discover & Schema)\n"
                "2. Export\n"
                "3. Transform\n"
                "4. Import Phase 1 (Base Resources)\n"
                "5. Import Phase 2 (Patch Projects + Automation)\n"
                "6. Full Migrate (Prep → Export → Transform → Import)\n"
                "o. Set organization scope\n"
                "q. quit",
                title="Main Menu",
                border_style="blue",
            )
        )

        choice = Prompt.ask(
            "Select an option",
            choices=["0", "1", "2", "3", "4", "5", "6", "o", "q"],
            default="q",
        )

        if choice.lower() == "q":
            break

        console.print()  # Spacer

        if choice == "o":
            _prompt_organization_scope(ctx, console)
        elif choice == "0":
            run_command(["cleanup"], ctx)
        elif choice == "1":
            run_command(["prep"], ctx)
        elif choice == "2":
            _prompt_organization_scope(ctx, console)
            run_command(["export", "-y"], ctx)
        elif choice == "3":
            _prompt_organization_scope(ctx, console)
            run_command(["transform", "-y"], ctx)
        elif choice == "4":
            run_command(["import", "--phase", "phase1", "-y"], ctx)
        elif choice == "5":
            run_command(["import", "--phase", "phase2", "-y"], ctx)
        elif choice == "6":
            _prompt_organization_scope(ctx, console)
            run_command(["migrate"], ctx)

        Prompt.ask("\nPress Enter to return to menu...")
