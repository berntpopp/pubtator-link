"""Guardrails for repository development tooling."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml


def _pyproject() -> dict[str, object]:
    return tomllib.loads(Path("pyproject.toml").read_text())


def _workflow(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text())


def _branch_protection_policy() -> dict[str, Any]:
    return json.loads(Path("docs/development/branch-protection.json").read_text())


def _workflow_action_refs(workflow: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for job in workflow["jobs"].values():
        if "uses" in job:
            refs.append(job["uses"])
        refs.extend(step["uses"] for step in job.get("steps", []) if "uses" in step)
    return refs


def test_python_baseline_is_modern_and_consistent() -> None:
    project = _pyproject()["project"]

    assert project["requires-python"] == ">=3.12"
    assert Path(".python-version").read_text().strip() == "3.12"


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


def test_ruff_targets_python_312_and_core_paths() -> None:
    data = _pyproject()
    ruff = data["tool"]["ruff"]

    assert ruff["target-version"] == "py312"
    assert ruff["line-length"] == 100


def test_mypy_targets_python_312() -> None:
    mypy = _pyproject()["tool"]["mypy"]

    assert mypy["python_version"] == "3.12"
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
    # The serve loop (and its signal handler) lives in the typer CLI now that
    # the root server.py / mcp_server.py entrypoints are gone.
    cli = Path("pubtator_link/cli.py").read_text()

    assert "shutdown_task: asyncio.Task[None] | None = None" in cli
    assert "shutdown_task = asyncio.create_task(manager.shutdown())" in cli


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
        "serve:",
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


def test_gitignore_allows_tracked_benchmark_inputs() -> None:
    text = Path(".gitignore").read_text()

    assert "benchmarks/results/" in text
    assert "benchmarks/logs/" in text
    assert "!benchmarks/cases/**" in text
    assert "!benchmarks/prompts/**" in text
    assert "!benchmarks/suites/**" in text


def test_claude_md_is_lean_and_references_agents() -> None:
    claude = Path("CLAUDE.md").read_text()

    assert "@AGENTS.md" in claude
    assert len(claude.splitlines()) <= 20


def test_development_commands_documented_in_agents_and_linked_from_readme() -> None:
    """The locked uv/make workflow must stay written down.

    README Standard v1 exiles the make-target tour from the README to AGENTS.md, so
    this asserts the contract at its new home *and* that the README still routes a
    contributor there — strictly more than the old README-only substring check.
    """
    agents = Path("AGENTS.md").read_text()
    readme = Path("README.md").read_text()

    for command in ("make install", "uv lock", "make ci-local"):
        assert command in agents, f"AGENTS.md must document `{command}`"

    assert "](AGENTS.md)" in readme, "README must link AGENTS.md as the contributor guide"
    assert "make ci-local" in readme, "README must name the definition-of-done gate"


def test_coverage_threshold_matches_verified_baseline() -> None:
    coverage = _pyproject()["tool"]["coverage"]["report"]
    assert coverage["fail_under"] == 80


def test_github_actions_workflows_exist_and_use_make_targets() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    container_ci = _workflow(".github/workflows/container-ci.yml")
    container_release = _workflow(".github/workflows/container-release.yml")
    security = _workflow(".github/workflows/security.yml")

    assert ci["permissions"] == {"contents": "read"}
    quality_job = ci["jobs"]["quality"]
    assert quality_job["name"] == "Format, lint, typecheck, tests, and coverage"
    ci_commands = {step.get("run") for step in quality_job["steps"]}
    assert "uv sync --group dev --frozen" in ci_commands
    assert "make ci-local" in ci_commands
    assert "make test-cov" in ci_commands

    assert container_ci["permissions"] == {}
    container_ci_job = container_ci["jobs"]["container-ci"]
    assert container_ci_job["permissions"] == {"contents": "read"}
    assert container_ci_job["uses"].startswith(
        "berntpopp/genefoundry-router/.github/workflows/_container-ci.yml@"
    )

    assert container_release["permissions"] == {}
    container_release_job = container_release["jobs"]["container-release"]
    assert container_release_job["permissions"] == {
        "attestations": "write",
        "contents": "write",
        "id-token": "write",
        "packages": "write",
    }
    assert container_release_job["uses"].startswith(
        "berntpopp/genefoundry-router/.github/workflows/_container-release.yml@"
    )

    assert security["permissions"] == {"contents": "read"}
    codeql_job = security["jobs"]["codeql"]
    dependency_review_job = security["jobs"]["dependency-review"]
    assert codeql_job["name"] == "CodeQL"
    assert codeql_job["if"] == "${{ !github.event.repository.private }}"
    assert codeql_job["permissions"] == {
        "actions": "read",
        "contents": "read",
        "security-events": "write",
    }
    assert dependency_review_job["name"] == "Dependency review"
    assert dependency_review_job["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    security_actions = {
        step["uses"] for job in security["jobs"].values() for step in job["steps"] if "uses" in step
    }
    assert any(action.startswith("github/codeql-action/init@") for action in security_actions)
    assert not any(
        action.startswith("github/codeql-action/autobuild@") for action in security_actions
    )
    assert any(
        action.startswith("actions/dependency-review-action@") for action in security_actions
    )


def test_release_service_token_is_scoped_to_compose_validation() -> None:
    release = _workflow(".github/workflows/release.yml")
    assert "PUBTATOR_LINK_MCP_SERVICE_TOKEN" not in (release.get("env") or {})
    allowed_steps = {"Validate production Compose config", "Validate NPM Compose config"}
    token_steps: set[str] = set()
    for job in release["jobs"].values():
        assert "PUBTATOR_LINK_MCP_SERVICE_TOKEN" not in (job.get("env") or {})
        for step in job["steps"]:
            step_env = step.get("env") or {}
            if "PUBTATOR_LINK_MCP_SERVICE_TOKEN" in step_env:
                token_steps.add(step.get("name", ""))
                assert step.get("name") in allowed_steps
                assert step_env["PUBTATOR_LINK_MCP_SERVICE_TOKEN"]

    assert token_steps == allowed_steps


def test_github_actions_are_sha_pinned_with_uv_version() -> None:
    workflows = [
        _workflow(".github/workflows/ci.yml"),
        _workflow(".github/workflows/container-ci.yml"),
        _workflow(".github/workflows/container-release.yml"),
        _workflow(".github/workflows/release.yml"),
        _workflow(".github/workflows/security.yml"),
    ]
    action_ref_pattern = re.compile(r"^[^@]+@[0-9a-f]{40}$")
    action_refs = [ref for workflow in workflows for ref in _workflow_action_refs(workflow)]

    assert action_refs
    assert all(action_ref_pattern.match(ref) for ref in action_refs)

    setup_uv_steps = [
        step
        for workflow in workflows
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert setup_uv_steps
    assert all(step.get("with", {}).get("version") for step in setup_uv_steps)


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
    assert "Container CI calls" in docs
    assert "CI / Format, lint, typecheck, tests, and coverage" in docs
    assert "Container CI / container-ci" in docs
    assert "Security / CodeQL" in docs
    assert "Security / Dependency review" in docs


def test_active_docs_do_not_advertise_v2_or_prepare_mode_examples() -> None:
    active_paths = [
        Path("docs/MCP_CONNECTION_GUIDE.md"),
        Path("pubtator_link/mcp/resources.py"),
    ]
    joined = "\n".join(path.read_text() for path in active_paths)

    assert "search_literature_v2" not in joined
    assert '"prepare_mode": "selected"' not in joined


def test_branch_protection_policy_file_exists_and_parses() -> None:
    policy_path = Path("docs/development/branch-protection.json")

    assert policy_path.exists()
    policy = json.loads(policy_path.read_text())

    assert policy["branch"] == "main"
    assert policy["required_review_count"] == 1
    assert policy["dismiss_stale_reviews"] is True
    assert policy["require_up_to_date_branch"] is True
    assert policy["postgres_integration_required"] is False


def test_branch_protection_required_checks_match_workflow_job_names() -> None:
    policy = _branch_protection_policy()
    workflows = {
        "CI": _workflow(".github/workflows/ci.yml"),
        "Container CI": _workflow(".github/workflows/container-ci.yml"),
        "Security": _workflow(".github/workflows/security.yml"),
    }
    workflow_checks = {
        f"{workflow_name} / {job.get('name', job_name)}"
        for workflow_name, workflow in workflows.items()
        for job_name, job in workflow["jobs"].items()
    }

    assert set(policy["required_status_checks"]) == {
        "CI / Format, lint, typecheck, tests, and coverage",
        "Container CI / container-ci",
        "Security / CodeQL",
        "Security / Dependency review",
    }
    assert set(policy["required_status_checks"]).issubset(workflow_checks)


def test_container_security_workflow_generates_scan_and_sbom_artifacts() -> None:
    workflow = _workflow(".github/workflows/container-ci.yml")
    job = workflow["jobs"]["container-ci"]

    assert workflow["permissions"] == {}
    assert job["permissions"] == {"contents": "read"}
    assert job["uses"].startswith(
        "berntpopp/genefoundry-router/.github/workflows/_container-ci.yml@"
    )


def test_release_workflow_validates_tagged_builds_without_publishing() -> None:
    workflow = _workflow(".github/workflows/release.yml")
    release_job = workflow["jobs"]["release-validation"]
    commands = {step.get("run") for step in release_job["steps"]}

    assert workflow["permissions"] == {"contents": "read"}
    assert release_job["name"] == "Release validation"
    assert "make ci-local" in commands
    assert "make docker-prod-config" in commands
    assert "make docker-npm-config" in commands
    assert "docker build -f docker/Dockerfile -t pubtator-link:release ." in commands


def test_operations_runbook_documents_deploy_health_and_rollback() -> None:
    runbook = Path("docs/development/operations-runbook.md").read_text()

    assert "make docker-up" in runbook
    assert "/health" in runbook
    assert "/ready" in runbook
    assert "docker compose" in runbook
    assert "rollback" in runbook.lower()
    assert "X-Request-ID" in runbook


def test_readme_quickstart_uses_uv_and_make_not_pip_install() -> None:
    readme = Path("README.md").read_text()

    assert "make install" in readme
    assert "make dev" in readme
    assert 'pip install -e ".[dev]"' not in readme
    assert "FROM python:3.11-slim" not in readme

    # The Python floor used to be a hand-typed status footer ("**Python**: 3.12+"),
    # exactly the kind of derived fact README Standard v1 deletes because it rots.
    # It is now carried by a badge that links out, and enforced by the only source
    # of truth that can actually reject a wrong interpreter.
    assert "img.shields.io/badge/python-3.12" in readme
    assert _pyproject()["project"]["requires-python"] == ">=3.12"  # type: ignore[index]


def test_repo_local_claude_workflows_exist_for_agentic_development() -> None:
    workflow_paths = [
        Path(".claude/skills/mcp-tool-change/SKILL.md"),
        Path(".claude/skills/fastapi-route-change/SKILL.md"),
        Path(".claude/skills/database-migration/SKILL.md"),
        Path(".claude/skills/ci-failure-triage/SKILL.md"),
        Path(".claude/skills/release-readiness/SKILL.md"),
    ]

    for path in workflow_paths:
        assert path.exists()
        content = path.read_text()
        assert "make ci-local" in content
        assert "AGENTS.md" in content
