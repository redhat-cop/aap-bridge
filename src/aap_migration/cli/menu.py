import subprocess
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from aap_migration.resources import get_version_path


def run_command(args: list[str], ctx: Any = None) -> None:
    """Run a CLI command in a subprocess."""
    # Use the same executable entry point
    cmd = [sys.argv[0]]

    # Pass config file if present in context - insert BEFORE subcommand args
    if ctx and ctx.obj and ctx.obj.config_path:
        cmd.extend(["--config", str(ctx.obj.config_path)])

    # Add subcommand and its args
    cmd.extend(args)

    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print(f"Error running command: {e}")


def interactive_menu(ctx: Any) -> None:
    """Display interactive menu for AAP Bridge."""
    console = Console()

    while True:
        console.clear()
        console.print(
            Panel.fit(
                "[bold cyan]AAP Bridge[/bold cyan]\n\n"
                "0. Cleanup\n"
                "1. Prep Phase (Discover & Schema)\n"
                "2. Export (All)\n"
                "3. Transform (All)\n"
                "4. Import Phase 1 (Base Resources)\n"
                "5. Import Phase 2 (Patch Projects + Automation)\n"
                "q. quit",
                title="Main Menu",
                border_style="blue",
            )
        )

        choice = Prompt.ask(
            "Select an option", choices=["0", "1", "2", "3", "4", "5", "q"], default="q"
        )

        if choice.lower() == "q":
            break

        console.print()  # Spacer

        if choice == "0":
            run_command(["cleanup"], ctx)
        elif choice == "1":
            args = ["prep"]
            if ctx and ctx.obj:
                config = ctx.obj.config
                source = config.source.version
                target = config.target.version
                if source and target and get_version_path(source, target) is None:
                    console.print(
                        f"[yellow]Untested migration path: {source} → {target}. "
                        "Discovery does not establish migration compatibility.[/yellow]"
                    )
                    if not Confirm.ask("Run discovery only for this untested path?", default=False):
                        continue
                    args.append("--allow-untested-path")
            run_command(args, ctx)
        elif choice == "2":
            run_command(["export"], ctx)
        elif choice == "3":
            run_command(["transform"], ctx)
        elif choice == "4":
            run_command(["import", "--phase", "phase1"], ctx)
        elif choice == "5":
            run_command(["import", "--phase", "phase2"], ctx)

        Prompt.ask("\nPress Enter to return to menu...")
