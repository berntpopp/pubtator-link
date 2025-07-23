"""MCP server implementation for PubTator-Link."""

from typing import Any, Optional

from mcp.server import Server

from .api.client import PubTator3Client
from .api.routes.dependencies import (
    validate_entity_id,
    validate_limit,
    validate_page_number,
    validate_pmcids,
    validate_pmids,
)
from .config import api_config
from .logging_config import configure_logging
from .services.publication_service import PublicationService

# Initialize the MCP server
server = Server("pubtator-link")

# Global variables for services
client: Optional[PubTator3Client] = None
publication_service: Optional[PublicationService] = None
logger = configure_logging()


async def initialize_services():
    """Initialize the MCP server services."""
    global client, publication_service

    logger.info("Initializing PubTator MCP server")

    # Initialize API client and services
    client = PubTator3Client(logger=logger)
    publication_service = PublicationService(client=client, logger=logger)

    logger.info("PubTator MCP server initialized successfully")


async def cleanup_services():
    """Cleanup server resources."""
    global client, publication_service

    logger.info("Cleaning up PubTator MCP server")

    if client:
        await client.close()

    client = None
    publication_service = None

    logger.info("PubTator MCP server cleanup complete")


@server.call_tool()
async def export_publication_annotations(
    format: str, pmids: str, full: bool = False
) -> dict[str, Any]:
    """Export publication annotations in specified format."""
    if not client or not publication_service:
        raise RuntimeError("MCP server not initialized")

    # Validate PMIDs
    validated_pmids = validate_pmids(pmids)

    # Call service
    result = await publication_service.export_annotations(
        pmids=validated_pmids, format=format, full=full
    )

    return {
        "success": True,
        "format": format,
        "pmids": validated_pmids,
        "full": full,
        "content": result.content,
        "content_type": result.content_type,
    }


@server.call_tool()
async def export_pmc_publications(format: str, pmcids: str) -> dict[str, Any]:
    """Export PMC publication annotations in specified format."""
    if not client or not publication_service:
        raise RuntimeError("MCP server not initialized")

    # Validate PMCIDs
    validated_pmcids = validate_pmcids(pmcids)

    # Call service
    result = await publication_service.export_pmc_annotations(
        pmcids=validated_pmcids, format=format
    )

    return {
        "success": True,
        "format": format,
        "pmcids": validated_pmcids,
        "content": result.content,
        "content_type": result.content_type,
    }


@server.call_tool()
async def search_entity_ids(
    query: str, concept: Optional[str] = None, limit: int = 10
) -> dict[str, Any]:
    """Find biomedical entity identifiers through autocomplete search."""
    if not client:
        raise RuntimeError("MCP server not initialized")

    # Validate concept type if provided
    if concept and concept not in api_config.bioconcept_types:
        raise ValueError(
            f"Invalid bioconcept '{concept}'. Supported types: {', '.join(api_config.bioconcept_types)}"
        )

    # Validate limit
    validated_limit = validate_limit(limit, max_limit=100)

    # Call API client
    result = await client.autocomplete_entity(
        query=query.strip(), concept=concept, limit=validated_limit
    )

    # Parse response
    matches = []
    # API returns a list directly, not a dict with "results" key
    api_results = result if isinstance(result, list) else []

    for item in api_results:
        matches.append(
            {
                "identifier": item.get("_id", ""),
                "name": item.get("name", ""),
                "type": item.get("biotype", concept or "Unknown"),
                "score": item.get("score"),
                "synonyms": item.get("synonyms", []),
                "db_id": item.get("db_id"),
                "db": item.get("db"),
                "match": item.get("match"),
            }
        )

    return {
        "success": True,
        "query": query,
        "matches": matches,
        "total_matches": len(matches),
        "concept_filter": concept,
    }


@server.call_tool()
async def search_publications(text: str, page: int = 1, sort: str = None) -> dict[str, Any]:
    """Search biomedical literature using flexible query types.

    Args:
        text: Search query (free text, entity ID, or relation)
        page: Page number for pagination (default: 1)
        sort: Sort order - "date desc", "date asc", "score desc", "score asc" (default: score desc)
    """
    if not client:
        raise RuntimeError("MCP server not initialized")

    # Validate page number
    validated_page = validate_page_number(page)

    # Validate sort parameter
    valid_sorts = ["date desc", "date asc", "score desc", "score asc"]
    if sort is not None and sort not in valid_sorts:
        raise ValueError(f"Invalid sort order. Must be one of: {', '.join(valid_sorts)}")

    # Call API client
    result = await client.search_publications(text=text.strip(), page=validated_page, sort=sort)

    # Parse response
    search_results = []
    api_results = result.get("results", [])

    for item in api_results:
        search_results.append(
            {
                "pmid": item.get("pmid", ""),
                "title": item.get("title", ""),
                "abstract": item.get("abstract"),
                "authors": item.get("authors", []),
                "journal": item.get("journal"),
                "pub_date": item.get("pub_date"),
                "annotations": item.get("annotations", []),
                "score": item.get("score"),
            }
        )

    # Extract pagination information
    total_results = result.get("total", 0)
    per_page = result.get("per_page", 20)
    total_pages = (total_results + per_page - 1) // per_page

    return {
        "success": True,
        "query": text,
        "results": search_results,
        "total_results": total_results,
        "page": validated_page,
        "per_page": per_page,
        "total_pages": total_pages,
        "sort_order": sort or "score desc (default)",
    }


