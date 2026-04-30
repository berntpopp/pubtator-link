"""Guardrails for repository development tooling."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml


def _pyproject() -> dict[str, object]:
    return tomllib.loads(Path("pyproject.toml").read_text())


def _workflow(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text())


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
    assert "respx" in dev


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


def test_ruff_enforces_modern_rules_with_narrow_fixture_exception() -> None:
    ruff = _pyproject()["tool"]["ruff"]["lint"]
    per_file_ignores = _pyproject()["tool"]["ruff"]["lint"]["per-file-ignores"]

    assert "SIM" in ruff["extend-select"]
    assert "RUF" in ruff["extend-select"]
    assert per_file_ignores["tests/fixtures/test_data.py"] == ["RUF012"]


def test_server_signal_handler_keeps_shutdown_task_reference() -> None:
    server = Path("server.py").read_text()

    assert "shutdown_task: asyncio.Task[None] | None = None" in server
    assert "shutdown_task = asyncio.create_task(server_manager.shutdown())" in server


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


def test_coverage_threshold_matches_verified_baseline() -> None:
    coverage = _pyproject()["tool"]["coverage"]["report"]
    assert coverage["fail_under"] == 78


def test_github_actions_workflows_exist_and_use_make_targets() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    docker = _workflow(".github/workflows/docker.yml")
    security = _workflow(".github/workflows/security.yml")

    assert ci["permissions"] == {"contents": "read"}
    quality_job = ci["jobs"]["quality"]
    assert quality_job["name"] == "Format, lint, typecheck, tests, and coverage"
    ci_commands = {step.get("run") for step in quality_job["steps"]}
    assert "uv sync --group dev --frozen" in ci_commands
    assert "make ci-local" in ci_commands
    assert "make test-cov" in ci_commands

    assert docker["permissions"] == {"contents": "read"}
    docker_job = docker["jobs"]["docker"]
    assert docker_job["name"] == "Docker build and Compose validation"
    docker_commands = {step.get("run") for step in docker_job["steps"]}
    assert "make docker-prod-config" in docker_commands
    assert "make docker-npm-config" in docker_commands
    assert "docker build -f docker/Dockerfile -t pubtator-link:ci ." in docker_commands

    assert security["permissions"] == {"contents": "read"}
    codeql_job = security["jobs"]["codeql"]
    dependency_review_job = security["jobs"]["dependency-review"]
    assert codeql_job["name"] == "CodeQL"
    assert codeql_job["permissions"] == {"contents": "read", "security-events": "write"}
    assert dependency_review_job["name"] == "Dependency review"
    assert dependency_review_job["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    security_actions = {
        step.get("uses")
        for job in security["jobs"].values()
        for step in job["steps"]
    }
    assert "github/codeql-action/init@v3" in security_actions
    assert "actions/dependency-review-action@v4" in security_actions


def test_pull_request_template_contains_quality_checklist() -> None:
    template = Path(".github/pull_request_template.md").read_text()

    assert "make ci-local" in template
    assert "Public REST/MCP behavior" in template
    assert "New dependencies" in template
    assert "research-use" in template


def test_branch_protection_docs_define_required_checks() -> None:
    docs = Path("docs/development/branch-protection.md").read_text()

    assert "Require pull request before merging" in docs
    assert "make ci-local" in docs
    assert "coverage" in docs
    assert "Docker validation" in docs
    assert "CI / Format, lint, typecheck, tests, and coverage" in docs
    assert "Docker / Docker build and Compose validation" in docs
    assert "Security / CodeQL" in docs
    assert "Security / Dependency review" in docs
