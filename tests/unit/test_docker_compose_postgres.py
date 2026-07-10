import json
import shutil
import subprocess
from pathlib import Path

import yaml


def _base_compose() -> dict[str, object]:
    return yaml.safe_load(Path("docker/docker-compose.yml").read_text())


def test_base_compose_sets_explicit_project_name() -> None:
    # An explicit top-level project name isolates this stack from sibling -link
    # repos that also root their compose at docker/docker-compose.yml (which would
    # otherwise all default to the "docker" project).
    compose = _base_compose()
    assert compose["name"] == "pubtator-link"


def test_base_compose_defines_postgres_service() -> None:
    compose = _base_compose()
    services = compose["services"]
    postgres = services["pubtator-postgres"]

    assert postgres["image"].startswith("pgvector/pgvector:")
    assert "pg18" in postgres["image"]
    assert postgres["environment"]["POSTGRES_DB"] == "${PUBTATOR_LINK_POSTGRES_DB:-pubtator_link}"
    assert (
        postgres["environment"]["POSTGRES_USER"] == "${PUBTATOR_LINK_POSTGRES_USER:-pubtator_link}"
    )
    assert postgres["environment"]["POSTGRES_PASSWORD"] == (
        "${PUBTATOR_LINK_POSTGRES_PASSWORD:-pubtator_link}"  # noqa: S105
    )
    assert "pubtator_postgres_data:/var/lib/postgresql" in postgres["volumes"]
    assert (
        "../pubtator_link/db/review_schema.sql:/docker-entrypoint-initdb.d/010-review-schema.sql:ro"
    ) in postgres["volumes"]


def test_app_service_uses_postgres_database_url_and_health_dependency() -> None:
    compose = _base_compose()
    app = compose["services"]["pubtator-link"]

    assert app["environment"]["PUBTATOR_LINK_DATABASE_URL"] == (
        "postgresql://${PUBTATOR_LINK_POSTGRES_USER:-pubtator_link}:"
        "${PUBTATOR_LINK_POSTGRES_PASSWORD:-pubtator_link}@pubtator-postgres:5432/"
        "${PUBTATOR_LINK_POSTGRES_DB:-pubtator_link}"
    )
    assert app["depends_on"] == {"pubtator-postgres": {"condition": "service_healthy"}}
    assert "pubtator_postgres_data" in compose["volumes"]


def test_app_service_publishes_only_to_loopback() -> None:
    app = _base_compose()["services"]["pubtator-link"]
    assert app["ports"] == ["127.0.0.1:${PUBTATOR_LINK_PORT:-8000}:8000"]


def test_merged_production_compose_is_readonly_and_requires_service_token(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBTATOR_LINK_MCP_SERVICE_TOKEN", "compose-test-secret")
    docker = shutil.which("docker")
    assert docker is not None
    result = subprocess.run(  # noqa: S603
        [
            docker,
            "compose",
            "-f",
            "docker/docker-compose.yml",
            "-f",
            "docker/docker-compose.prod.yml",
            "-f",
            "docker/docker-compose.npm.yml",
            "config",
            "--format",
            "json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    service = json.loads(result.stdout)["services"]["pubtator-link"]
    assert service["environment"]["PUBTATOR_LINK_MCP_PROFILE"] == "readonly"
    assert (
        service["environment"]["PUBTATOR_LINK_MCP_SERVICE_TOKEN"] == "compose-test-secret"  # noqa: S105
    )
    assert service["environment"]["PUBTATOR_LINK_ALLOW_UNAUTHENTICATED_WRITES"] == "false"
    assert not service.get("ports")


def test_security_doc_documents_write_profile_posture() -> None:
    text = Path("docs/SECURITY.md").read_text(encoding="utf-8")
    for token in (
        "review_export_base_dir",
        "trust_proxy_headers",
        "mcp_profile",
        "127.0.0.1",
        "#85",
    ):
        assert token in text
