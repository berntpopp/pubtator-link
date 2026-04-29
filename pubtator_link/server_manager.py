"""Unified server manager for PubTator-Link."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from structlog.typing import FilteringBoundLogger

from .api.client import PubTator3Client
from .api.routes import (
    annotations_router,
    cache_router,
    entities_router,
    publications_router,
    relations_router,
    search_router,
)
from .api.routes.dependencies import cleanup_dependencies
from .config import settings
from .logging_config import configure_logging
from .services.publication_service import PublicationService


class UnifiedServerManager:
    """Manages unified server with multiple transport protocols."""

    def __init__(self, logger: FilteringBoundLogger | None = None):
        """Initialize unified server manager.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or configure_logging()
        self.client: PubTator3Client | None = None
        self.publication_service: PublicationService | None = None
        self.app: FastAPI | None = None
        self.mcp: FastMCP | None = None
        self.server: uvicorn.Server | None = None

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage FastAPI lifespan context."""
        # Startup
        self.logger.info("Starting PubTator-Link server")

        # Initialize API client
        self.client = PubTator3Client(logger=self.logger)

        # Initialize services
        self.publication_service = PublicationService(client=self.client, logger=self.logger)

        self.logger.info("Server started successfully")

        yield

        # Shutdown
        self.logger.info("Shutting down server")
        if self.client:
            await self.client.close()
        # Cleanup dependencies
        await cleanup_dependencies()
        self.logger.info("Server shutdown complete")

    def create_app(self) -> FastAPI:
        """Create FastAPI application."""
        app = FastAPI(
            title="PubTator-Link",
            description="A unified server for the PubTator3 biomedical literature API",
            version="1.0.0",
            lifespan=self.lifespan,
            docs_url="/docs" if settings.enable_docs else None,
            redoc_url="/redoc" if settings.enable_docs else None,
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Add basic routes
        @app.get("/")
        async def root() -> dict[str, str]:
            """Root endpoint."""
            return {
                "name": "PubTator-Link",
                "version": "1.0.0",
                "description": "A unified server for the PubTator3 biomedical literature API",
                "transport": settings.transport,
            }

        @app.get("/health")
        async def health() -> dict[str, str]:
            """Health check endpoint."""
            return {
                "status": "healthy",
                "version": "1.0.0",
                "transport": settings.transport,
            }

        # Include all API route modules
        app.include_router(publications_router)
        app.include_router(entities_router)
        app.include_router(search_router)
        app.include_router(relations_router)
        app.include_router(annotations_router)
        app.include_router(cache_router)

        self.app = app
        return app

    async def create_mcp_server(self, app: FastAPI) -> FastMCP:
        """Create FastMCP server from FastAPI app."""
        try:
            # Import MCP configuration classes
            from fastmcp.server.openapi import MCPType, RouteMap

            # Define custom tool names for better LLM experience
            mcp_custom_names = {
                "export_publication_annotations": "export_publications",
                "export_pmc_publications": "export_pmc_articles",
                "search_entity_ids": "search_biomedical_entities",
                "search_publications": "search_literature",
                "find_related_entities": "find_entity_relations",
                "submit_text_annotation": "annotate_text",
                "get_annotation_results": "get_text_annotations",
                "get_cache_statistics": "get_cache_stats",
                "clear_cache": "clear_api_cache",
            }

            # Define route filtering to exclude utility endpoints from MCP
            mcp_route_maps = [
                # Exclude health and monitoring endpoints
                RouteMap(pattern=r"^/health$", mcp_type=MCPType.EXCLUDE),
                RouteMap(pattern=r"^/cache/.*$", mcp_type=MCPType.EXCLUDE),
                # Exclude root and docs endpoints
                RouteMap(pattern=r"^/$", mcp_type=MCPType.EXCLUDE),
                RouteMap(pattern=r"^/docs$", mcp_type=MCPType.EXCLUDE),
                RouteMap(pattern=r"^/openapi.json$", mcp_type=MCPType.EXCLUDE),
                RouteMap(pattern=r"^/redoc$", mcp_type=MCPType.EXCLUDE),
            ]

            # Create MCP server from FastAPI app
            mcp = FastMCP.from_fastapi(
                app=app,
                name="PubTator-Link Server",
                mcp_names=mcp_custom_names,
                route_maps=mcp_route_maps,
            )

            self.logger.info("FastMCP server created successfully")
            return mcp

        except Exception as e:
            self.logger.error(f"Failed to create MCP server: {e}")
            raise RuntimeError(f"MCP server creation failed: {e}") from e

    async def start_unified_server(
        self, host: str = "127.0.0.1", port: int = 8000, reload: bool = False
    ) -> None:
        """Start unified server (HTTP + MCP)."""
        # Create FastAPI app
        app = self.create_app()

        # Create and mount MCP server
        self.mcp = await self.create_mcp_server(app)
        app.mount("/mcp", self.mcp.http_app())

        self.logger.info("MCP HTTP interface mounted at /mcp")
        self.logger.info(f"REST API available at http://{host}:{port}")
        self.logger.info(f"MCP HTTP available at http://{host}:{port}/mcp")
        self.logger.info(f"API documentation at http://{host}:{port}/docs")

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=settings.log_level.lower(),
            access_log=settings.transport != "stdio",
            reload=reload,
            reload_dirs=["pubtator_link"] if reload else None,
        )

        self.server = uvicorn.Server(config)

        self.logger.info("Starting unified server", host=host, port=port, transport="unified")

        await self.server.serve()

    async def start_http_only_server(
        self, host: str = "127.0.0.1", port: int = 8000, reload: bool = False
    ) -> None:
        """Start HTTP-only server."""
        app = self.create_app()

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=settings.log_level.lower(),
            reload=reload,
            reload_dirs=["pubtator_link"] if reload else None,
        )

        self.server = uvicorn.Server(config)

        self.logger.info("Starting HTTP server", host=host, port=port, transport="http")

        await self.server.serve()

    async def start_stdio_server(self) -> None:
        """Start STDIO MCP server."""
        self.logger.info("Starting STDIO MCP server", transport="stdio")

        # Create FastAPI app (for MCP introspection)
        app = self.create_app()

        # Use lifespan context manager for consistency with HTTP mode
        self.logger.info("Initializing app state using lifespan context...")
        async with self.lifespan(app):
            # Create MCP server within the lifespan context
            self.mcp = await self.create_mcp_server(app)

            self.logger.info("STDIO MCP server ready")

            # Run MCP server in STDIO mode
            # Note: FastMCP needs direct access to sys.stdout.buffer for STDIO protocol
            await self.mcp.run_async(transport="stdio")

    async def shutdown(self) -> None:
        """Shutdown server."""
        if self.server:
            self.server.should_exit = True

        if self.client:
            await self.client.close()

        self.logger.info("Server shutdown initiated")


# Global app instance for WSGI compatibility (used by Gunicorn)
_manager = UnifiedServerManager()
app = _manager.create_app()
