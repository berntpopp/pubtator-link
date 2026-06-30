from __future__ import annotations

from pathlib import Path

import yaml

BASE = Path("docker/docker-compose.yml").read_text()
PROD = Path("docker/docker-compose.prod.yml").read_text()
NPM = Path("docker/docker-compose.npm.yml").read_text()
NPM_ENV = Path("docker/.env.npm.example").read_text()
DOCKER_ENV = Path(".env.docker.example")
DOCKERFILE = Path("docker/Dockerfile").read_text()


def test_base_compose_runs_unified_server_via_cli() -> None:
    assert "PUBTATOR_LINK_TRANSPORT: unified" in BASE
    # Streamable HTTP only: the base stack boots through the typer CLI, not a
    # raw uvicorn --factory invocation.
    assert "--factory" not in BASE
    assert '"pubtator-link", "serve"' in BASE
    assert '"--transport", "unified"' in BASE


def test_default_image_command_uses_cli_serve() -> None:
    # The default image runs `pubtator-link serve` (GeneFoundry CLI Standard v1).
    assert '"pubtator-link", "serve"' in DOCKERFILE
    assert '"--transport", "unified"' in DOCKERFILE
    assert "stdio" not in DOCKERFILE


def test_production_gunicorn_overlays_use_callable_factory_entrypoint() -> None:
    # Production / NPM overlays keep the hardened multi-worker Gunicorn
    # entrypoint, which drives the unaffected ASGI app factory.
    expected = '"pubtator_link.server_manager:create_app()"'

    for source in (PROD, NPM):
        assert '"--factory"' not in source
        assert expected in source


def test_prod_compose_has_security_controls() -> None:
    assert "read_only: true" in PROD
    assert "no-new-privileges:true" in PROD
    assert "cap_drop:" in PROD
    assert "- ALL" in PROD
    assert "/tmp/pubtator-link" in PROD  # noqa: S108
    assert "mode=1777" in PROD


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


def test_base_compose_binds_published_ports_to_loopback() -> None:
    compose = yaml.safe_load(BASE)
    published = [
        (name, mapping)
        for name, svc in compose["services"].items()
        for mapping in (svc.get("ports") or [])
    ]
    assert published, "base compose should publish at least one host port"
    for name, mapping in published:
        assert isinstance(mapping, str) and mapping.startswith("127.0.0.1:"), (
            f"{name} publishes {mapping!r} on all interfaces; loopback-bind it "
            "(127.0.0.1) so the unauthenticated backend is never exposed on the host IP"
        )
