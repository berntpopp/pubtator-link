"""Guardrails for repository development tooling."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _pyproject() -> dict[str, object]:
    return tomllib.loads(Path("pyproject.toml").read_text())


def test_python_baseline_is_modern_and_consistent() -> None:
    project = _pyproject()["project"]

    assert project["requires-python"] == ">=3.11"
    assert Path(".python-version").read_text().strip() == "3.11"


def test_dependency_groups_include_dev_tooling() -> None:
    data = _pyproject()
    groups = data["dependency-groups"]
    dev = "\n".join(groups["dev"])

    assert "ruff" in dev
    assert "mypy" in dev
    assert "pytest" in dev
    assert "pytest-xdist" in dev
    assert "pre-commit" in dev


def test_uv_lock_exists() -> None:
    assert Path("uv.lock").exists()


def test_ruff_targets_python_311_and_core_paths() -> None:
    data = _pyproject()
    ruff = data["tool"]["ruff"]

    assert ruff["target-version"] == "py311"
    assert ruff["line-length"] == 100


def test_mypy_targets_python_311() -> None:
    mypy = _pyproject()["tool"]["mypy"]

    assert mypy["python_version"] == "3.11"
    assert mypy["strict"] is True


def test_pytest_has_fast_default_addopts() -> None:
    pytest_config = _pyproject()["tool"]["pytest"]["ini_options"]
    addopts = " ".join(pytest_config["addopts"])

    assert "--strict-markers" in addopts
    assert "--cov=pubtator_link" not in addopts
    assert "-n" not in addopts


def test_makefile_exposes_expected_developer_commands() -> None:
    makefile = Path("Makefile").read_text()

    for target in (
        "help:",
        "install:",
        "lock:",
        "format:",
        "format-check:",
        "lint:",
        "lint-ci:",
        "lint-fix:",
        "typecheck:",
        "typecheck-fast:",
        "test:",
        "test-fast:",
        "test-unit:",
        "test-integration:",
        "test-cov:",
        "check:",
        "ci-local:",
        "precommit:",
        "dev:",
        "mcp-serve:",
        "mcp-serve-http:",
        "docker-build:",
        "docker-up:",
        "docker-down:",
    ):
        assert target in makefile


def test_pre_commit_config_uses_ruff_and_mypy() -> None:
    config = Path(".pre-commit-config.yaml").read_text()

    assert "astral-sh/ruff-pre-commit" in config
    assert "id: ruff" in config
    assert "id: ruff-format" in config
    assert "uv run mypy" in config


def test_editorconfig_sets_project_defaults() -> None:
    config = Path(".editorconfig").read_text()

    assert "charset = utf-8" in config
    assert "indent_style = space" in config
    assert "indent_size = 4" in config
    assert "end_of_line = lf" in config


def test_agents_md_contains_shared_agent_guidance() -> None:
    agents = Path("AGENTS.md").read_text()

    assert "Shared repository instructions" in agents
    assert "Do not revert or overwrite changes you did not make" in agents
    assert "make ci-local" in agents
    assert "uv" in agents
    assert "CLAUDE.md" in agents


def test_claude_md_is_lean_and_references_agents() -> None:
    claude = Path("CLAUDE.md").read_text()

    assert "@AGENTS.md" in claude
    assert len(claude.splitlines()) <= 20


def test_readme_documents_modern_development_commands() -> None:
    readme = Path("README.md").read_text()

    assert "make install" in readme
    assert "make ci-local" in readme
    assert "uv lock" in readme
    assert "AGENTS.md" in readme
