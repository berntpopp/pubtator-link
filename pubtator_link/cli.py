"""Command-line interface for PubTator-Link."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .api.client import PubTator3Client
from .logging_config import configure_logging

# Add root directory to path for mcp_server import
sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp_server import main as mcp_main

from .server_manager import UnifiedServerManager
from .services.publication_service import PublicationService

# Initialize rich console
console = Console()


async def test_connection() -> bool:
    """Test connection to PubTator3 API."""
    logger = configure_logging()

    with console.status("[bold blue]Testing PubTator3 API connection...", spinner="dots"):
        async with PubTator3Client(logger=logger) as client:
            try:
                # Test with a simple entity search
                result = await client.autocomplete_entity("cancer", limit=1)
                logger.info("Connection test successful", result_count=len(result))

                console.print(
                    Panel(
                        "[bold green]:white_check_mark: PubTator3 API connection successful!",
                        title="Connection Test",
                        border_style="green",
                    )
                )

                if result:
                    console.print(f"[dim]Found {len(result)} entity results for 'cancer'[/dim]")

                return True
            except Exception as e:
                logger.error("Connection test failed", error=str(e))

                console.print(
                    Panel(
                        f"[bold red]:x: Connection failed: {str(e)}",
                        title="Connection Test",
                        border_style="red",
                    )
                )

                return False


async def search_entities(query: str, concept: Optional[str] = None, limit: int = 10) -> None:
    """Search for entity IDs."""
    logger = configure_logging()

    search_desc = f"[bold blue]Searching for entities: '{query}'"
    if concept:
        search_desc += f" (type: {concept})"

    with console.status(search_desc, spinner="dots"):
        async with PubTator3Client(logger=logger) as client:
            try:
                result = await client.autocomplete_entity(query=query, concept=concept, limit=limit)

                if not result:
                    console.print(f"[yellow]No entities found for query: '{query}'[/yellow]")
                    return

                # Create a table for results
                table = Table(title=f"Entity Search Results for '{query}'")
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("Name", style="green")
                table.add_column("Type", style="magenta")
                table.add_column("Score", style="yellow", justify="right")

                # Handle both list and dict response formats
                entities: list[dict[str, Any]] = []
                if isinstance(result, list):
                    entities = result  # type: ignore[assignment]
                elif isinstance(result, dict):
                    entities = result.get("results", [])  # type: ignore[assignment]
                else:
                    entities = []

                for entity in entities[:limit]:
                    entity_id = entity.get("_id", entity.get("identifier", "N/A"))
                    name = entity.get("name", "Unknown")
                    entity_type = entity.get("biotype", entity.get("type", concept or "Unknown"))
                    score = entity.get("score", 0.0)

                    table.add_row(
                        entity_id,
                        name[:60] + "..." if len(name) > 60 else name,
                        entity_type,
                        f"{score:.2f}" if isinstance(score, (int, float)) else str(score),
                    )

                console.print(table)
                console.print(
                    f"[dim]Found {len(entities)} entities (showing top {min(len(entities), limit)})[/dim]"
                )

            except Exception as e:
                logger.error("Entity search failed", error=str(e))
                console.print(
                    Panel(
                        f"[bold red]:x: Entity search failed: {str(e)}",
                        title="Search Error",
                        border_style="red",
                    )
                )
                sys.exit(1)


async def search_publications(query: str, page: int = 1) -> None:
    """Search for publications."""
    logger = configure_logging()

    with console.status(
        f"[bold blue]Searching publications: '{query}' (page {page})", spinner="dots"
    ):
        async with PubTator3Client(logger=logger) as client:
            try:
                service = PublicationService(client, logger)
                result = await service.search_publications(text=query, page=page)

                if not result.results:
                    console.print(f"[yellow]No publications found for query: '{query}'[/yellow]")
                    return

                # Display search summary
                console.print(
                    Panel(
                        f"[bold green]Found {result.total_results:,} publications",
                        title=f"Search Results for '{query}'",
                        subtitle=f"Page {result.page}/{result.total_pages} ({result.per_page} per page)",
                        border_style="green",
                    )
                )

                # Display each publication
                for i, pub in enumerate(result.results, 1):
                    # Create publication panel
                    pub_content = []
                    pub_content.append(f"[bold cyan]PMID: {pub.pmid}[/bold cyan]")

                    if pub.authors:
                        authors_str = ", ".join(pub.authors[:3])  # Show first 3 authors
                        if len(pub.authors) > 3:
                            authors_str += f" et al. ({len(pub.authors)} total)"
                        pub_content.append(f"[dim]Authors: {authors_str}[/dim]")

                    if pub.journal:
                        pub_content.append(f"[dim]Journal: {pub.journal}[/dim]")

                    if pub.pub_date:
                        pub_content.append(f"[dim]Date: {pub.pub_date}[/dim]")

                    if pub.abstract:
                        # Truncate long abstracts
                        abstract = (
                            pub.abstract[:300] + "..." if len(pub.abstract) > 300 else pub.abstract
                        )
                        pub_content.append(f"\n[white]{abstract}[/white]")

                    if pub.annotations:
                        entities = []
                        for ann in pub.annotations[:5]:  # Show first 5 annotations
                            entity_type = ann.get("type", "Unknown")
                            entity_text = ann.get("text", "")
                            entities.append(f"[{entity_type}] {entity_text}")

                        if entities:
                            pub_content.append(f"\n[dim]Entities: {', '.join(entities)}[/dim]")
                            if len(pub.annotations) > 5:
                                pub_content.append(
                                    f"[dim]... and {len(pub.annotations) - 5} more entities[/dim]"
                                )

                    console.print(
                        Panel(
                            "\n".join(pub_content),
                            title=f"[bold]{i}. {pub.title[:80] + '...' if len(pub.title) > 80 else pub.title}[/bold]",
                            border_style="blue",
                            padding=(1, 2),
                        )
                    )

                # Show navigation hint
                if result.total_pages > 1:
                    console.print(f"\n[dim]Use --page {page + 1} to see next page[/dim]")

            except Exception as e:
                logger.error("Publication search failed", error=str(e))
                console.print(
                    Panel(
                        f"[bold red]:x: Publication search failed: {str(e)}",
                        title="Search Error",
                        border_style="red",
                    )
                )
                sys.exit(1)


async def export_publications(pmids: str, format: str = "biocjson", full: bool = False) -> None:
    """Export publication annotations."""
    logger = configure_logging()
    pmid_list = [pmid.strip() for pmid in pmids.split(",")]

    export_desc = f"[bold blue]Exporting {len(pmid_list)} publication(s) in {format} format"
    if full:
        export_desc += " (full text)"

    with console.status(export_desc, spinner="dots"):
        async with PubTator3Client(logger=logger) as client:
            try:
                service = PublicationService(client, logger)
                result = await service.export_publications(
                    pmids=pmid_list, format=format, full=full
                )

                if not result.export_data:
                    console.print(
                        f"[yellow]No documents found for PMIDs: {', '.join(pmid_list)}[/yellow]"
                    )
                    return

                # Display export summary
                console.print(
                    Panel(
                        f"[bold green]Successfully exported {result.count} document(s)",
                        title=f"Export Complete ({format.upper()})",
                        subtitle=f"PMIDs: {', '.join(pmid_list)}",
                        border_style="green",
                    )
                )

                # Display each document
                # Extract documents from export_data
                documents = result.export_data.get("documents", []) if isinstance(result.export_data, dict) else []
                for i, doc in enumerate(documents, 1):
                    if isinstance(doc, dict):
                        # Handle dictionary format
                        pmid = doc.get("id", f"Document {i}")
                        title = "[Document Content]"

                        # Try to extract title from passages if available
                        if "passages" in doc and doc["passages"]:
                            first_passage = doc["passages"][0]
                            if "text" in first_passage:
                                title = (
                                    first_passage["text"][:100] + "..."
                                    if len(first_passage["text"]) > 100
                                    else first_passage["text"]
                                )

                        # Count annotations
                        annotation_count = 0
                        if "passages" in doc:
                            for passage in doc["passages"]:
                                if "annotations" in passage:
                                    annotation_count += len(passage["annotations"])

                        doc_info = [
                            f"[bold cyan]PMID: {pmid}[/bold cyan]",
                            f"[dim]Format: {format}[/dim]",
                            f"[dim]Annotations: {annotation_count}[/dim]",
                        ]

                        if full:
                            doc_info.append("[dim]Full text: ✓[/dim]")

                        console.print(
                            Panel(
                                "\n".join(doc_info),
                                title=f"[bold]{i}. {title}[/bold]",
                                border_style="blue",
                                padding=(1, 1),
                            )
                        )

                        # Display JSON preview for biocjson format
                        if format == "biocjson":
                            json_preview = (
                                json.dumps(doc, indent=2)[:300] + "..."
                                if len(json.dumps(doc)) > 300
                                else json.dumps(doc, indent=2)
                            )
                            syntax = Syntax(
                                json_preview, "json", theme="monokai", line_numbers=False
                            )
                            console.print(Panel(syntax, title="JSON Preview", border_style="dim"))

                    else:
                        # Handle object format
                        console.print(
                            Panel(
                                f"[bold cyan]PMID: {getattr(doc, 'pmid', f'Document {i}')}[/bold cyan]\n"
                                f"[dim]Format: {format}[/dim]\n"
                                f"[dim]Type: {type(doc).__name__}[/dim]",
                                title=f"[bold]{i}. Document Export[/bold]",
                                border_style="blue",
                            )
                        )

                # Show data size info
                total_data = (
                    json.dumps(result.export_data)
                    if hasattr(result, "export_data")
                    else str(result)
                )
                data_size = len(total_data.encode("utf-8"))
                size_str = f"{data_size:,} bytes"
                if data_size > 1024:
                    size_str += f" ({data_size / 1024:.1f} KB)"
                if data_size > 1024 * 1024:
                    size_str += f" ({data_size / (1024 * 1024):.1f} MB)"

                console.print(f"\n[dim]Total export size: {size_str}[/dim]")

            except Exception as e:
                logger.error("Publication export failed", error=str(e))
                console.print(
                    Panel(
                        f"[bold red]:x: Export failed: {str(e)}",
                        title="Export Error",
                        border_style="red",
                    )
                )
                sys.exit(1)


async def serve_http(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Start HTTP-only server."""
    logger = configure_logging()
    manager = UnifiedServerManager(logger=logger)

    try:
        logger.info("Starting HTTP server", host=host, port=port, reload=reload)
        await manager.start_http_only_server(host=host, port=port, reload=reload)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


