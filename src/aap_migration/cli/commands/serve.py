import os

import click


@click.command()
@click.option("--host", default="0.0.0.0", help="Bind address")
@click.option("--port", default=8000, type=int, help="Bind port")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, reload: bool) -> None:
    """Start the AAP Bridge API server."""
    try:
        import uvicorn

        from aap_migration.api.app import create_app
    except ImportError:
        click.echo(
            "Error: API dependencies not installed. Install with: pip install '.[api]'",
            err=True,
        )
        raise SystemExit(1) from None

    db_url = os.environ.get("MIGRATION_STATE_DB_PATH", "")

    if not db_url:
        click.echo(
            "Warning: No database URL configured. Set MIGRATION_STATE_DB_PATH.",
            err=True,
        )
        db_url = "sqlite:///aap_bridge.db"

    click.echo(f"Starting AAP Bridge API server on {host}:{port}")

    if reload:
        os.environ["MIGRATION_STATE_DB_PATH"] = db_url
        uvicorn.run(
            "aap_migration.api.app:create_app",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
        return

    app = create_app(db_url=db_url)
    uvicorn.run(app, host=host, port=port, reload=False)
