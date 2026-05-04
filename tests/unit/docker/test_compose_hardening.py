from __future__ import annotations

from pathlib import Path

BASE = Path("docker/docker-compose.yml").read_text()
PROD = Path("docker/docker-compose.prod.yml").read_text()
NPM = Path("docker/docker-compose.npm.yml").read_text()
NPM_ENV = Path("docker/.env.npm.example").read_text()
DOCKER_ENV = Path(".env.docker.example")


def test_base_compose_runs_unified_server_with_mcp() -> None:
    assert "PUBTATOR_LINK_TRANSPORT: unified" in BASE
    assert "pubtator_link.server_manager:app" in BASE


def test_prod_compose_has_security_controls() -> None:
    assert "read_only: true" in PROD
    assert "no-new-privileges:true" in PROD
    assert "cap_drop:" in PROD
    assert "- ALL" in PROD
    assert "/tmp/pubtator-link" in PROD  # noqa: S108


def test_prod_compose_does_not_publish_extra_ports() -> None:
    assert "ports: []" in PROD


def test_npm_compose_matches_shared_network_pattern() -> None:
    assert "npm_shared:" in NPM
    assert "external: true" in NPM
    assert "${NPM_SHARED_NETWORK_NAME:-npm_default}" in NPM
    assert "ports: []" in NPM


def test_npm_environment_documents_public_url_and_cors() -> None:
    assert "PUBTATOR_LINK_PUBLIC_DOMAIN" in NPM_ENV
    assert "PUBTATOR_LINK_PUBLIC_URL" in NPM_ENV
    assert "PUBTATOR_LINK_CORS_ORIGINS" in NPM_ENV


def test_root_docker_env_example_matches_vps_manager_contract() -> None:
    assert DOCKER_ENV.exists()
    env = DOCKER_ENV.read_text()

    assert "NPM_SHARED_NETWORK_NAME=npm_default" in env
    assert "PUBTATOR_LINK_PUBLIC_DOMAIN=" in env
    assert "PUBTATOR_LINK_PUBLIC_URL=" in env
    assert "PUBTATOR_LINK_CORS_ORIGINS=" in env
