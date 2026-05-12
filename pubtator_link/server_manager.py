"""Unified server manager for PubTator-Link."""

import json
import time
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import asdict
from uuid import uuid4

import uvicorn
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send
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
    variants_router,
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
from .db.migrate import ReviewSchemaDiagnostics
from .logging_config import configure_logging
from .mcp.facade import create_pubtator_mcp
from .observability.metrics import CONTENT_TYPE_LATEST, metrics_payload


async def _json_error_response(
    status_code: int,
    payload: dict[str, object],
    send: Send,
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


class PubTatorResourcesMiddleware:
    """Bind app resources to request context without BaseHTTPMiddleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        resources = getattr(request.app.state, "pubtator_resources", None)
        if resources is None:
            await self.app(scope, receive, send)
            return

        token = bind_app_resources(resources_from_request(request))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_app_resources(token)


class RequestSizeLimitMiddleware:
    """Reject oversized inbound HTTP request bodies."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        body_size = 0
        messages: deque[Message] = deque()
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break

            body_size += len(message.get("body", b""))
            if body_size > self.max_bytes:
                await _json_error_response(
                    413,
                    {
                        "success": False,
                        "error_code": "request_too_large",
                        "message": "Request body exceeds configured maximum size.",
                        "retryable": False,
                    },
                    send,
                )
                while message.get("more_body", False):
                    message = await receive()
                return

            if not message.get("more_body", False):
                break

        async def replay_receive() -> Message:
            if messages:
                return messages.popleft()
            return await receive()

        await self.app(scope, replay_receive, send)


class InboundRateLimitMiddleware:
    """Apply a simple per-client 60-second inbound HTTP request limit."""

    def __init__(self, app: ASGIApp, *, requests_per_minute: int) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.requests: defaultdict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        self._prune_stale_clients(now)
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        timestamps = self.requests[client_ip]
        while timestamps and now - timestamps[0] >= 60:
            timestamps.popleft()

        if len(timestamps) >= self.requests_per_minute:
            retry_after_seconds = max(1, int(60 - (now - timestamps[0])))
            await _json_error_response(
                429,
                {
                    "success": False,
                    "error_code": "rate_limited",
                    "message": "Inbound request rate limit exceeded.",
                    "retryable": True,
                    "retry_after_seconds": retry_after_seconds,
                },
                send,
            )
            return

        timestamps.append(now)
        await self.app(scope, receive, send)

    def _prune_stale_clients(self, now: float) -> None:
        for client_ip, timestamps in list(self.requests.items()):
            while timestamps and now - timestamps[0] >= 60:
                timestamps.popleft()
            if not timestamps:
                del self.requests[client_ip]


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
            app.state.pubtator_schema_diagnostics = _schema_diagnostics_payload(
                self.resources.schema_diagnostics
            )

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
            if hasattr(app.state, "pubtator_schema_diagnostics"):
                delattr(app.state, "pubtator_schema_diagnostics")
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

        app.add_middleware(
            RequestSizeLimitMiddleware,
            max_bytes=settings.http_max_request_bytes,
        )
        if settings.enable_inbound_rate_limit:
            app.add_middleware(
                InboundRateLimitMiddleware,
                requests_per_minute=settings.inbound_rate_limit_per_minute,
            )
        app.add_middleware(PubTatorResourcesMiddleware)
        app.add_middleware(
            CorrelationIdMiddleware,
            header_name="X-Request-ID",
            update_request_header=True,
            generator=lambda: str(uuid4()),
            validator=None,
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=settings.cors_allow_methods,
            allow_headers=settings.cors_allow_headers,
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

        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            """Prometheus metrics endpoint."""
            return Response(metrics_payload(), media_type=CONTENT_TYPE_LATEST)

        @app.get("/ready")
        async def ready(request: Request) -> dict[str, object]:
            """Readiness check endpoint."""
            resources = getattr(request.app.state, "pubtator_resources", None)
            schema_diagnostics = getattr(request.app.state, "pubtator_schema_diagnostics", None)
            schema_diagnostics = _schema_diagnostics_payload(schema_diagnostics)
            database_status = "not_configured"
            schema_current: bool | None = None
            if schema_diagnostics is not None:
                schema_current = bool(schema_diagnostics.get("current", False))
                database_status = "ready" if schema_current else "schema_outdated"
                if not bool(schema_diagnostics.get("connected", False)):
                    database_status = "unavailable"
            elif review_rerag_config.database_url is not None:
                database_status = "ready"
                if resources is None or resources.review_pool is None:
                    database_status = "unavailable"

            status = (
                "ready"
                if database_status not in {"unavailable", "schema_outdated"}
                else "not_ready"
            )
            database_dependency: dict[str, object] = {
                "status": database_status,
                "schema_current": schema_current,
            }
            if schema_diagnostics is not None:
                database_dependency.update(
                    {
                        "missing_tables": schema_diagnostics.get("missing_tables", []),
                        "missing_columns": schema_diagnostics.get("missing_columns", []),
                        "applied_versions": schema_diagnostics.get("applied_versions", []),
                        "error": schema_diagnostics.get("error"),
                    }
                )
            return {
                "status": status,
                "version": "1.0.0",
                "transport": settings.transport,
                "dependencies": {"database": database_dependency},
            }

        # Include all API route modules
        app.include_router(publications_router)
        app.include_router(entities_router)
        app.include_router(search_router)
        app.include_router(relations_router)
        app.include_router(discovery_router)
        app.include_router(annotations_router)
        if settings.enable_cache_endpoints:
            app.include_router(cache_router)
        app.include_router(reviews_router)
        app.include_router(variants_router)

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


def _schema_diagnostics_payload(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, ReviewSchemaDiagnostics):
        return asdict(value)
    return None
