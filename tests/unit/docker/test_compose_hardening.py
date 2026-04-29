from __future__ import annotations

from pathlib import Path


BASE = Path("docker/docker-compose.yml").read_text()
PROD = Path("docker/docker-compose.prod.yml").read_text()


def test_base_compose_runs_unified_server_with_mcp() -> None:
    assert "PUBTATOR_LINK_TRANSPORT: unified" in BASE
    assert "pubtator_link.server_manager:app" in BASE


def test_prod_compose_has_security_controls() -> None:
    assert "read_only: true" in PROD
    assert "no-new-privileges:true" in PROD
    assert "cap_drop:" in PROD
    assert "- ALL" in PROD
    assert "/tmp/pubtator-link" in PROD


def test_prod_compose_does_not_publish_extra_ports() -> None:
    assert "ports: []" in PROD
