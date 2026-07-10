"""Typer command-line interface for pubtator-link.

GeneFoundry Logging & CLI Standard v1: a single ``Typer`` app exposing
``serve`` / ``config`` / ``health`` / ``version``. Streamable HTTP only — there
is no stdio transport and no bare-serve entry point. The server boots via
``pubtator-link serve`` in either the ``unified`` (FastAPI REST + MCP at
``/mcp``) or ``http`` (FastAPI REST only) transport.
"""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING

import httpx
import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import settings
from .logging_config import configure_logging

if TYPE_CHECKING:
    from types import FrameType

app = typer.Typer(
    name="pubtator-link",
    add_completion=False,
    no_args_is_help=True,
    help="pubtator-link: an MCP/API server grounding biomedical literature work in PubTator3.",
)
console = Console()


async def _serve(host: str, port: int, *, unified: bool, reload: bool) -> None:
    """Run the unified or HTTP-only server until interrupted."""
    # Imported lazily so `--help`, `version`, etc. don't pull in uvicorn/fastmcp.
    from .server_manager import UnifiedServerManager

    logger = configure_logging()
    manager = UnifiedServerManager(logger=logger)

    shutdown_task: asyncio.Task[None] | None = None

    def _signal(signum: int, _frame: FrameType | None) -> None:
        nonlocal shutdown_task
        logger.info("Received shutdown signal", signal=signum)
        if shutdown_task is None or shutdown_task.done():
            shutdown_task = asyncio.create_task(manager.shutdown())

    signal.signal(signal.SIGINT, _signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal)

    try:
        if unified:
            await manager.start_unified_server(host=host, port=port, reload=reload)
        else:
            await manager.start_http_only_server(host=host, port=port, reload=reload)
    finally:
        await manager.shutdown()


def _run_server(*, transport: str, host: str, port: int, unified: bool, reload: bool) -> None:
    """Thin seam around :func:`asyncio.run` so tests can intercept the boot."""
    asyncio.run(_serve(host, port, unified=unified, reload=reload))


@app.command()
def serve(
    transport: str = typer.Option(
        "unified",
        "--transport",
        help="Transport mode: 'unified' (REST + MCP/HTTP) or 'http' (REST only).",
    ),
    host: str = typer.Option(settings.host, "--host", help="Host to bind to."),
    port: int = typer.Option(settings.port, "--port", help="Port to bind to."),
    mcp_path: str = typer.Option(settings.mcp_path, "--mcp-path", help="MCP endpoint path."),
    log_level: str = typer.Option(settings.log_level, "--log-level", help="Logging level."),
    disable_docs: bool = typer.Option(
        False, "--disable-docs", help="Disable API documentation endpoints."
    ),
    dev: bool = typer.Option(False, "--dev", help="Development mode (enable auto-reload)."),
) -> None:
    """Start the pubtator-link server (Streamable HTTP only)."""
    if transport not in ("unified", "http"):
        console.print(
            f"[red]Invalid transport '{transport}'.[/red] Choose 'unified' or 'http' "
            "(stdio is not supported)."
        )
        raise typer.Exit(code=2)

    try:
        settings.validate_write_boundary_for_host(host)
    except ValueError as exc:
        console.print(f"[red]Refusing unsafe MCP bind:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    settings.transport = transport  # type: ignore[assignment]
    settings.host = host
    settings.port = port
    settings.mcp_path = mcp_path
    settings.log_level = log_level
    settings.enable_docs = not disable_docs

    console.print(
        f"[green]Starting pubtator-link[/green] transport={transport} "
        f"host={host} port={port} mcp_path={settings.mcp_path}"
    )
    _run_server(
        transport=transport,
        host=host,
        port=port,
        unified=transport == "unified",
        reload=dev,
    )


@app.command()
def config(
    validate: bool = typer.Option(False, "--validate", help="Validate the configuration."),
) -> None:
    """Show (and optionally validate) the resolved configuration."""
    table = Table(title="pubtator-link configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("transport", settings.transport)
    table.add_row("host", settings.host)
    table.add_row("port", str(settings.port))
    table.add_row("mcp_path", settings.mcp_path)
    table.add_row("log_level", settings.log_level)
    table.add_row("log_format", settings.log_format)
    table.add_row("api_base_url", settings.api_base_url)
    table.add_row("api_timeout", str(settings.api_timeout))
    table.add_row("rate_limit_per_second", str(settings.rate_limit_per_second))
    table.add_row("mcp_profile", settings.mcp_profile)
    console.print(table)

    if validate:
        if not 1 <= settings.port <= 65535:
            console.print("[red]Invalid port number[/red]")
            raise typer.Exit(code=1)
        if not settings.mcp_path.startswith("/"):
            console.print("[red]MCP path must start with '/'[/red]")
            raise typer.Exit(code=1)
        console.print("[green]Configuration is valid[/green]")


@app.command()
def health(
    url: str = typer.Option(
        "http://127.0.0.1:8000", "--url", help="Base URL of the server to probe."
    ),
) -> None:
    """Check a running server's /health endpoint."""
    try:
        response = httpx.get(f"{url.rstrip('/')}/health", timeout=5)
    except httpx.HTTPError as exc:
        console.print(f"[red]Failed to connect to server:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if response.status_code != 200:
        console.print(f"[red]Server returned status {response.status_code}[/red]")
        raise typer.Exit(code=1)

    data = response.json()
    console.print("[green]Server is healthy[/green]")
    console.print(f"status:    {data.get('status', 'unknown')}")
    console.print(f"version:   {data.get('version', 'unknown')}")
    console.print(f"transport: {data.get('transport', 'unknown')}")


@app.command()
def version() -> None:
    """Print the installed pubtator-link version."""
    console.print(f"pubtator-link {__version__}")


if __name__ == "__main__":
    app()
