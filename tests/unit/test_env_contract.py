"""The environment contract must be true, and machine-checked.

GeneFoundry README Standard v1: a documented fact that no machine checks will rot.
This module pins the four env facts the docs assert, so a future edit that
re-introduces a false one fails here instead of shipping.

1. ``ServerSettings`` reads env under the ``PUBTATOR_LINK_`` prefix, and ONLY under
   that prefix. ``extra="ignore"`` means an unprefixed name is silently dropped —
   no error, no warning, no effect. Docs must never promise otherwise.
2. Every variable in ``.env.example`` is prefixed and names a real setting. An
   unprefixed row there is dead config that an operator will reasonably expect to work.
3. Every variable in the ``docs/configuration.md`` tables names a real setting.
4. ``cp .env.example .env`` — the README quick start — yields a loadable config.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pubtator_link.config import ServerSettings

ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_DOC = ROOT / "docs/configuration.md"
COMPOSE = ROOT / "docker/docker-compose.yml"

PREFIX = "PUBTATOR_LINK_"

# Consumed by docker-compose interpolation (``${PUBTATOR_LINK_POSTGRES_*}``), not by
# ServerSettings. The exemption is itself checked below against the compose file, so
# it cannot become a rubber stamp for a typo.
COMPOSE_ONLY = {
    "PUBTATOR_LINK_POSTGRES_DB",
    "PUBTATOR_LINK_POSTGRES_USER",
    "PUBTATOR_LINK_POSTGRES_PASSWORD",
    "PUBTATOR_LINK_POSTGRES_PORT",
}

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.M)
# The first cell of a markdown table row, e.g. "| `PUBTATOR_LINK_PORT` | ... |".
_TABLE_ROW = re.compile(r"^\|\s*(.+?)\s*\|", re.M)
_BACKTICKED = re.compile(r"`([A-Z][A-Z0-9_]*)`")


def _settings_env_names() -> set[str]:
    return {f"{PREFIX}{name.upper()}" for name in ServerSettings.model_fields}


def _env_example_names() -> list[str]:
    return _ASSIGNMENT.findall(ENV_EXAMPLE.read_text(encoding="utf-8"))


def _documented_names() -> set[str]:
    names: set[str] = set()
    for cell in _TABLE_ROW.findall(CONFIG_DOC.read_text(encoding="utf-8")):
        names.update(_BACKTICKED.findall(cell))
    return names


def test_settings_read_only_the_prefixed_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prefix is the whole contract: unprefixed names do nothing."""
    assert ServerSettings.model_config["env_prefix"] == PREFIX

    monkeypatch.setenv("HOST", "9.9.9.9")
    monkeypatch.setenv("PORT", "1234")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("RATE_LIMIT_PER_SECOND", "0.5")
    monkeypatch.setenv(f"{PREFIX}HOST", "10.0.0.1")

    parsed = ServerSettings(_env_file=None)

    # The prefixed name wins; the unprefixed ones are dropped, not merged.
    assert parsed.host == "10.0.0.1"
    assert parsed.port == 8000
    assert parsed.log_level == "INFO"
    assert parsed.rate_limit_per_second == 2.5


def test_compose_only_exemptions_are_really_used_by_compose() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    for name in COMPOSE_ONLY:
        assert f"${{{name}" in compose, f"{name} is exempted but compose never interpolates it"


def test_env_example_names_are_prefixed_and_real() -> None:
    """A row in .env.example that no setting reads is config that silently does nothing."""
    known = _settings_env_names() | COMPOSE_ONLY

    unprefixed = [name for name in _env_example_names() if not name.startswith(PREFIX)]
    assert not unprefixed, (
        f".env.example ships unprefixed names that ServerSettings ignores: {sorted(unprefixed)}"
    )

    unknown = [name for name in _env_example_names() if name not in known]
    assert not unknown, f".env.example names settings that do not exist: {sorted(unknown)}"


def test_configuration_doc_documents_only_real_settings() -> None:
    known = _settings_env_names() | COMPOSE_ONLY
    documented = _documented_names()

    assert documented, "no variables parsed from the docs/configuration.md tables"

    unknown = sorted(name for name in documented if name not in known)
    assert not unknown, f"docs/configuration.md documents names no setting reads: {unknown}"


def test_env_example_loads_because_the_quick_start_copies_it(tmp_path: Path) -> None:
    """README quick start says ``cp .env.example .env``. It must produce a loadable config."""
    env_file = tmp_path / ".env"
    env_file.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    parsed = ServerSettings(_env_file=env_file)

    assert parsed.allowed_hosts == ["localhost", "127.0.0.1", "::1"]
    assert parsed.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert parsed.mcp_profile == "readonly"


def test_allowlists_accept_csv_and_json_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """.env.example writes these as CSV; docker-compose writes them as JSON. Both must work."""
    monkeypatch.setenv(f"{PREFIX}ALLOWED_HOSTS", "localhost,example.org")
    monkeypatch.setenv(f"{PREFIX}CORS_ORIGINS", "https://a.example,https://b.example")
    monkeypatch.setenv(f"{PREFIX}ALLOWED_ORIGINS", '["https://c.example"]')

    parsed = ServerSettings(_env_file=None)

    assert parsed.allowed_hosts == ["localhost", "example.org"]
    assert parsed.cors_origins == ["https://a.example", "https://b.example"]
    assert parsed.allowed_origins == ["https://c.example"]
