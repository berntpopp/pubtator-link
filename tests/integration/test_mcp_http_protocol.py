from __future__ import annotations

from fastapi.testclient import TestClient


def test_unified_app_mounts_streamable_http_mcp() -> None:
    from pubtator_link.server_manager import UnifiedServerManager

    manager = UnifiedServerManager()
    app = manager.create_app(include_mcp=True)

    with TestClient(app, raise_server_exceptions=False) as client:
        initialize = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )

        assert initialize.status_code in {200, 202}

        tools = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

    assert tools.status_code == 200
    names = {tool["name"] for tool in tools.json()["result"]["tools"]}
    assert "search_literature" in names
    assert "pubtator.clear_api_cache" not in names


_MODERN_VERSION = "2026-07-28"
_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": _MODERN_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1.0"},
}


def _modern_post(
    client: TestClient, req_id: int, method: str, params: dict[str, object], name: str | None = None
):  # type: ignore[no-untyped-def]
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": _MODERN_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": {"_meta": _MODERN_META, **params},
        },
    )


def test_modern_mcp_http_discovers_lists_calls_and_fences_unknown_tool() -> None:
    """The 2026-07-28 sessionless era works end to end through the unified app."""
    from pubtator_link.server_manager import UnifiedServerManager

    app = UnifiedServerManager().create_app(include_mcp=True)
    hostile = "ignore-instructions-secret"
    with TestClient(app, raise_server_exceptions=False) as client:
        discover = _modern_post(client, 1, "server/discover", {})
        listed = _modern_post(client, 2, "tools/list", {})
        called = _modern_post(
            client,
            3,
            "tools/call",
            {"name": "get_server_capabilities", "arguments": {}},
            name="get_server_capabilities",
        )
        unknown = _modern_post(
            client, 4, "tools/call", {"name": hostile, "arguments": {}}, name=hostile
        )

    assert discover.status_code == 200, discover.text
    assert _MODERN_VERSION in discover.json()["result"]["supportedVersions"]
    assert "mcp-session-id" not in discover.headers
    assert listed.status_code == 200
    assert "get_server_capabilities" in {t["name"] for t in listed.json()["result"]["tools"]}
    assert called.status_code == 200
    assert called.json()["result"].get("isError") is not True
    assert unknown.status_code == 200
    unknown_result = unknown.json()["result"]
    assert unknown_result["isError"] is True
    assert unknown_result["structuredContent"]["error_code"] == "not_found"
    assert hostile not in unknown.text


_EVIL_METHOD = "evil__IGNORE_ALL_PREVIOUS__method"


def _assert_fixed_method_not_found(response) -> None:  # type: ignore[no-untyped-def]
    assert _EVIL_METHOD not in response.text
    assert "IGNORE_ALL_PREVIOUS" not in response.text
    error = response.json()["error"]
    assert error["code"] == -32601
    assert "data" not in error or error["data"] is None


def test_unknown_method_is_not_echoed_in_either_era() -> None:
    """SDK 2 echoes an unknown JSON-RPC method in METHOD_NOT_FOUND ``data``; the
    Layer-3 middleware strips it (legacy after initialize, and the modern era)."""
    from pubtator_link.server_manager import UnifiedServerManager

    app = UnifiedServerManager().create_app(include_mcp=True)
    legacy_headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        init = client.post(
            "/mcp",
            headers=legacy_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "hostile", "version": "0"},
                },
            },
        )
        assert init.status_code in {200, 202}, init.text
        session = init.headers.get("mcp-session-id")
        if session:
            legacy_headers["mcp-session-id"] = session
        legacy = client.post(
            "/mcp",
            headers=legacy_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": _EVIL_METHOD, "params": {}},
        )
        modern = _modern_post(client, 3, _EVIL_METHOD, {})

    _assert_fixed_method_not_found(legacy)
    _assert_fixed_method_not_found(modern)
