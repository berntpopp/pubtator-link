from fastapi import FastAPI
from fastapi.testclient import TestClient

from pubtator_link.security import MCPServiceAuthMiddleware


def _client(token: str = "service-secret") -> TestClient:  # noqa: S107
    app = FastAPI()
    app.add_middleware(MCPServiceAuthMiddleware, token=token)

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
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
