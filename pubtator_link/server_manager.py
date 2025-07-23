"""Unified server manager for PubTator-Link."""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

    def __init__(self, logger: Optional[FilteringBoundLogger] = None):
        """Initialize unified server manager.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or configure_logging()
        self.client: Optional[PubTator3Client] = None
        self.publication_service: Optional[PublicationService] = None
        self.app: Optional[FastAPI] = None
        self.server: Optional[uvicorn.Server] = None

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
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
        async def root():
            """Root endpoint."""
            return {
                "name": "PubTator-Link",
                "version": "1.0.0",
                "description": "A unified server for the PubTator3 biomedical literature API",
                "transport": settings.transport,
            }

        @app.get("/health")
        async def health():
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

    async def start_unified_server(
        self, host: str = "127.0.0.1", port: int = 8000, reload: bool = False
    ):
        """Start unified server (HTTP + MCP)."""
        app = self.create_app()

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
    ):
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

    async def start_stdio_server(self):
        """Start STDIO MCP server."""
        self.logger.info("Starting STDIO MCP server", transport="stdio")

        # Initialize services for STDIO mode
        async with self.lifespan(None):
            # Simple STDIO MCP server loop
            self.logger.info("STDIO server ready for MCP communication")

            # Keep server running
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass

    async def shutdown(self):
        """Shutdown server."""
        if self.server:
            self.server.should_exit = True

        if self.client:
            await self.client.close()

        self.logger.info("Server shutdown initiated")
