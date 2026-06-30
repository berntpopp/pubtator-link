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


def test_create_app_uses_explicit_cors_methods_and_headers() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app()

    cors_middleware = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]
    assert cors_middleware.kwargs["allow_headers"] == [
        "Authorization",
        "Content-Type",
        "Mcp-Session-Id",
        "MCP-Protocol-Version",
        "Last-Event-ID",
        "X-Request-ID",
    ]


def test_post_request_size_limit_returns_stable_413(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.http_max_request_bytes", 8)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.post("/echo")
    async def echo() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).post("/echo", content=b"0123456789")

    assert response.status_code == 413
    assert response.json() == {
        "success": False,
        "error_code": "request_too_large",
        "message": "Request body exceeds configured maximum size.",
        "retryable": False,
    }


def test_inbound_rate_limit_returns_stable_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.enable_inbound_rate_limit", True)
    monkeypatch.setattr("pubtator_link.server_manager.settings.inbound_rate_limit_per_minute", 1)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.get("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/limited").status_code == 200
    response = client.get("/limited")

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert response.json()["retryable"] is True


def test_request_size_limit_response_includes_cors_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.http_max_request_bytes", 8)
    monkeypatch.setattr(
        "pubtator_link.server_manager.settings.cors_origins", ["http://localhost:3000"]
    )

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.post("/echo")
    async def echo() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).post(
        "/echo",
        content=b"0123456789",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_accepts_mcp_protocol_version_header() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    response = TestClient(app).options(
        "/mcp",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "MCP-Protocol-Version",
        },
    )

    assert response.status_code == 200


def test_cors_preflight_does_not_consume_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.enable_inbound_rate_limit", True)
    monkeypatch.setattr("pubtator_link.server_manager.settings.inbound_rate_limit_per_minute", 1)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.get("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    preflight = client.options(
        "/limited",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    response = client.get("/limited")

    assert preflight.status_code == 200
    assert response.status_code == 200


def test_server_settings_parse_csv_cors_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    from pubtator_link.config import ServerSettings

    monkeypatch.setenv("PUBTATOR_LINK_CORS_ALLOW_METHODS", "GET,POST,OPTIONS")
    monkeypatch.setenv(
        "PUBTATOR_LINK_CORS_ALLOW_HEADERS",
        "Authorization,Content-Type,MCP-Protocol-Version",
    )

    parsed = ServerSettings(_env_file=None)

    assert parsed.cors_allow_methods == ["GET", "POST", "OPTIONS"]
    assert parsed.cors_allow_headers == [
        "Authorization",
        "Content-Type",
        "MCP-Protocol-Version",
    ]


def test_server_settings_parse_json_cors_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    from pubtator_link.config import ServerSettings

    monkeypatch.setenv("PUBTATOR_LINK_CORS_ALLOW_METHODS", '["GET","POST","OPTIONS"]')
    monkeypatch.setenv(
        "PUBTATOR_LINK_CORS_ALLOW_HEADERS",
        '["Authorization","Content-Type","MCP-Protocol-Version"]',
    )

    parsed = ServerSettings(_env_file=None)

    assert parsed.cors_allow_methods == ["GET", "POST", "OPTIONS"]
    assert parsed.cors_allow_headers == [
        "Authorization",
        "Content-Type",
        "MCP-Protocol-Version",
    ]


@pytest.mark.asyncio
async def test_inbound_rate_limit_prunes_stale_client_entries() -> None:
    from pubtator_link.server_manager import InboundRateLimitMiddleware

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = InboundRateLimitMiddleware(app, requests_per_minute=1)
    middleware.requests["stale"].append(time_marker := 0.0)
    assert time_marker == 0.0

    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await middleware(
        {"type": "http", "method": "GET", "client": ("new", 1234)},
        receive,
        send,
    )

    assert "stale" not in middleware.requests


def test_inbound_rate_limit_keys_on_trusted_proxy_xff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.enable_inbound_rate_limit", True)
    monkeypatch.setattr("pubtator_link.server_manager.settings.inbound_rate_limit_per_minute", 1)
    monkeypatch.setattr("pubtator_link.server_manager.settings.trust_proxy_headers", True)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.get("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/limited", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert client.get("/limited", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
    assert client.get("/limited", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429


def test_inbound_rate_limit_ignores_xff_when_proxy_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.enable_inbound_rate_limit", True)
    monkeypatch.setattr("pubtator_link.server_manager.settings.inbound_rate_limit_per_minute", 1)
    monkeypatch.setattr("pubtator_link.server_manager.settings.trust_proxy_headers", False)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.get("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/limited", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    # Spoofed XFF must not buy a fresh bucket when the proxy is untrusted.
    assert client.get("/limited", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429
