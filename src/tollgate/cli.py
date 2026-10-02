"""Tollgate CLI (typer): serve, db, key, version."""

from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(help="Tollgate — local-first LLM gateway.", no_args_is_help=True)
key_app = typer.Typer(help="Manage virtual keys.", no_args_is_help=True)
db_app = typer.Typer(help="Database utilities.", no_args_is_help=True)
app.add_typer(key_app, name="key")
app.add_typer(db_app, name="db")


@app.command()
def version() -> None:
    """Print version."""
    typer.echo(f"tollgate {__version__}")


@app.command()
def serve(
    host: str = typer.Option(None, help="Bind host (default: settings)."),
    port: int = typer.Option(None, help="Bind port (default: settings)."),
) -> None:
    """Run the gateway + dashboard."""
    import uvicorn

    from .config import get_settings
    from .main import create_app

    settings = get_settings()
    bind_host = host or settings.host

    if bind_host not in ("127.0.0.1", "localhost", "::1"):
        typer.echo("⚠  LAN binding: the dashboard and admin API are now reachable from")
        typer.echo("   your network. Anyone with the admin token can manage Tollgate, so")
        typer.echo("   only do this on networks you trust (or use Tailscale). Proxy")
        typer.echo("   endpoints still require a valid tg-… virtual key.")
        the_port = port if port is not None else settings.port
        typer.echo(f"   Reachable at: http://{_lan_ip()}:{the_port}")
        typer.echo()

    the_app = create_app(settings)
    uvicorn.run(
        the_app,
        host=bind_host,
        port=port if port is not None else settings.port,
        log_level=settings.log_level.lower(),
    )


def _lan_ip() -> str:
    """Best-effort primary LAN address for the startup hint."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no packets sent; just picks a route
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "<this-machine-ip>"


@app.command()
def desktop() -> None:
    """Run the gateway in a native desktop window (pywebview)."""
    try:
        from .desktop.shell import run_desktop
    except ImportError:
        typer.echo(
            "pywebview is not installed. Run: uv sync --extra desktop "
            "(or: pip install 'tollgate[desktop]')"
        )
        raise typer.Exit(1) from None
    run_desktop()


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all pending migrations."""
    from .config import get_settings
    from .store import run_migrations

    settings = get_settings()
    run_migrations(settings.db_url)
    typer.echo(f"database up to date: {settings.db_path}")


@key_app.command("create")
def key_create(
    name: str = typer.Option("", "--name", help="Label for the key."),
    project: str = typer.Option(None, "--project", help="Project/tag."),
    expires_in_days: int = typer.Option(None, "--expires-in-days", help="Expiry."),
) -> None:
    """Create a virtual key; the full key is shown ONCE."""
    import asyncio

    from .auth.service import KeyService

    async def _run() -> None:
        from .config import get_settings
        from .main import create_app

        the_app = create_app(get_settings())
        svc = KeyService(the_app)
        key, plaintext = await svc.create(
            name=name, project=project, expires_in_days=expires_in_days
        )
        await the_app.state.engine.dispose()
        typer.echo(f"Virtual key created (id {key.id}):")
        typer.echo(f"  {plaintext}")
        typer.echo("Store it now — it will not be shown again.")

    asyncio.run(_run())


@key_app.command("list")
def key_list() -> None:
    """List virtual keys (prefix + status only — never the secret)."""
    import asyncio

    from sqlalchemy import select

    from .store.models import VirtualKey

    async def _run() -> None:
        from .config import get_settings
        from .main import create_app

        the_app = create_app(get_settings())
        async with the_app.state.session_factory() as session:
            rows = (await session.execute(select(VirtualKey))).scalars().all()
            for k in sorted(rows, key=lambda r: r.created_at):
                typer.echo(f"{k.prefix:<14} {k.status:<9} {k.name or '-'}")
        await the_app.state.engine.dispose()

    asyncio.run(_run())


@key_app.command("admin-token")
def key_admin_token() -> None:
    """Print the dashboard admin token, creating it on first use."""
    import asyncio
    import logging

    logging.getLogger("alembic").setLevel(logging.WARNING)

    async def _run() -> str | None:
        from .main import create_app, ensure_admin_token

        the_app = create_app(get_settings())
        token = await ensure_admin_token(the_app)
        await the_app.state.engine.dispose()
        return token

    from .config import get_settings

    token = asyncio.run(_run())
    settings = get_settings()
    if token:
        typer.echo(f"Admin token: {token}")
        typer.echo(f"Dashboard:   http://{settings.host}:{settings.port}")
    else:
        typer.echo("Could not determine the admin token.")


if __name__ == "__main__":
    app()


if __name__ == "__main__":
    app()
