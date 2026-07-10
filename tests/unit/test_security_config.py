import pytest
from pydantic import ValidationError

from pubtator_link.config import ServerSettings


def test_write_profile_requires_service_token_or_explicit_local_exception() -> None:
    with pytest.raises(ValidationError, match="write-capable MCP profile requires"):
        ServerSettings(
            _env_file=None,
            mcp_profile="full",
            mcp_service_token=None,
            allow_unauthenticated_writes=False,
        )


def test_lean_profile_requires_service_token() -> None:
    with pytest.raises(ValidationError, match="write-capable MCP profile requires"):
        ServerSettings(
            _env_file=None,
            mcp_profile="lean",
            mcp_service_token=None,
            allow_unauthenticated_writes=False,
        )


def test_readonly_profile_does_not_require_service_token() -> None:
    settings = ServerSettings(
        _env_file=None,
        mcp_profile="readonly",
        mcp_service_token=None,
    )
    assert settings.mcp_profile == "readonly"


def test_unauthenticated_write_exception_is_loopback_only() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        ServerSettings(
            _env_file=None,
            host="0.0.0.0",  # noqa: S104
            mcp_profile="full",
            mcp_service_token=None,
            allow_unauthenticated_writes=True,
        )


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_explicit_loopback_exception_allows_local_writes(host: str) -> None:
    settings = ServerSettings(
        _env_file=None,
        host=host,
        mcp_profile="full",
        mcp_service_token=None,
        allow_unauthenticated_writes=True,
    )
    assert settings.allow_unauthenticated_writes is True
