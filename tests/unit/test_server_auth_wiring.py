"""server_manager wiring: auth attach, legacy-gate gating, REST-review disable."""

import pytest
from fastapi.testclient import TestClient

from pubtator_link import server_manager as sm
from pubtator_link.security import MCPServiceAuthMiddleware
from pubtator_link.server_manager import UnifiedServerManager

_OAUTH = dict(
    auth_mode="oauth",
    oauth_authorize_url="https://kc.example.org/realms/gf/protocol/openid-connect/auth",
    oauth_token_url="https://kc.example.org/realms/gf/protocol/openid-connect/token",
    oauth_client_id="pubtator-link",
    oauth_client_secret="secret",
    oauth_jwt_signing_key="x" * 32,
    jwt_issuer="https://kc.example.org/realms/gf",
    jwt_jwks_url="https://kc.example.org/realms/gf/protocol/openid-connect/certs",
    jwt_audience="https://pubtator-link.genefoundry.org/mcp",
    public_base_url="https://pubtator-link.genefoundry.org",
    mcp_service_token="router-secret",
    mcp_profile="readonly",
    allowed_hosts=["testserver", "localhost", "127.0.0.1", "::1"],
)


def _apply(monkeypatch: pytest.MonkeyPatch, **kw: object) -> None:
    for k, v in kw.items():
        monkeypatch.setattr(sm.settings, k, v, raising=False)


def _has_legacy_gate(app: object) -> bool:
    return any(m.cls is MCPServiceAuthMiddleware for m in app.user_middleware)  # type: ignore[attr-defined]


def _has_reviews_routes(app: object) -> bool:
    for r in app.routes:  # type: ignore[attr-defined]
        orig = getattr(r, "original_router", None)
        if orig is not None and getattr(orig, "prefix", "") == "/api/reviews":
            return True
    return False


def test_none_mode_no_provider_legacy_gate_reviews_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, auth_mode="none", mcp_service_token="tok", mcp_profile="readonly")
    mgr = UnifiedServerManager()
    app = mgr.create_app(include_mcp=True)
    assert mgr.mcp.auth is None
    assert _has_legacy_gate(app) is True
    assert _has_reviews_routes(app) is True
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/mcp").status_code == 401  # legacy path gate


def test_oauth_mode_attaches_multiauth_skips_legacy_disables_rest_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply(monkeypatch, **_OAUTH)
    mgr = UnifiedServerManager()
    app = mgr.create_app(include_mcp=True)
    assert mgr.mcp.auth is not None  # MultiAuth attached
    assert _has_legacy_gate(app) is False  # no double-gate over OAuth JWTs
    assert _has_reviews_routes(app) is False  # REST review bypass removed
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        anon = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
        )
        assert anon.status_code == 401  # anonymous rejected by RequireAuthMiddleware
