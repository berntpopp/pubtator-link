from __future__ import annotations

from pathlib import Path

import yaml

BASE = Path("docker/docker-compose.yml").read_text()
PROD = Path("docker/docker-compose.prod.yml").read_text()
NPM = Path("docker/docker-compose.npm.yml").read_text()
NPM_ENV = Path("docker/.env.npm.example").read_text()
DOCKER_ENV = Path(".env.docker.example")
DOCKERFILE = Path("docker/Dockerfile").read_text()


def test_base_compose_serves_unified_transport_via_the_image_default() -> None:
    assert "PUBTATOR_LINK_TRANSPORT: unified" in BASE
    # Streamable HTTP only: no raw uvicorn --factory invocation.
    assert "--factory" not in BASE
    # The container-release standard forbids a Compose `command:` override on the
    # application service in the production render. Keeping the base file free of
    # one means the CI smoke stack (base + generated override) exercises exactly
    # the process the released image runs in production.
    base = yaml.safe_load(BASE)
    app = base["services"]["pubtator-link"]
    assert "command" not in app
    assert "entrypoint" not in app


def test_dev_overlay_keeps_the_typer_cli_entrypoint() -> None:
    # GeneFoundry Logging & CLI Standard v1: `pubtator-link serve` stays the
    # interactive/dev entrypoint even though the image default is Gunicorn.
    dev = Path("docker/docker-compose.dev.yml").read_text()
    assert "pubtator-link serve" in dev


def test_default_image_command_is_the_production_gunicorn_entrypoint() -> None:
    # The released image must already run the exact production process, because
    # the central Compose policy rejects a `command:`/`entrypoint:` override on
    # the application service.
    assert (
        'CMD ["gunicorn", "-c", "gunicorn_conf.py", '
        '"pubtator_link.server_manager:create_app()"]' in DOCKERFILE
    )
    assert '"--factory"' not in DOCKERFILE
    assert "stdio" not in DOCKERFILE


def test_production_overlays_never_override_the_image_process() -> None:
    # A `command:`/`entrypoint:` override on the application service is a policy
    # violation in the effective production render; the only permitted mention is
    # the explicit `!reset` that strips an inherited one.
    for source in (PROD, NPM):
        for override in ("command:", "entrypoint:"):
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith(override):
                    assert stripped == f"{override} !reset null", (
                        f"production overlay overrides the image process: {stripped!r}"
                    )


def test_prod_compose_has_security_controls() -> None:
    assert "read_only: true" in PROD
    assert "no-new-privileges:true" in PROD
    assert "cap_drop:" in PROD
    assert "- ALL" in PROD
    # The central policy fixes the application's writable targets at /tmp (tmpfs)
    # and /data; a nested /tmp/pubtator-link tmpfs is no longer accepted.
    assert "/tmp:rw,noexec,nosuid" in PROD  # noqa: S108
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
