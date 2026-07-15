"""build_auth: none passthrough + oauth MultiAuth assembly (feat: MultiAuth)."""

import pytest
from fastmcp.server.auth import MultiAuth
from fastmcp.server.auth.providers.jwt import JWTVerifier

from pubtator_link.auth import ServiceTokenVerifier, build_auth
from pubtator_link.config import ServerSettings


def _oauth_settings(**over: object) -> ServerSettings:
    base: dict[str, object] = dict(
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
        mcp_path="/mcp",
    )
    base.update(over)
    return ServerSettings(_env_file=None, **base)


@pytest.mark.asyncio
async def test_service_token_verifier_constant_time_accept_reject() -> None:
    v = ServiceTokenVerifier("s3cret", scopes=["pubtator:read", "pubtator:write"])
    ok = await v.verify_token("s3cret")
    assert ok is not None
    assert "pubtator:write" in ok.scopes
    assert ok.client_id == "genefoundry-router"
    assert await v.verify_token("wrong") is None
    assert await v.verify_token("") is None


def test_build_auth_none_mode_returns_none() -> None:
    assert build_auth(ServerSettings(_env_file=None, auth_mode="none")) is None


def test_build_auth_oauth_returns_multiauth_audience_bound() -> None:
    auth = build_auth(_oauth_settings())
    assert isinstance(auth, MultiAuth)
    jwt_v = next(v for v in auth.verifiers if isinstance(v, JWTVerifier))
    assert jwt_v.audience == "https://pubtator-link.genefoundry.org/mcp"
    assert any(isinstance(v, ServiceTokenVerifier) for v in auth.verifiers)


@pytest.mark.asyncio
async def test_oauth_multiauth_accepts_service_token_rejects_garbage() -> None:
    auth = build_auth(_oauth_settings())
    ok = await auth.verify_token("router-secret")
    assert ok is not None
    assert "pubtator:write" in ok.scopes
    assert await auth.verify_token("not-a-real-token") is None
