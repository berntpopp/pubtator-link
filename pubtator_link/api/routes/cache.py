"""Cache management API routes for PubTator-Link server."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ...models.responses import CacheClearResponse, CacheStats, CacheStatsResponse
from .dependencies import (
    PublicationServiceDep,
    handle_api_errors,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cache", tags=["Cache Management"])


@router.get(
    "/stats",
    response_model=CacheStatsResponse,
    summary="Get cache statistics",
    description="Retrieve comprehensive statistics about the server's caching performance.",
    operation_id="get_cache_statistics",
    responses={
        200: {
            "description": "Cache statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "stats": {
                            "total_size": 1000,
                            "current_size": 347,
                            "hit_rate": 0.82,
                            "miss_rate": 0.18,
                            "total_hits": 1647,
                            "total_misses": 358,
                        },
                        "detailed_stats": {
                            "publication_export": {
                                "size": 156,
                                "hits": 892,
                                "misses": 134,
                                "hit_rate": 0.87,
                            },
                            "entity_autocomplete": {
                                "size": 89,
                                "hits": 445,
                                "misses": 91,
                                "hit_rate": 0.83,
                            },
                            "search": {
                                "size": 67,
                                "hits": 234,
                                "misses": 89,
                                "hit_rate": 0.72,
                            },
                            "relations": {
                                "size": 35,
                                "hits": 76,
                                "misses": 44,
                                "hit_rate": 0.63,
                            },
                        },
                    }
                }
            },
        },
        500: {
            "description": "Error retrieving cache statistics",
            "content": {
                "application/json": {"example": {"detail": "Failed to retrieve cache statistics"}}
            },
        },
    },
)
@handle_api_errors
async def get_cache_statistics(
    service: PublicationServiceDep,
    detailed: bool = Query(
        default=False, description="Include detailed per-operation cache statistics"
    ),
) -> CacheStatsResponse:
    """Get comprehensive cache performance statistics.

    This endpoint provides insights into the server's caching performance,
    which can be useful for monitoring, optimization, and troubleshooting.

    **Basic Statistics:**
    - **total_size**: Maximum number of items the cache can hold
    - **current_size**: Current number of cached items
    - **hit_rate**: Percentage of requests served from cache
    - **miss_rate**: Percentage of requests that required API calls
    - **total_hits**: Total number of cache hits since server start
    - **total_misses**: Total number of cache misses since server start

    **Detailed Statistics (when detailed=true):**
    Per-operation breakdown for:
    - **publication_export**: Publication annotation exports
    - **entity_autocomplete**: Entity ID searches
    - **search**: Literature searches
    - **relations**: Entity relationship queries
    - **text_processing**: Text annotation results

    **Performance Indicators:**
    - Hit rate > 70%: Good caching performance
    - Hit rate 50-70%: Moderate caching performance
    - Hit rate < 50%: Consider cache size increase or TTL adjustment

    **Cache Optimization:**
    - High miss rate may indicate need for larger cache size
    - Very high hit rate with full cache may indicate need for longer TTL
    - Monitor detailed stats to identify most/least cached operations

    Args:
        detailed: Whether to include per-operation statistics
        service: Injected publication service with cache access

    Returns:
        CacheStatsResponse with cache performance metrics

    Raises:
        HTTPException(500): Error retrieving cache statistics
    """
    try:
        # Get cache statistics from the service
        cache_stats = service.get_cache_stats()

        # Create basic cache stats object
        basic_stats = CacheStats(
            total_size=cache_stats.get("total_size", 0),
            current_size=cache_stats.get("current_size", 0),
            hit_rate=cache_stats.get("hit_rate", 0.0),
            miss_rate=cache_stats.get("miss_rate", 0.0),
            total_hits=cache_stats.get("total_hits", 0),
            total_misses=cache_stats.get("total_misses", 0),
        )

        # Include detailed stats if requested
        detailed_stats = None
        if detailed:
            detailed_stats = cache_stats.get("detailed_stats", {})

        return CacheStatsResponse(
            success=True,
            stats=basic_stats,
            detailed_stats=detailed_stats,
            message="Cache statistics retrieved successfully",
        )

    except Exception as e:
        logger.error(f"Error retrieving cache statistics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve cache statistics") from e


@router.delete(
    "/clear",
    response_model=CacheClearResponse,
    summary="Clear cache",
    description="Clear cached data with optional pattern-based filtering.",
    operation_id="clear_cache",
    responses={
        200: {
            "description": "Cache cleared successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "clear_all": {
                            "summary": "Clear all cache",
                            "value": {
                                "success": True,
                                "cleared_items": 347,
                                "pattern": None,
                                "message": "All cached items cleared successfully",
                            },
                        },
                        "clear_pattern": {
                            "summary": "Clear with pattern",
                            "value": {
                                "success": True,
                                "cleared_items": 156,
                                "pattern": "pub_export:*",
                                "message": "Cache items matching pattern cleared successfully",
                            },
                        },
                    }
                }
            },
        },
        400: {
            "description": "Invalid clear pattern",
            "content": {
                "application/json": {"example": {"detail": "Invalid cache pattern format"}}
            },
        },
        500: {
            "description": "Error clearing cache",
            "content": {"application/json": {"example": {"detail": "Failed to clear cache"}}},
        },
    },
)
@handle_api_errors
async def clear_cache(
    service: PublicationServiceDep,
    pattern: Optional[str] = Query(
        default=None,
        description="Cache key pattern to clear (clears all if not specified)",
        examples=[
            {
                "summary": "Clear all cache",
                "description": "Clear all cached items",
                "value": None,
            },
            {
                "summary": "Clear publication cache",
                "description": "Clear only publication export cache",
                "value": "pub_export:*",
            },
            {
                "summary": "Clear entity cache",
                "description": "Clear only entity autocomplete cache",
                "value": "entity_ac:*",
            },
            {
                "summary": "Clear search cache",
                "description": "Clear only literature search cache",
                "value": "search:*",
            },
            {
                "summary": "Clear relations cache",
                "description": "Clear only entity relations cache",
                "value": "relations:*",
            },
        ],
    ),
) -> CacheClearResponse:
    """Clear cached data with optional pattern-based filtering.

    This endpoint allows clearing cached data either completely or selectively
    based on cache key patterns. This can be useful for:
    - Forcing fresh data retrieval after API updates
    - Managing memory usage
    - Clearing stale cached results
    - Development and testing

    **Cache Key Patterns:**
    The server uses structured cache keys for different operations:
    - **pub_export:*** - Publication export cache
    - **entity_ac:*** - Entity autocomplete cache
    - **search:*** - Literature search cache
    - **relations:*** - Entity relations cache
    - **text_proc:*** - Text processing results cache

    **Pattern Syntax:**
    - Use wildcards (*) to match multiple keys
    - Patterns are case-sensitive
    - Empty/null pattern clears all cache

    **Usage Examples:**
    - Clear all cache: Don't specify pattern parameter
    - Clear publication exports: pattern="pub_export:*"
    - Clear specific search: pattern="search:cancer*"
    - Clear entity data: pattern="entity_ac:*"

    **Performance Impact:**
    - Clearing cache will temporarily increase API response times
    - Subsequent requests will rebuild the cache
    - Consider clearing during low-usage periods
    - Monitor cache hit rates after clearing

    **Safety Considerations:**
    - This operation cannot be undone
    - Cleared data must be re-fetched from PubTator3 APIs
    - May impact server performance temporarily
    - Use with caution in production environments

    Args:
        pattern: Optional pattern to match cache keys for selective clearing
        service: Injected publication service with cache access

    Returns:
        CacheClearResponse with number of items cleared

    Raises:
        HTTPException(400): Invalid pattern format
        HTTPException(500): Error clearing cache
    """
    try:
        # Validate pattern format if provided
        if pattern is not None:
            # Basic pattern validation - ensure it's not empty string
            if pattern.strip() == "":
                raise HTTPException(
                    status_code=400,
                    detail="Cache pattern cannot be empty. Use null/undefined to clear all cache.",
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
        cleared_count = await service.clear_cache(pattern=pattern)

        # Determine success message
        if pattern is None:
            message = "All cached items cleared successfully"
        else:
            message = "Cache items matching pattern cleared successfully"

        return CacheClearResponse(
            success=True, cleared_items=cleared_count, pattern=pattern, message=message
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cache") from e
