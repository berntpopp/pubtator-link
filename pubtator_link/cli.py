"""Command-line interface for PubTator-Link."""

import argparse
import asyncio
import sys
from typing import Optional

from .api.client import PubTator3Client
from .logging_config import configure_logging
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
            result = await client.autocomplete_entity(
                query=query, concept=concept, limit=limit
            )

            print(f"Entity search results for '{query}':")
            if isinstance(result, dict) and "content" in result:
                print(result["content"])
            else:
                print(result)

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

            print(f"Publication search results for '{query}' (page {page}):")
            print(f"Total results: {result.total_results}")

            for i, pub in enumerate(result.results, 1):
                print(f"\n{i}. PMID: {pub.pmid}")
                print(f"   Title: {pub.title}")
                if pub.abstract:
                    print(f"   Abstract: {pub.abstract[:200]}...")

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
            result = await service.export_publications(
                pmids=pmid_list, format=format, full=full
            )

            print(f"Export results for PMIDs {pmids} in {format} format:")
            print(f"Total documents: {result.total_documents}")

            for i, doc in enumerate(result.documents, 1):
                print(f"\nDocument {i}:")
                if isinstance(doc, dict):
                    print(f"  Keys: {list(doc.keys())}")
                else:
                    print(f"  Type: {type(doc)}")

        except Exception as e:
            logger.error("Publication export failed", error=str(e))
            sys.exit(1)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="PubTator-Link CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Test connection command
    subparsers.add_parser("test", help="Test connection to PubTator3 API")

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
    export_parser = subparsers.add_parser(
        "export", help="Export publication annotations"
    )
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
    elif args.command == "entities":
        asyncio.run(search_entities(args.query, args.concept, args.limit))
    elif args.command == "search":
        asyncio.run(search_publications(args.query, args.page))
    elif args.command == "export":
        asyncio.run(export_publications(args.pmids, args.format, args.full))


if __name__ == "__main__":
    main()
