"""Command-line interface for PubTator-Link."""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from .api.client import PubTator3Client
from .logging_config import configure_logging

# Add root directory to path for mcp_server import
sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp_server import main as mcp_main

from .server_manager import UnifiedServerManager
from .services.publication_service import PublicationService


async def test_connection():
    """Test connection to PubTator3 API."""
    logger = configure_logging()

    async with PubTator3Client(logger=logger) as client:
        try:
            # Test with a simple entity search
            result = await client.autocomplete_entity("cancer", limit=1)
            logger.info("Connection test successful", result_count=len(result))
            return True
        except Exception as e:
            logger.error("Connection test failed", error=str(e))
            return False


async def search_entities(query: str, concept: Optional[str] = None, limit: int = 10):
    """Search for entity IDs."""
    logger = configure_logging()

    async with PubTator3Client(logger=logger) as client:
        try:
            result = await client.autocomplete_entity(query=query, concept=concept, limit=limit)

            if isinstance(result, dict) and "content" in result:
                pass
            else:
                pass

        except Exception as e:
            logger.error("Entity search failed", error=str(e))
            sys.exit(1)


async def search_publications(query: str, page: int = 1):
    """Search for publications."""
    logger = configure_logging()

    async with PubTator3Client(logger=logger) as client:
        try:
            service = PublicationService(client, logger)
            result = await service.search_publications(text=query, page=page)

            for _i, pub in enumerate(result.results, 1):
                if pub.abstract:
                    pass

        except Exception as e:
            logger.error("Publication search failed", error=str(e))
            sys.exit(1)


async def export_publications(pmids: str, format: str = "biocjson", full: bool = False):
    """Export publication annotations."""
    logger = configure_logging()
    pmid_list = [pmid.strip() for pmid in pmids.split(",")]

    async with PubTator3Client(logger=logger) as client:
        try:
            service = PublicationService(client, logger)
            result = await service.export_publications(pmids=pmid_list, format=format, full=full)

            for _i, doc in enumerate(result.documents, 1):
                if isinstance(doc, dict):
                    pass
                else:
                    pass

        except Exception as e:
            logger.error("Publication export failed", error=str(e))
            sys.exit(1)


async def serve_http(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
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


async def serve_unified(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
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


def serve_mcp_only():
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


def main():
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
