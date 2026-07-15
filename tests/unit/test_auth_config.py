"""AUTH_MODE config + oauth validation (feat: MultiAuth)."""

import pytest

from pubtator_link.config import ServerSettings


def _oauth_kwargs(**over: object) -> dict[str, object]:
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
    return base


def test_auth_mode_defaults_to_none_and_validate_is_noop() -> None:
    s = ServerSettings(_env_file=None)
    assert s.auth_mode == "none"
    assert s.require_write_scope is False
    s.validate_oauth_config()  # no-op in none mode


def test_oauth_mode_missing_everything_raises() -> None:
    s = ServerSettings(_env_file=None, auth_mode="oauth")
    with pytest.raises(ValueError, match="oauth mode requires"):
        s.validate_oauth_config()


def test_oauth_requires_signing_key() -> None:
    s = ServerSettings(_env_file=None, **_oauth_kwargs(oauth_jwt_signing_key=None))
    with pytest.raises(ValueError, match="OAUTH_JWT_SIGNING_KEY"):
        s.validate_oauth_config()


def test_oauth_requires_service_token() -> None:
    s = ServerSettings(_env_file=None, **_oauth_kwargs(mcp_service_token=None))
    with pytest.raises(ValueError, match="MCP_SERVICE_TOKEN"):
        s.validate_oauth_config()


def test_public_base_url_must_be_bare_origin() -> None:
    s = ServerSettings(_env_file=None, **_oauth_kwargs(public_base_url="https://host/mcp"))
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        s.validate_oauth_config()


def test_audience_must_equal_base_plus_mcp_path() -> None:
    s = ServerSettings(
        _env_file=None,
        **_oauth_kwargs(jwt_audience="https://pubtator-link.genefoundry.org/wrong"),
    )
    with pytest.raises(ValueError, match="JWT_AUDIENCE"):
        s.validate_oauth_config()


def test_valid_oauth_config_passes() -> None:
    ServerSettings(_env_file=None, **_oauth_kwargs()).validate_oauth_config()
