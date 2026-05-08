from pathlib import Path

import yaml


def test_compose_postgres_uses_pgvector_image() -> None:
    compose = yaml.safe_load(Path("docker/docker-compose.yml").read_text())
    image = compose["services"]["pubtator-postgres"]["image"]
    assert image.startswith("pgvector/pgvector:")
    assert "pg18" in image
