from pathlib import Path

import yaml


def _base_compose() -> dict[str, object]:
    return yaml.safe_load(Path("docker/docker-compose.yml").read_text())


def test_base_compose_defines_postgres_service() -> None:
    compose = _base_compose()
    services = compose["services"]
    postgres = services["pubtator-postgres"]

    assert postgres["image"] == "postgres:18-alpine"
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
