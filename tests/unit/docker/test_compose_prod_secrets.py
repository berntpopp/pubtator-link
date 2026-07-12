"""F-14 regression: the production compose path must REQUIRE the DB secret with
no predictable fallback.

The base ``docker/docker-compose.yml`` intentionally ships a developer default
(``pubtator_link``) so a fresh checkout runs. The production overlay must strip
that fallback and fail closed when ``PUBTATOR_LINK_POSTGRES_PASSWORD`` is unset,
so the predictable credential can never reach a deployed database.
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

PASSWORD_VAR = "PUBTATOR_LINK_POSTGRES_PASSWORD"  # noqa: S105 (env var name, not a secret)
# ``${VAR:?msg}`` fails when VAR is unset; ``${VAR:-default}`` supplies a
# fallback. Production must use the former for the DB secret.
REQUIRED = f"${{{PASSWORD_VAR}:?"
FALLBACK = f"${{{PASSWORD_VAR}:-"


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


def _prod() -> dict[str, object]:
    # _ComposeLoader subclasses SafeLoader; the extra tags are inert pass-throughs.
    return yaml.load(PROD.read_text(), Loader=_ComposeLoader)  # noqa: S506


def test_prod_postgres_password_requires_secret_without_fallback() -> None:
    prod = _prod()
    password = prod["services"]["pubtator-postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert password.startswith(REQUIRED), (
        f"production POSTGRES_PASSWORD must use ${{...:?}} (fail-closed), got {password!r}"
    )
    assert FALLBACK not in password, "production must not carry a predictable password fallback"


def test_prod_database_url_requires_secret_without_fallback() -> None:
    prod = _prod()
    dsn = prod["services"]["pubtator-link"]["environment"]["PUBTATOR_LINK_DATABASE_URL"]
    assert REQUIRED in dsn, "production DATABASE_URL must require the DB secret via ${...:?}"
    assert FALLBACK not in dsn, (
        "production DATABASE_URL must not carry a predictable password fallback"
    )


def test_base_compose_still_has_dev_fallback() -> None:
    # The base (dev) compose keeps the fallback so a bare `docker compose up`
    # works locally; only the prod overlay strips it.
    base = yaml.safe_load(BASE.read_text())
    password = base["services"]["pubtator-postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert FALLBACK in password


def _config(*, with_password: bool) -> subprocess.CompletedProcess[str]:
    docker = shutil.which("docker")
    assert docker is not None
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        # Satisfy the unrelated ${...:?required} service-token guard so the run
        # can fail (or pass) specifically on the DB password.
        "PUBTATOR_LINK_MCP_SERVICE_TOKEN": "compose-test-token",
    }
    if with_password:
        env[PASSWORD_VAR] = "compose-test-db-secret"
    return subprocess.run(  # noqa: S603
        [docker, "compose", "-f", str(BASE), "-f", str(PROD), "config"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI unavailable")
def test_prod_compose_config_fails_without_db_password() -> None:
    result = _config(with_password=False)
    assert result.returncode != 0, "prod compose config must fail when the DB secret is absent"
    assert PASSWORD_VAR in result.stderr


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI unavailable")
def test_prod_compose_config_succeeds_with_db_password() -> None:
    result = _config(with_password=True)
    assert result.returncode == 0, result.stderr
    assert "compose-test-db-secret" in result.stdout
    assert "pubtator_link@pubtator-postgres" not in result.stdout
