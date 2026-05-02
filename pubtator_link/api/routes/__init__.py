"""FastAPI route modules for PubTator-Link API endpoints."""

from .annotations import router as annotations_router
from .cache import router as cache_router
from .discovery import router as discovery_router
from .entities import router as entities_router
from .publications import router as publications_router
from .relations import router as relations_router
from .reviews import router as reviews_router
from .search import router as search_router

# Export all routers for easy import in server manager
__all__ = [
    "annotations_router",
    "cache_router",
    "discovery_router",
    "entities_router",
    "publications_router",
    "relations_router",
    "reviews_router",
    "search_router",
]

# Router registry for dynamic inclusion
ROUTE_MODULES = {
    "publications": publications_router,
    "entities": entities_router,
    "search": search_router,
    "relations": relations_router,
    "discovery": discovery_router,
    "reviews": reviews_router,
    "annotations": annotations_router,
    "cache": cache_router,
}
