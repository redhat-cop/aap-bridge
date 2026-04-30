"""
Decorators for CLI commands.

This module provides decorators for error handling, context passing,
and other common CLI patterns.
"""

import functools
from collections.abc import Callable

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.client.exceptions import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    StateError,
)
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


def pass_context(f: Callable) -> Callable:
    """
    Decorator to pass MigrationContext to command function.

    This is a convenience decorator that extracts the MigrationContext
    from Click's context and passes it as the first argument to the
    command function.

    Usage:
        @click.command()
        @pass_context
        def my_command(ctx: MigrationContext):
            print(ctx.config)
    """

    @click.pass_context
    @functools.wraps(f)
    def wrapper(click_ctx: click.Context, *args, **kwargs):
        migration_ctx: MigrationContext = click_ctx.obj
        return f(migration_ctx, *args, **kwargs)

    return wrapper


def handle_errors(f: Callable) -> Callable:
    """
    Decorator to handle common errors in CLI commands.

    This decorator catches common exceptions and converts them to
    user-friendly error messages with appropriate exit codes.

    Exit codes:
        0: Success
        1: General error
        2: Configuration error
        3: Authentication error
        4: API error
        5: State error
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)

        except click.exceptions.Exit:
            # Let Exit exceptions pass through (they're intentional exits)
            raise

        except click.ClickException:
            # Let ClickException pass through — it's an intentional user-facing error
            # already formatted by the command. main() will display it via e.show().
            raise

        except ConfigurationError as e:
            logger.error("Configuration error", error=str(e))
            click.echo(f"Configuration Error: {e}", err=True)
            click.echo(
                "\nPlease check your configuration file and ensure all required fields are set.",
                err=True,
            )
            raise click.exceptions.Exit(2) from e

        except AuthenticationError as e:
            logger.error("Authentication error", error=str(e))
            click.echo(f"Authentication Error: {e}", err=True)
            click.echo(
                "\nPlease verify your credentials and tokens in the configuration file.",
                err=True,
            )
            raise click.exceptions.Exit(3) from e

        except APIError as e:
            logger.error("API error", error=str(e))
            click.echo(f"API Error: {e}", err=True)
            if hasattr(e, "status_code") and e.status_code:
                click.echo(f"\nResponse status: {e.status_code}", err=True)
            raise click.exceptions.Exit(4) from e

        except StateError as e:
            logger.error("State error", error=str(e))
            click.echo(f"State Error: {e}", err=True)
            click.echo(
                "\nThere was an error accessing migration state. "
                "The database may be corrupted or inaccessible.",
                err=True,
            )
            raise click.exceptions.Exit(5) from e

        except Exception as e:
            logger.error("Unexpected error", error=str(e), exc_info=True)
            click.echo(f"Unexpected Error: {e}", err=True)
            click.echo(
                "\nAn unexpected error occurred. Please check the logs for details.",
                err=True,
            )
            raise click.exceptions.Exit(1) from e

    return wrapper


def requires_config(f: Callable) -> Callable:
    """
    Decorator to ensure configuration is loaded.

    This decorator checks that a configuration file has been provided
    and loads it before executing the command.
    """

    @functools.wraps(f)
    def wrapper(ctx: MigrationContext, *args, **kwargs):
        if ctx.config_path is None:
            click.echo(
                "Error: Configuration file required. Use --config option or set AAP_BRIDGE_CONFIG.",
                err=True,
            )
            raise click.exceptions.Exit(2)

        # Access config property to trigger loading and validation
        try:
            _ = ctx.config
        except Exception as e:
            click.echo(f"Error loading configuration: {e}", err=True)
            raise click.exceptions.Exit(2) from e

        return f(ctx, *args, **kwargs)

    return wrapper


def confirm_action(
    message: str = "Do you want to continue?",
    abort_message: str = "Operation cancelled.",
) -> Callable:
    """
    Decorator to prompt for confirmation before executing a command.

    Args:
        message: Confirmation prompt message
        abort_message: Message to show if user aborts

    Usage:
        @click.command()
        @confirm_action("This will delete all migration state. Continue?")
        def dangerous_command():
            # ... dangerous operation
    """

    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            # Skip confirmation if --yes flag is present
            ctx = click.get_current_context()
            if ctx.params.get("yes", False):
                return f(*args, **kwargs)

            if not click.confirm(message):
                click.echo(abort_message)
                raise click.exceptions.Exit(0)

            return f(*args, **kwargs)

        return wrapper

    return decorator
