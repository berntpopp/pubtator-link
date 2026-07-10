from fastapi import FastAPI
from fastapi.testclient import TestClient

from pubtator_link.security import MCPServiceAuthMiddleware


def _client(
    token: str = "service-secret",  # noqa: S107
    path: str = "/mcp",
) -> TestClient:
    app = FastAPI()
    app.add_middleware(MCPServiceAuthMiddleware, token=token, path=path)

    @app.api_route(path, methods=["GET", "POST", "DELETE"])
    async def mcp() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_mcp_service_auth_rejects_missing_and_wrong_token() -> None:
    client = _client()
    assert client.post("/mcp").status_code == 401
    assert client.post("/mcp/", follow_redirects=False).status_code == 401
    assert client.get("/mcp").status_code == 401
    assert client.delete("/mcp").status_code == 401
    response = client.post("/mcp", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_mcp_service_auth_accepts_backend_token_and_leaves_health_public() -> None:
    client = _client()
    response = client.post("/mcp", headers={"Authorization": "Bearer service-secret"})
    assert response.status_code == 200
    assert client.get("/health").status_code == 200


def test_mcp_service_auth_protects_configured_transport_path() -> None:
    client = _client(path="/pubtator-mcp")
    assert client.post("/pubtator-mcp").status_code == 401
    response = client.post(
        "/pubtator-mcp/",
        headers={"Authorization": "Bearer service-secret"},
        follow_redirects=False,
    )
    assert response.status_code in {200, 307}