@server.call_tool()
async def find_related_entities(
    e1: str, type: Optional[str] = None, e2: Optional[str] = None
) -> dict[str, Any]:
    """Find entities related to a specific biomedical entity."""
    if not client:
        raise RuntimeError("MCP server not initialized")

    # Validate entity ID
    validated_entity_id = validate_entity_id(e1)

    # Validate relation type if provided
    if type and type not in api_config.relation_types:
        raise ValueError(
            f"Invalid relation type '{type}'. Supported types: {', '.join(api_config.relation_types)}"
        )

    # Validate target entity type if provided
    if e2 and e2 not in api_config.bioconcept_types:
        raise ValueError(
            f"Invalid entity type '{e2}'. Supported types: {', '.join(api_config.bioconcept_types)}"
        )

    # Call API client
    result = await client.find_relations(e1=validated_entity_id, relation_type=type, e2=e2)

    # Parse response
    related_entities = []
    api_results = result.get("results", [])

    for item in api_results:
        related_entities.append(
            {
                "entity_id": item.get("entity_id", ""),
                "entity_name": item.get("entity_name", ""),
                "entity_type": item.get("entity_type", ""),
                "relation_type": item.get("relation_type", ""),
                "confidence": item.get("confidence"),
                "pmids": item.get("pmids", []),
            }
        )

    return {
        "success": True,
        "primary_entity": validated_entity_id,
        "related_entities": related_entities,
        "total_relations": len(related_entities),
        "relation_filter": type,
        "entity_filter": e2,
    }


@server.call_tool()
async def submit_text_annotation(text: str, bioconcepts: str = "all") -> dict[str, Any]:
    """Submit text for biomedical entity annotation."""
    if not client:
        raise RuntimeError("MCP server not initialized")

    # Parse bioconcepts
    if bioconcepts == "all":
        concept_list = list(api_config.bioconcept_types)
    else:
        concept_list = [bc.strip() for bc in bioconcepts.split(",") if bc.strip()]
        # Validate concept types
        for concept in concept_list:
            if concept not in api_config.bioconcept_types:
                raise ValueError(
                    f"Invalid bioconcept '{concept}'. Supported types: {', '.join(api_config.bioconcept_types)}"
                )

    # Call API client
    result = await client.submit_text_annotation(text=text, bioconcepts=concept_list)

    return {
        "success": True,
        "session_id": result.get("session_id"),
        "status": result.get("status", "submitted"),
        "bioconcepts": concept_list,
        "message": "Text submitted for annotation. Use get_annotation_results with the session_id to retrieve results.",
    }


@server.call_tool()
async def get_annotation_results(session_id: str, format: str = "pubtator") -> dict[str, Any]:
    """Retrieve annotation results for a submitted text processing job."""
    if not client:
        raise RuntimeError("MCP server not initialized")

    # Call API client
    result = await client.get_annotation_results(session_id=session_id, format=format)

    return {
        "success": True,
        "session_id": session_id,
        "status": result.get("status"),
        "format": format,
        "content": result.get("content"),
        "annotations": result.get("annotations", []),
    }


@server.call_tool()
async def get_cache_statistics(detailed: bool = False) -> dict[str, Any]:
    """Get comprehensive cache performance statistics."""
    if not publication_service:
        raise RuntimeError("MCP server not initialized")

    # Get cache statistics from the service
    cache_stats = publication_service.get_cache_stats()

    # Create basic cache stats
    basic_stats = {
        "total_size": cache_stats.get("total_size", 0),
        "current_size": cache_stats.get("current_size", 0),
        "hit_rate": cache_stats.get("hit_rate", 0.0),
        "miss_rate": cache_stats.get("miss_rate", 0.0),
        "total_hits": cache_stats.get("total_hits", 0),
        "total_misses": cache_stats.get("total_misses", 0),
    }

    result = {
        "success": True,
        "stats": basic_stats,
        "message": "Cache statistics retrieved successfully",
    }

    # Include detailed stats if requested
    if detailed:
        result["detailed_stats"] = cache_stats.get("detailed_stats", {})

    return result


@server.call_tool()
async def clear_cache(pattern: Optional[str] = None) -> dict[str, Any]:
    """Clear cached data with optional pattern-based filtering."""
    if not publication_service:
        raise RuntimeError("MCP server not initialized")

    # Validate pattern format if provided
    if pattern is not None:
        if pattern.strip() == "":
            raise ValueError(
                "Cache pattern cannot be empty. Use null/undefined to clear all cache."
            )

        # Validate that pattern contains valid cache prefixes
        valid_prefixes = [
            "pub_export:",
            "entity_ac:",
            "search:",
            "relations:",
            "text_proc:",
        ]
        if not any(pattern.startswith(prefix) for prefix in valid_prefixes):
            logger.warning(f"Pattern '{pattern}' doesn't match known cache prefixes")

    # Clear cache using the service
    cleared_count = publication_service.clear_cache(pattern=pattern)

    # Determine success message
    if pattern is None:
        message = "All cached items cleared successfully"
    else:
        message = "Cache items matching pattern cleared successfully"

    return {
        "success": True,
        "cleared_items": cleared_count,
        "pattern": pattern,
        "message": message,
    }


async def serve_mcp() -> None:
    """Serve the MCP server."""
    try:
        await initialize_services()

        # Run the MCP server
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)

    except Exception as e:
        logger.error(f"MCP server error: {e}")
        raise
    finally:
        await cleanup_services()


if __name__ == "__main__":
    import asyncio

    asyncio.run(serve_mcp())
