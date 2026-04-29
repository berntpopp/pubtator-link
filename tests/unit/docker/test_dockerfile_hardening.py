from __future__ import annotations

from pathlib import Path


DOCKERFILE = Path("docker/Dockerfile").read_text()


def test_dockerfile_uses_python_311_and_uv_lock() -> None:
    assert "FROM python:3.11-slim" in DOCKERFILE
    assert "COPY uv.lock pyproject.toml README.md ./" in DOCKERFILE
    assert "uv sync --frozen" in DOCKERFILE


def test_dockerfile_runs_as_non_root_and_has_runtime_dirs() -> None:
    assert "USER app" in DOCKERFILE
    assert "/tmp/pubtator-link" in DOCKERFILE
    assert "/var/cache/pubtator-link" in DOCKERFILE


def test_dockerfile_healthcheck_uses_internal_health_endpoint() -> None:
    assert "HEALTHCHECK" in DOCKERFILE
    assert "http://localhost:8000/health" in DOCKERFILE
