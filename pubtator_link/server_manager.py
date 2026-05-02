"""Unified server manager for PubTator-Link."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from starlette.responses import Response
from structlog.typing import FilteringBoundLogger

from .api.routes import (
    annotations_router,
    cache_router,
    discovery_router,
    entities_router,
    publications_router,
    relations_router,
    reviews_router,
    search_router,
)
from .api.routes.dependencies import (
    AppResources,
    bind_app_resources,
    close_app_resources,
    create_app_resources,
    reset_app_resources,
    resources_from_request,
)
from .config import review_rerag_config, settings
from .logging_config import configure_logging
from .mcp.facade import create_pubtator_mcp


class UnifiedServerManager:
    """Manages unified server with multiple transport protocols."""

    def __init__(self, logger: FilteringBoundLogger | None = None):
        """Initialize unified server manager.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or configure_logging()
        self.resources: AppResources | None = None
        self.app: FastAPI | None = None
        self.mcp: FastMCP | None = None
        self.server: uvicorn.Server | None = None

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage FastAPI lifespan context."""
        self.logger.info("Starting PubTator-Link server")

        try:
            self.resources = await create_app_resources(logger=self.logger)
            app.state.pubtator_resources = self.resources

            if self.resources.review_queue is not None:
                await self.resources.review_queue.start()

            self.logger.info("Server started successfully")

            yield
        finally:
            self.logger.info("Shutting down server")
            if self.resources is not None:
                await close_app_resources(self.resources)
                self.resources = None
            if hasattr(app.state, "pubtator_resources"):
                delattr(app.state, "pubtator_resources")
            self.logger.info("Server shutdown complete")

    def create_app(self, *, include_mcp: bool = False) -> FastAPI:
        """Create FastAPI application."""
        mcp_http_app = None
        if include_mcp:
            mcp = create_pubtator_mcp()
            mcp_http_app = mcp.http_app(
                path=settings.mcp_path,
                json_response=True,
                stateless_http=True,
            )
            self.mcp = mcp

        @asynccontextmanager
        async def combined_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            async with self.lifespan(app):
                if mcp_http_app is None:
                    yield
                else:
                    async with mcp_http_app.lifespan(mcp_http_app):
                        yield

        app = FastAPI(
            title="PubTator-Link",
            description="A unified server for the PubTator3 biomedical literature API",
            version="1.0.0",
            lifespan=combined_lifespan,
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

        @app.get("/ready")
        async def ready(request: Request) -> dict[str, object]:
            """Readiness check endpoint."""
            resources = getattr(request.app.state, "pubtator_resources", None)
            database_status = "not_configured"
            if review_rerag_config.database_url is not None:
                database_status = "ready"
                if resources is None or resources.review_pool is None:
                    database_status = "unavailable"

            status = "ready" if database_status != "unavailable" else "not_ready"
            return {
                "status": status,
                "version": "1.0.0",
                "transport": settings.transport,
                "dependencies": {
                    "database": {
                        "status": database_status,
                    }
                },
            }

        @app.middleware("http")
        async def add_request_id(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            request_id = request.headers.get("X-Request-ID") or str(uuid4())
            request.state.request_id = request_id
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        @app.middleware("http")
        async def bind_pubtator_resources(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            resources = getattr(request.app.state, "pubtator_resources", None)
            if resources is None:
                return await call_next(request)
            resources = resources_from_request(request)
            token = bind_app_resources(resources)
            try:
                return await call_next(request)
            finally:
                reset_app_resources(token)

        # Include all API route modules
        app.include_router(publications_router)
        app.include_router(entities_router)
        app.include_router(search_router)
        app.include_router(relations_router)
        app.include_router(discovery_router)
        app.include_router(annotations_router)
        app.include_router(cache_router)
        app.include_router(reviews_router)

        if mcp_http_app is not None:
            app.mount("/", mcp_http_app)

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
        app = self.create_app(include_mcp=True)

        self.logger.info("MCP Streamable HTTP facade mounted", path=settings.mcp_path)
        self.logger.info(f"REST API available at http://{host}:{port}")
        self.logger.info(f"MCP HTTP available at http://{host}:{port}{settings.mcp_path}")
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
            if self.resources is None:
                await self.mcp.run_async(transport="stdio")
            else:
                token = bind_app_resources(self.resources)
                try:
                    await self.mcp.run_async(transport="stdio")
                finally:
                    reset_app_resources(token)

    async def shutdown(self) -> None:
        """Shutdown server."""
        if self.server:
            self.server.should_exit = True

        self.logger.info("Server shutdown initiated")


# Global app instance for WSGI compatibility (used by Gunicorn)
_manager = UnifiedServerManager()
app = _manager.create_app(include_mcp=settings.transport == "unified")
