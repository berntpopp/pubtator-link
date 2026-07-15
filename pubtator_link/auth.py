"""Edge auth assembly for PubTator-Link (AUTH_MODE = none | oauth).

No-token-passthrough: the router authenticates the *caller* at its own edge and
reaches this backend with its OWN static service credential — never the caller's
OAuth token. That credential is the ``ServiceTokenVerifier`` principal here.

In ``oauth`` mode one ``/mcp`` accepts either a Keycloak-issued JWT (standalone
users, via ``OAuthProxy``) or the router's static service token, both mapped to
the ``full`` write surface. ``none`` mode returns ``None`` (today's behavior).
"""

from __future__ import annotations

import secrets
from typing import Any

from fastmcp.server.auth import AccessToken, TokenVerifier

from pubtator_link.config import ServerSettings

SERVICE_SCOPES: list[str] = ["pubtator:read", "pubtator:write"]


class ServiceTokenVerifier(TokenVerifier):
    """Constant-time verifier for the single router-owned service token."""

    def __init__(
        self,
        token: str,
        *,
        client_id: str = "genefoundry-router",
        scopes: list[str],
    ) -> None:
        super().__init__()
        self._token = token
        self._client_id = client_id
        self._scopes = list(scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not secrets.compare_digest(token, self._token):
            return None
        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=list(self._scopes),
            expires_at=None,
        )


def build_auth(settings: ServerSettings) -> Any | None:
    """Return a FastMCP auth provider for the configured mode, or None for none."""
    if settings.auth_mode == "none":
        return None
    return _build_oauth(settings)


def _build_oauth(settings: ServerSettings) -> Any:
    """oauth mode: MultiAuth = Keycloak OAuthProxy + JWT verifier + router token.

    Copies the router's proven wiring, including ``resource_base_url`` = the ROOT
    origin (NOT the audience) so the advertised resource is not doubled to
    ``/mcp/mcp``. ``validate_oauth_config`` has already enforced that invariant.
    """
    settings.validate_oauth_config()
    from fastmcp.server.auth import MultiAuth, OAuthProxy
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    # validate_oauth_config guarantees these are set; narrow str | None -> str.
    assert settings.oauth_authorize_url and settings.oauth_token_url
    assert settings.oauth_client_id and settings.public_base_url

    verifier = JWTVerifier(
        jwks_uri=settings.jwt_jwks_url,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,  # reject tokens not minted for this resource
        base_url=settings.public_base_url,
    )
    oauth = OAuthProxy(
        upstream_authorization_endpoint=settings.oauth_authorize_url,
        upstream_token_endpoint=settings.oauth_token_url,
        upstream_client_id=settings.oauth_client_id,
        upstream_client_secret=settings.oauth_client_secret,
        token_verifier=verifier,
        base_url=settings.public_base_url,  # ROOT origin (/authorize, /auth/callback live here)
        resource_base_url=settings.public_base_url,  # ROOT origin — NOT the audience
        jwt_signing_key=settings.oauth_jwt_signing_key,
        require_authorization_consent="external",  # Keycloak owns login+consent
        # Bound downstream (MCP-client) redirects; empty -> None = unrestricted (dev only,
        # production MUST set PUBTATOR_LINK_OAUTH_ALLOWED_CLIENT_REDIRECT_URIS).
        allowed_client_redirect_uris=settings.oauth_allowed_client_redirect_uris or None,
        valid_scopes=list(SERVICE_SCOPES),
    )
    verifiers: list[Any] = [verifier]
    if settings.mcp_service_token:
        verifiers.append(ServiceTokenVerifier(settings.mcp_service_token, scopes=SERVICE_SCOPES))
    return MultiAuth(server=oauth, verifiers=verifiers)
