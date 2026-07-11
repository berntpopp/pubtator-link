"""Regression tests for strict HTTP Host and Origin validation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pubtator_link.config import ServerSettings
from pubtator_link.server_manager import UnifiedServerManager


def test_host_origin_defaults_are_exact_loopback_allowlists() -> None:
    parsed = ServerSettings(_env_file=None)

    assert parsed.allowed_hosts == ["localhost", "127.0.0.1", "::1"]
    assert parsed.allowed_origins == []


def test_host_origin_allowlists_parse_json_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PUBTATOR_LINK_ALLOWED_HOSTS",
        '["localhost","pubtator-link.genefoundry.org"]',
    )
    monkeypatch.setenv(
        "PUBTATOR_LINK_ALLOWED_ORIGINS",
        '["https://pubtator-link.genefoundry.org"]',
    )

    parsed = ServerSettings(_env_file=None)

    assert parsed.allowed_hosts == ["localhost", "pubtator-link.genefoundry.org"]
    assert parsed.allowed_origins == ["https://pubtator-link.genefoundry.org"]


@pytest.mark.parametrize("wildcard", ["*", "*.example.org", "host?.example.org", "host[0]"])
def test_allowed_hosts_reject_wildcard_syntax(wildcard: str) -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        ServerSettings(allowed_hosts=[wildcard], _env_file=None)


def test_guard_rejects_untrusted_host_and_origin_on_all_http_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pubtator_link.server_manager.settings.allowed_hosts",
        ["localhost", "127.0.0.1", "::1", "pubtator-link.genefoundry.org"],
        raising=False,
    )
    monkeypatch.setattr(
        "pubtator_link.server_manager.settings.allowed_origins",
        ["https://pubtator-link.genefoundry.org"],
        raising=False,
    )
    client = TestClient(UnifiedServerManager().create_app(include_mcp=True))

    for path in ("/", "/health", "/mcp"):
        assert client.get(path, headers={"Host": "attacker.example"}).status_code == 421
        assert (
            client.get(
                path,
                headers={
                    "Host": "pubtator-link.genefoundry.org",
                    "Origin": "https://attacker.example",
                },
            ).status_code
            == 403
        )


def test_guard_allows_exact_host_and_absent_or_exact_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pubtator_link.server_manager.settings.allowed_hosts",
        ["localhost", "pubtator-link.genefoundry.org"],
        raising=False,
    )
    monkeypatch.setattr(
        "pubtator_link.server_manager.settings.allowed_origins",
        ["https://pubtator-link.genefoundry.org"],
        raising=False,
    )
    client = TestClient(UnifiedServerManager().create_app())

    without_origin = client.get("/health", headers={"Host": "localhost"})
    exact_origin = client.get(
        "/health",
        headers={
            "Host": "pubtator-link.genefoundry.org",
            "Origin": "https://pubtator-link.genefoundry.org",
        },
    )

    assert without_origin.status_code == 200
    assert exact_origin.status_code == 200


def test_compose_profiles_wire_exact_allowlists_and_explicit_health_host() -> None:
    base = Path("docker/docker-compose.yml").read_text()
    prod = Path("docker/docker-compose.prod.yml").read_text()
    npm = Path("docker/docker-compose.npm.yml").read_text()

    assert "PUBTATOR_LINK_ALLOWED_HOSTS" in base
    assert "PUBTATOR_LINK_ALLOWED_ORIGINS" in base
    assert "Host: localhost" in base
    assert "Host: localhost" in prod
    assert "PUBTATOR_LINK_ALLOWED_HOSTS" in npm
    assert "PUBTATOR_LINK_ALLOWED_ORIGINS" in npm
    assert "PUBTATOR_LINK_CORS_ORIGINS" in npm
