"""Login service commands. Management never opens the database or secret store."""

from pathlib import Path

import typer

from .service import ServiceError, ServiceManager, log_path, make_spec

app = typer.Typer(help="Run Tollgate in the background at sign-in.", no_args_is_help=True)


@app.command()
def install(
    host: str = typer.Option(None, help="Persist a bind host override."),
    port: int = typer.Option(None, min=1, max=65535, help="Persist a port override."),
    data_dir: Path = typer.Option(None, help="Persist a data directory override."),
    working_directory: Path = typer.Option(
        None, "--working-directory", help="Directory containing .env (default: current directory)."
    ),
) -> None:
    """Install/update for this user and start now; no administrator rights needed."""
    try:
        manager = ServiceManager()
        spec = make_spec(
            host=host, port=port, data_dir=data_dir, working_directory=working_directory
        )
        manager.install(spec)
    except (ServiceError, OSError) as exc:
        typer.echo(f"Service installation failed: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo("Tollgate is installed to start at sign-in. Start requested.")
    typer.echo(f"Working directory: {spec.working_directory}")
    typer.echo(f"Logs: {log_path()}")
    typer.echo("Check startup with: tollgate service status")
    typer.echo("Shell environment is not saved; use .env or the install options for overrides.")


def _manage(action: str) -> None:
    try:
        manager = ServiceManager()
        result = getattr(manager, action)()
    except (ServiceError, OSError) as exc:
        typer.echo(f"Service {action} failed: {exc}", err=True)
        raise typer.Exit(1) from None
    if action == "status":
        typer.echo(f"Tollgate: {result}")
        typer.echo(f"Logs: {log_path()}")
    elif action == "uninstall":
        typer.echo("Tollgate login service removed. Data and logs are preserved.")
    else:
        typer.echo(f"Service {action} requested. Check with: tollgate service status")


@app.command()
def start() -> None:
    """Start the installed service now."""
    _manage("start")


@app.command()
def stop() -> None:
    """Stop now; automatic startup at the next sign-in remains enabled."""
    _manage("stop")


@app.command()
def restart() -> None:
    """Restart the installed service (for example, after an update)."""
    _manage("restart")


@app.command()
def status() -> None:
    """Show the OS manager's state and log location."""
    _manage("status")


@app.command()
def uninstall() -> None:
    """Stop and remove automatic startup, keeping all user data."""
    _manage("uninstall")
