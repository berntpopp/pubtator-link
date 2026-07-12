"""F-19 regression: the Docker builder must not bootstrap a floating pip/uv
upgrade. Instead it copies a digest-pinned `uv` binary so the toolchain is
reproducible and tamper-evident.
"""

from __future__ import annotations

from pathlib import Path

DOCKERFILE = Path("docker/Dockerfile").read_text()

# Digest-pinned uv (Shared Primitive P-A) — must stay in sync across the fleet.
UV_PINNED_COPY = (
    "COPY --from=ghcr.io/astral-sh/uv:0.8.7@sha256:"
    "1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab "
    "/uv /usr/local/bin/uv"
)


def test_dockerfile_has_no_floating_pip_upgrade() -> None:
    assert "pip install --upgrade" not in DOCKERFILE, (
        "floating pip/uv upgrade must be removed; pin the toolchain instead"
    )


def test_dockerfile_pins_uv_via_digest_copy() -> None:
    assert UV_PINNED_COPY in DOCKERFILE


def test_dockerfile_uv_copy_precedes_uv_sync() -> None:
    # The pinned uv must be available before `uv sync` runs in the builder stage.
    assert UV_PINNED_COPY in DOCKERFILE
    assert "uv sync --frozen" in DOCKERFILE
    assert DOCKERFILE.index(UV_PINNED_COPY) < DOCKERFILE.index("uv sync --frozen")
