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
