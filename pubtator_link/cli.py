"""Typer command-line interface for pubtator-link.

GeneFoundry Logging & CLI Standard v1: a single ``Typer`` app exposing
``serve`` / ``config`` / ``health`` / ``version``, plus the domain group
``embeddings backfill`` (embed an existing review corpus, #182). Streamable HTTP only — there
is no stdio transport and no bare-serve entry point. The server boots via
``pubtator-link serve`` in either the ``unified`` (FastAPI REST + MCP at
``/mcp``) or ``http`` (FastAPI REST only) transport.
"""

from __future__ import annotations

import asyncio
import signal
import time
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


embeddings_app = typer.Typer(no_args_is_help=True, help="Review-corpus embedding maintenance.")
app.add_typer(embeddings_app, name="embeddings")


@embeddings_app.command("backfill")
def embeddings_backfill(
    review_ids: list[str] | None = typer.Option(  # noqa: B008
        None, "--review-id", help="Review index to embed (repeatable)."
    ),
    all_reviews: bool = typer.Option(False, "--all", help="Embed every review index."),
    batch_size: int = typer.Option(
        settings.review_embedding_batch_size,
        "--batch-size",
        min=1,
        max=256,
        help="Passages per model call.",
    ),
    chunk_size: int = typer.Option(
        512, "--chunk-size", min=1, max=10000, help="Passages fetched per database round trip."
    ),
) -> None:
    """Embed missing or stale review passages. Idempotent and resumable: rerun to continue."""
    if bool(review_ids) == all_reviews:
        console.print("[red]Pass --review-id (one or more) or --all.[/red]")
        raise typer.Exit(code=2)
    configure_logging()
    raise typer.Exit(
        code=asyncio.run(_embeddings_backfill(review_ids or [], batch_size, chunk_size))
    )


async def _embeddings_backfill(review_ids: list[str], batch_size: int, chunk_size: int) -> int:
    import asyncpg

    from .api.routes.dependencies.resources import review_pool_kwargs
    from .api.routes.dependencies.review import load_embedding_provider
    from .repositories.review_rerag import PostgresReviewReragRepository
    from .services.review_context.embedding_backfill import backfill_review_passage_embeddings

    provider = load_embedding_provider()
    if provider is None:
        console.print(
            "[red]Embedding model unavailable[/red] (install the 'embeddings' extra and run "
            "`make embeddings-model`, or set PUBTATOR_LINK_REVIEW_EMBEDDING_MODEL_DIR)."
        )
        return 1
    pool = await asyncpg.create_pool(**{**review_pool_kwargs(), "min_size": 1, "max_size": 2})
    try:
        repository = PostgresReviewReragRepository(pool)
        if not review_ids:
            offset = 0
            while page := await repository.list_review_indexes(limit=200, offset=offset):
                review_ids.extend(item.review_id for item in page)
                offset += len(page)
        started, total, failed = time.monotonic(), 0, 0
        for index, review_id in enumerate(review_ids, start=1):

            def report(rid: str, count: int, index: int = index, base: int = total) -> None:
                rate = (base + count) / max(time.monotonic() - started, 1e-9)
                console.print(
                    f"[{index}/{len(review_ids)}] {rid}: {count} embedded "
                    f"(run total {base + count}, {rate:.1f} passages/s)"
                )

            result = await backfill_review_passage_embeddings(
                repository=repository,
                review_id=review_id,
                provider=provider,
                model_name=provider.model_name,
                embedding_dim=provider.dim,
                batch_size=batch_size,
                chunk_size=chunk_size,
                progress=report,
            )
            total += result.embedded_count
            if result.error is not None:
                failed += 1
                console.print(f"[red]{review_id}: {result.error}[/red]")
        console.print(
            f"Done: {total} passages embedded across {len(review_ids)} review(s), "
            f"{failed} failed, {time.monotonic() - started:.1f}s."
        )
        return 1 if failed else 0
    finally:
        await pool.close()


if __name__ == "__main__":
    app()
