"""The declared auxiliary sidecar must match the effective production Compose.

``container-release.json -> service.auxiliary`` is the contract the router's central
``validate-compose`` gate enforces at CI/release time. A sidecar is authorized by its
*role*, never by its name, so every field the role policy checks (writable targets,
readiness probe, egress) has to agree with what Compose actually renders. These tests
catch that drift locally, before the central gate does.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CONFIG = json.loads(Path("container-release.json").read_text())
BASE = Path("docker/docker-compose.yml")
PROD = Path("docker/docker-compose.prod.yml")

SIDECAR = "pubtator-postgres"
FAKE_IMAGE = "ghcr.io/berntpopp/pubtator-link@sha256:" + "a" * 64


def _auxiliary() -> dict[str, Any]:
    declared = {entry["name"]: entry for entry in CONFIG["service"]["auxiliary"]}
    assert SIDECAR in declared, f"{SIDECAR} must be a declared auxiliary service"
    return declared[SIDECAR]


def test_postgres_sidecar_is_declared_with_the_database_role() -> None:
    auxiliary = _auxiliary()
    assert auxiliary["role"] == "database"
    # A database role must be reachable on an approved project network and must
    # declare a non-empty readiness probe.
    assert auxiliary["egress"] == "approved-networks"
    assert auxiliary["healthcheck_test"]
    assert auxiliary["writable_targets"]
    assert not set(auxiliary["writable_targets"]) & set(auxiliary.get("read_only_targets", []))


def test_smoke_profile_matches_the_restored_database_mode() -> None:
    assert CONFIG["data"]["mode"] == "restored-database"
    assert CONFIG["smoke"]["profile"] == "postgres-bundle"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI unavailable")
def test_rendered_sidecar_matches_the_declared_role_contract() -> None:
    docker = shutil.which("docker")
    assert docker is not None
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PUBTATOR_LINK_IMAGE": FAKE_IMAGE,
        "PUBTATOR_LINK_MCP_SERVICE_TOKEN": "compose-test-token",
        "PUBTATOR_LINK_POSTGRES_PASSWORD": "compose-test-db-secret",
    }
    result = subprocess.run(  # noqa: S603
        [
            docker,
            "compose",
            "--project-name",
            CONFIG["service"]["name"],
            "-f",
            str(BASE),
            "-f",
            str(PROD),
            "config",
            "--format",
            "json",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    auxiliary = _auxiliary()
    sidecar = rendered["services"][SIDECAR]

    # The readiness probe the role policy compares against, verbatim.
    assert sidecar["healthcheck"]["test"] == auxiliary["healthcheck_test"]

    # Hardening every container in the stack must satisfy.
    assert sidecar["read_only"] is True
    assert sidecar["cap_drop"] == ["ALL"]
    assert sidecar["security_opt"] == ["no-new-privileges:true"]
    assert sidecar["pull_policy"] == "missing"
    assert (
        "@sha256:" in sidecar["image"]
        and ":" not in sidecar["image"].rsplit("/", 1)[-1].split("@")[0]
    ), "the sidecar image must be an untagged repository digest"
    assert not sidecar.get("ports")
    assert "container_name" not in sidecar
    assert "user" not in sidecar
    assert "pids_limit" not in sidecar
    assert set(sidecar["deploy"]["resources"]["limits"]) == {"cpus", "memory", "pids"}
    assert sidecar["logging"]["driver"] == "json-file"

    # Every declared writable target must actually be writable storage, and the
    # persistent ones must be Compose-managed named volumes (never host binds).
    mounts = {mount["target"]: mount for mount in sidecar.get("volumes", [])}
    tmpfs = {entry.split(":", 1)[0] for entry in sidecar.get("tmpfs", [])}
    for target in auxiliary["writable_targets"]:
        assert target in mounts or target in tmpfs, f"{target} is declared writable but not mounted"
    for mount in mounts.values():
        assert mount["type"] == "volume", "a database sidecar may not use a host bind mount"
        assert not mount.get("read_only")

    # The application gates on the sidecar with the role's exact condition.
    app = rendered["services"][CONFIG["service"]["name"]]
    assert app["depends_on"][SIDECAR]["condition"] == "service_healthy"


def test_base_compose_gives_the_sidecar_writable_socket_storage() -> None:
    """The read-only rootfs needs PostgreSQL's socket dir as a *named volume*.

    The central smoke stack replaces the sidecar's ``tmpfs:`` list wholesale with
    its own ``/tmp`` cap, so a tmpfs at ``/var/run/postgresql`` would silently
    vanish there and PostgreSQL would fail to create its Unix socket.
    """
    base = yaml.safe_load(BASE.read_text())
    volumes = base["services"][SIDECAR]["volumes"]
    assert "pubtator_postgres_run:/var/run/postgresql" in volumes
    assert "pubtator_postgres_run" in base["volumes"]
