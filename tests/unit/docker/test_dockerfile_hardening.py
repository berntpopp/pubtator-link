from __future__ import annotations

from pathlib import Path

DOCKERFILE = Path("docker/Dockerfile").read_text()


def test_dockerfile_uses_python_314_and_uv_lock() -> None:
    assert "FROM python:3.14-slim" in DOCKERFILE
    assert "COPY uv.lock pyproject.toml README.md ./" in DOCKERFILE
    assert 'VIRTUAL_ENV="/opt/venv"' in DOCKERFILE
    assert "uv sync --frozen" in DOCKERFILE


def test_dockerfile_runs_as_non_root_and_has_runtime_dirs() -> None:
    assert "USER app" in DOCKERFILE
    # The production overlay mounts /tmp as the container's only writable tmpfs
    # (the central Compose policy fixes the app's writable targets at /tmp and
    # /data), so scratch must resolve to /tmp itself — not a nested subdirectory
    # that would not exist under the read-only rootfs.
    assert "TMPDIR=/tmp\n" in DOCKERFILE
    assert "/tmp/pubtator-link" not in DOCKERFILE  # noqa: S108
    assert "/var/cache/pubtator-link" in DOCKERFILE


def test_dockerfile_healthcheck_uses_internal_health_endpoint() -> None:
    assert "HEALTHCHECK" in DOCKERFILE
    assert "http://localhost:8000/health" in DOCKERFILE
