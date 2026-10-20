"""Contract tests for the container release trigger and target platform."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "container-release.yml"
MANIFEST = ROOT / "container-release.json"


def _workflow() -> dict[str, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_container_release_runs_only_for_strict_semver_tags() -> None:
    """A release must require vMAJOR.MINOR.PATCH, not any v-prefixed tag."""
    triggers = _workflow().get("on", _workflow().get(True, {}))
    assert triggers["push"]["tags"] == ["v*.*.*"]


def test_container_release_manifest_declares_linux_amd64_platform() -> None:
    """The release contract must make its single supported image platform explicit."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["platform"] == "linux/amd64"


def test_release_gate_rejects_tags_outside_central_stable_semver_contract() -> None:
    """Invalid tag pushes must stop before invoking the reusable release workflow."""
    workflow = _workflow()
    gate = workflow["jobs"]["validate-tag"]
    gate_run = gate["steps"][0]["run"]
    stable_ref = re.compile(
        r"^refs/tags/v(?:0|[1-9][0-9]{0,63})\.(?:0|[1-9][0-9]{0,63})\.(?:0|[1-9][0-9]{0,63})$"
    )

    for tag in ("v0.0.0", "v1.2.3", f"v{'9' * 64}.1.1"):
        assert stable_ref.fullmatch(f"refs/tags/{tag}") is not None

    for tag in (
        "v1.2",
        "v1.2.3-rc.1",
        "v1.2.3+build",
        "v1.two.3",
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
        f"v{'9' * 65}.1.1",
    ):
        assert stable_ref.fullmatch(f"refs/tags/{tag}") is None

    assert '"$EVENT_REF"' in gate_run
    assert "refs/tags/v(0|[1-9][0-9]{0,63})\\.(0|[1-9][0-9]{0,63})" in gate_run
    assert "exit 1" in gate_run
    assert workflow["jobs"]["container-release"]["needs"] == "validate-tag"


def test_container_release_manifest_declares_the_deployed_overlay() -> None:
    """The fleet controller deploys this repo layered (base + prod + npm), not the npm
    overlay standalone. The router's `validate-deployed-overlay` gate can only check what
    is actually deployed if `container-release.json` says so explicitly; a drift here
    silently re-validates a stack nobody runs.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    service = manifest["service"]

    assert service["deployed_compose_files"] == [
        "docker/docker-compose.yml",
        "docker/docker-compose.prod.yml",
        "docker/docker-compose.npm.yml",
    ]

    sidecars = {sidecar["name"]: sidecar["image"] for sidecar in service["deployed_sidecars"]}
    assert sidecars["pubtator-postgres"] == (
        "docker.io/pgvector/pgvector@"
        "sha256:1963bc48febf543433baa1ce3edcc6cc08154de722e22495f86681cc9a849026"
    )
