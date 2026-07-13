"""F-15 regression: every image reference in the production Compose files must be
digest-pinned (``@sha256:``), not tag-only.

A tag like ``pgvector/pgvector:0.8.5-pg18-trixie`` is mutable — the registry can
re-point it at a different (possibly malicious or regressed) build. Pinning the
manifest digest makes the deployed bytes reproducible and tamper-evident.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

BASE = Path("docker/docker-compose.yml")
PROD = Path("docker/docker-compose.prod.yml")
NPM = Path("docker/docker-compose.npm.yml")
ENV_EXAMPLE = Path(".env.docker.example")

COMPOSE_FILES = (BASE, PROD, NPM)


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Compose merge tags (``!reset``/``!override``)."""


def _passthrough(loader: yaml.Loader, node: yaml.Node) -> object:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_ComposeLoader.add_constructor("!reset", _passthrough)
_ComposeLoader.add_constructor("!override", _passthrough)


def _image_refs() -> list[tuple[str, str, str]]:
    """(compose_file, service, image) for every service that declares an image."""
    refs: list[tuple[str, str, str]] = []
    for path in COMPOSE_FILES:
        doc = yaml.load(path.read_text(), Loader=_ComposeLoader)  # noqa: S506
        for service, spec in (doc.get("services") or {}).items():
            image = spec.get("image") if isinstance(spec, dict) else None
            if image:
                refs.append((path.name, service, image))
    return refs


def test_every_prod_compose_image_is_digest_pinned() -> None:
    refs = _image_refs()
    assert refs, "expected at least one image reference across the compose files"
    unpinned = [(f, s, i) for f, s, i in refs if "@sha256:" not in i]
    assert not unpinned, f"tag-only (not digest-pinned) image references: {unpinned}"


def test_pgvector_image_keeps_tag_alongside_digest() -> None:
    # The digest is authoritative, but keep the human-readable tag for
    # readability/upgrade tracking: `repo:tag@sha256:...`.
    pgvector = [i for _f, _s, i in _image_refs() if i.startswith("pgvector/pgvector:")]
    assert pgvector, "expected the pgvector postgres image to be present"
    for image in pgvector:
        assert "0.8.5-pg18-trixie@sha256:" in image


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI unavailable")
def test_rendered_npm_stack_images_are_digest_pinned() -> None:
    """The fully-rendered npm production stack (base+prod+npm) must expose only
    digest-pinned images — the per-file scan can miss an image an overlay swaps in.
    """
    docker = shutil.which("docker")
    assert docker is not None
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PUBTATOR_LINK_MCP_SERVICE_TOKEN": "compose-test-token",
        "PUBTATOR_LINK_POSTGRES_PASSWORD": "compose-test-db-secret",
    }
    result = subprocess.run(  # noqa: S603
        [
            docker,
            "compose",
            "-f",
            str(BASE),
            "-f",
            str(PROD),
            "-f",
            str(NPM),
            "--env-file",
            str(ENV_EXAMPLE),
            "config",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = yaml.safe_load(result.stdout)
    images = [
        spec["image"]
        for spec in (rendered.get("services") or {}).values()
        if isinstance(spec, dict) and spec.get("image")
    ]
    assert images, "rendered npm stack should declare at least one image"
    unpinned = [i for i in images if "@sha256:" not in i]
    assert not unpinned, f"rendered npm stack has tag-only images: {unpinned}"