async def serve_unified(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Start unified server (HTTP + MCP)."""
    logger = configure_logging()
    manager = UnifiedServerManager(logger=logger)

    try:
        logger.info("Starting unified server", host=host, port=port, reload=reload)
        await manager.start_unified_server(host=host, port=port, reload=reload)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


def serve_mcp_only() -> None:
    """Start MCP-only server."""
    logger = configure_logging()

    try:
        logger.info("Starting MCP server")
        mcp_main()
    except KeyboardInterrupt:
        logger.info("MCP server stopped by user")
    except Exception as e:
        logger.error("MCP server error", error=str(e))
        sys.exit(1)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="PubTator-Link CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Test connection command
    subparsers.add_parser("test", help="Test connection to PubTator3 API")

    # Server commands
    serve_parser = subparsers.add_parser("serve", help="Start server")
    serve_subparsers = serve_parser.add_subparsers(dest="serve_mode", help="Server modes")

    # HTTP server
    http_parser = serve_subparsers.add_parser("http", help="Start HTTP-only server")
    http_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    http_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    http_parser.add_argument(
        "--reload", action="store_true", help="Enable hot reloading for development"
    )

    # Unified server
    unified_parser = serve_subparsers.add_parser(
        "unified", help="Start unified server (HTTP + MCP)"
    )
    unified_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    unified_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    unified_parser.add_argument(
        "--reload", action="store_true", help="Enable hot reloading for development"
    )

    # MCP server
    serve_subparsers.add_parser("mcp", help="Start MCP-only server")

    # Entity search command
    entity_parser = subparsers.add_parser("entities", help="Search for entity IDs")
    entity_parser.add_argument("query", help="Search query")
    entity_parser.add_argument(
        "--concept",
        choices=["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"],
        help="Filter by bioconcept type",
    )
    entity_parser.add_argument("--limit", type=int, default=10, help="Maximum results")

    # Publication search command
    search_parser = subparsers.add_parser("search", help="Search publications")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--page", type=int, default=1, help="Page number")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export publication annotations")
    export_parser.add_argument("pmids", help="Comma-separated PMIDs")
    export_parser.add_argument(
        "--format",
        choices=["pubtator", "biocxml", "biocjson"],
        default="biocjson",
        help="Export format",
    )
    export_parser.add_argument("--full", action="store_true", help="Include full text")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Run async command
    if args.command == "test":
        success = asyncio.run(test_connection())
        sys.exit(0 if success else 1)
    elif args.command == "serve":
        if not args.serve_mode:
            serve_parser.print_help()
            return

        if args.serve_mode == "http":
            asyncio.run(serve_http(args.host, args.port, getattr(args, "reload", False)))
        elif args.serve_mode == "unified":
            asyncio.run(serve_unified(args.host, args.port, getattr(args, "reload", False)))
        elif args.serve_mode == "mcp":
            serve_mcp_only()
    elif args.command == "entities":
        asyncio.run(search_entities(args.query, args.concept, args.limit))
    elif args.command == "search":
        asyncio.run(search_publications(args.query, args.page))
    elif args.command == "export":
        asyncio.run(export_publications(args.pmids, args.format, args.full))


if __name__ == "__main__":
    main()
