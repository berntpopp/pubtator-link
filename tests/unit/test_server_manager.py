"""Tests for unified server manager lifecycle and transport behavior."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

from pubtator_link.api.routes import dependencies
from pubtator_link.api.routes.dependencies import AppResources
from pubtator_link.server_manager import PubTatorResourcesMiddleware, UnifiedServerManager


class LoggerDouble:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []

    def info(self, message: str, **kwargs: Any) -> None:
        self.messages.append((message, kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self.messages.append((message, kwargs))


class ClientDouble:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class McpHttpAppDouble:
    def __init__(self) -> None:
        self.lifespan_entered = False

    @asynccontextmanager
    async def lifespan(self, app: Any) -> AsyncGenerator[None, None]:
        self.lifespan_entered = True
        yield

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        return None


class McpDouble:
    def __init__(self) -> None:
        self.http_app_calls: list[dict[str, Any]] = []
        self.http_app_double = McpHttpAppDouble()
        self.run_async_calls: list[dict[str, Any]] = []

    def http_app(self, **kwargs: Any) -> McpHttpAppDouble:
        self.http_app_calls.append(kwargs)
        return self.http_app_double

    async def run_async(self, **kwargs: Any) -> None:
        self.run_async_calls.append(kwargs)


def test_create_app_with_mcp_mounts_http_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    mcp = McpDouble()
    monkeypatch.setattr("pubtator_link.server_manager.create_pubtator_mcp", lambda: mcp)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=True)

    assert isinstance(app, FastAPI)
    assert manager.app is app
    assert manager.mcp is mcp
    assert mcp.http_app_calls == [
        {
            "path": "/mcp",
            "json_response": True,
            "stateless_http": True,
        }
    ]
    assert any(
        isinstance(route, Mount) and route.app is mcp.http_app_double for route in app.routes
    )


def test_create_app_uses_pure_asgi_observability_middleware() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app()

    middleware_classes = [middleware.cls for middleware in app.user_middleware]

    assert CorrelationIdMiddleware in middleware_classes
    assert PubTatorResourcesMiddleware in middleware_classes


def test_resource_middleware_preserves_contextvars_in_child_tasks() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app()
    resources = AppResources(
        logger=manager.logger,
        api_client=ClientDouble(),
        publication_service=object(),
        publication_passage_service=object(),
    )
    app.state.pubtator_resources = resources

    @app.get("/context-probe")
    async def context_probe() -> dict[str, bool]:
        async def probe() -> bool:
            return dependencies.current_app_resources() is resources

        return {"bound": await asyncio.create_task(probe())}

    response = TestClient(app).get("/context-probe")

    assert response.status_code == 200
    assert response.json() == {"bound": True}
    assert dependencies.current_app_resources() is None


def test_metrics_endpoint_exports_prometheus_payload() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app()

    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "mcp_tool_calls_total" in response.text


@pytest.mark.asyncio
async def test_shutdown_requests_server_exit_without_closing_resources() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    client = ClientDouble()
    manager.resources = AppResources(
        logger=manager.logger,
        api_client=client,
        publication_service=object(),
        publication_passage_service=object(),
    )
    manager.server = SimpleNamespace(should_exit=False)

    await manager.shutdown()

    assert manager.server.should_exit is True
    assert manager.resources is not None
    assert client.closed is False


@pytest.mark.asyncio
async def test_start_stdio_server_binds_lifespan_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    client = ClientDouble()
    resources = AppResources(
        logger=manager.logger,
        api_client=client,
        publication_service=object(),
        publication_passage_service=object(),
    )
    observed_resources: list[AppResources | None] = []

    async def create_resources(logger: Any) -> AppResources:
        return resources

    async def close_resources(app_resources: AppResources) -> None:
        await app_resources.api_client.close()

    class StdioMcpDouble:
        async def run_async(self, **kwargs: Any) -> None:
            observed_resources.append(dependencies.current_app_resources())
            assert kwargs == {"transport": "stdio"}

    async def create_mcp_server(app: FastAPI) -> StdioMcpDouble:
        assert isinstance(app, FastAPI)
        return StdioMcpDouble()

    monkeypatch.setattr(
        "pubtator_link.server_manager.create_app_resources",
        create_resources,
    )
    monkeypatch.setattr(
        "pubtator_link.server_manager.close_app_resources",
        close_resources,
    )
    monkeypatch.setattr(manager, "create_mcp_server", create_mcp_server)

    await manager.start_stdio_server()

    assert observed_resources == [resources]
    assert dependencies.current_app_resources() is None
    assert client.closed is True
    assert manager.resources is None
