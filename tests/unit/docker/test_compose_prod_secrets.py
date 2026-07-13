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
NPM = Path("docker/docker-compose.npm.yml")
ENV_EXAMPLE = Path(".env.docker.example")
DOCKER_README = Path("docker/README.md")
MAKEFILE = Path("Makefile")

PASSWORD_VAR = "PUBTATOR_LINK_POSTGRES_PASSWORD"  # noqa: S105 (env var name, not a secret)
# ``${VAR:?msg}`` fails when VAR is unset; ``${VAR:-default}`` supplies a
# fallback. Production must use the former for the DB secret.
REQUIRED = f"${{{PASSWORD_VAR}:?"
FALLBACK = f"${{{PASSWORD_VAR}:-"

# Values a predictable/committed default would render into a deployed credential.
# ``pubtator_link`` is the base-compose dev fallback and doubles as the DB
# name/user, so it is only "predictable" when it lands in the password position
# (``:pubtator_link@`` in a DSN or ``POSTGRES_PASSWORD: pubtator_link``).
PREDICTABLE_PASSWORD = "change-me"  # noqa: S105 (test literal, not a live secret)


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
        "PUBTATOR_LINK_IMAGE": (
            "ghcr.io/berntpopp/pubtator-link@sha256:"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
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


# --------------------------------------------------------------------------- #
# F-14 residual (b): the NPM production overlay must also require the DB secret
# with no predictable fallback, and the config-validation path must render a
# throwaway (non-predictable) credential, never a committed ``change-me``.
# --------------------------------------------------------------------------- #


def test_docker_readme_documents_no_predictable_prod_db_password() -> None:
    """F-14 doc gate: ``docker/README.md`` must not present the predictable DB
    password as a production example.

    The prod/npm overlays already require ``PUBTATOR_LINK_POSTGRES_PASSWORD`` from
    a secret store with no fallback. The README must not undermine that by
    documenting the predictable ``pubtator_link`` credential as a production env
    assignment; the env-config block must instead direct operators to a secret
    store. A purely-local ``make db-init`` command may keep the dev fallback only
    because it is explicitly labelled local-dev-only on the host-published dev
    port that the prod overlays never expose.
    """
    text = DOCKER_README.read_text()
    predictable_assignment = f"{PASSWORD_VAR}=pubtator_link"
    assert predictable_assignment not in text, (
        f"docker/README.md documents the predictable production credential "
        f"{predictable_assignment!r}; require it from a secret store instead"
    )
    assert f"{PASSWORD_VAR}=<from-secret-store>" in text, (
        "docker/README.md env block must present the DB password as a required "
        "secret-store placeholder, not a predictable default"
    )


def test_env_docker_example_ships_no_predictable_db_password() -> None:
    """The NPM/production env template must not ship a predictable DB password.

    ``docker compose config`` on the npm stack renders whatever
    ``PUBTATOR_LINK_POSTGRES_PASSWORD`` resolves to verbatim; a committed
    ``change-me`` would become the deployed credential. The secret must be
    injected from a secret store, so any assignment in the template is a defect.
    """
    for raw in ENV_EXAMPLE.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        assert key.strip() != PASSWORD_VAR, (
            f"{ENV_EXAMPLE} must not ship an active {PASSWORD_VAR} "
            f"(found {value.strip()!r}); require it from the secret store instead"
        )


@pytest.mark.skipif(shutil.which("make") is None, reason="make unavailable")
def test_make_config_targets_inject_dummy_db_password() -> None:
    """`make docker-prod-config`/`docker-npm-config` must self-supply a throwaway
    DB password so CI config-validation renders the ``${VAR:?}`` guard
    deterministically. The dummy is a config-validation value, never a real secret.
    """
    make = shutil.which("make")
    assert make is not None
    for target in ("docker-prod-config", "docker-npm-config"):
        # ``make -n`` expands variables and prints the recipe WITHOUT executing it.
        result = subprocess.run(  # noqa: S603
            [make, "-n", target],
            text=True,
            capture_output=True,
            check=True,
        )
        assert f"{PASSWORD_VAR}=" in result.stdout, (
            f"`make {target}` must inject a dummy {PASSWORD_VAR} for config "
            f"validation; expanded recipe:\n{result.stdout}"
        )


def _npm_config(*, with_password: bool) -> subprocess.CompletedProcess[str]:
    """Render the full npm production stack (base+prod+npm) exactly as the
    ``docker-npm-config`` Make target does, minus the target's injected secrets.
    """
    docker = shutil.which("docker")
    assert docker is not None
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        # Satisfy the unrelated ${...:?required} service-token guard.
        "PUBTATOR_LINK_MCP_SERVICE_TOKEN": "compose-test-token",
    }
    if with_password:
        env[PASSWORD_VAR] = "compose-test-db-secret"
    return subprocess.run(  # noqa: S603
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


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI unavailable")
def test_npm_compose_config_fails_without_db_password() -> None:
    result = _npm_config(with_password=False)
    assert result.returncode != 0, "npm compose config must fail when the DB secret is absent"
    assert PASSWORD_VAR in result.stderr


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI unavailable")
def test_npm_compose_config_renders_no_predictable_password() -> None:
    result = _npm_config(with_password=True)
    assert result.returncode == 0, result.stderr
    assert "compose-test-db-secret" in result.stdout
    assert PREDICTABLE_PASSWORD not in result.stdout, "npm stack rendered the predictable password"
    # Predictable dev fallback in the DSN password position (``:pubtator_link@``).
    assert "pubtator_link@pubtator-postgres" not in result.stdout


@pytest.mark.skipif(
    shutil.which("docker") is None or shutil.which("make") is None,
    reason="docker/make unavailable",
)
def test_make_docker_prod_config_passes_without_ambient_secret() -> None:
    """Regression for the CI break: `make docker-prod-config` must succeed even
    when no ``PUBTATOR_LINK_POSTGRES_PASSWORD`` is present in the caller's env.
    """
    make = shutil.which("make")
    assert make is not None
    env = dict(os.environ)
    env.pop(PASSWORD_VAR, None)
    env.pop("PUBTATOR_LINK_MCP_SERVICE_TOKEN", None)
    result = subprocess.run(  # noqa: S603
        [make, "docker-prod-config"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    shutil.which("docker") is None or shutil.which("make") is None,
    reason="docker/make unavailable",
)
def test_make_docker_npm_config_passes_without_ambient_secret() -> None:
    """`make docker-npm-config` must succeed with no ambient secret and must not
    render the predictable ``change-me`` credential.
    """
    make = shutil.which("make")
    assert make is not None
    env = dict(os.environ)
    env.pop(PASSWORD_VAR, None)
    env.pop("PUBTATOR_LINK_MCP_SERVICE_TOKEN", None)
    result = subprocess.run(  # noqa: S603
        [make, "docker-npm-config"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert PREDICTABLE_PASSWORD not in result.stdout, "npm config rendered the predictable password"
