# Modern Python Agentic Development Tooling Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a modern, reproducible Python development workflow for PubTator-Link with `uv`, `Makefile` commands, Ruff, mypy, pre-commit, and shared agent instructions for Codex, Claude Code, and other agentic coding tools.

**Architecture:** Standardize developer entrypoints at the repo root and make `make` the human and agent command surface. Keep shared agent guidance in `AGENTS.md`; keep `CLAUDE.md` as a tiny Claude Code shim that imports the shared guidance. Use `uv.lock` as the dependency source of truth, Ruff for formatting/linting, mypy plus `dmypy` for strict and fast type checking, pytest plus pytest-xdist for fast parallel testing, and pre-commit for local hygiene.

**Tech Stack:** Python 3.11+, uv, Make, Ruff, mypy/dmypy, pytest, pytest-asyncio, pytest-cov, pytest-xdist, pre-commit, Hatchling, Docker Compose, Codex-compatible `AGENTS.md`, Claude Code-compatible `CLAUDE.md`.

---

## File Structure

- Modify `pyproject.toml`: modern Python baseline, dependency groups, Ruff config, mypy config, pytest defaults.
- Create `uv.lock`: locked dependencies.
- Create `.python-version`: local Python version pin.
- Create `.editorconfig`: editor-neutral formatting defaults.
- Create `.pre-commit-config.yaml`: Ruff, mypy, and hygiene hooks.
- Create `Makefile`: canonical development commands.
- Create `AGENTS.md`: shared agent instructions for Codex, Claude Code, and other agents.
- Create `CLAUDE.md`: lean Claude Code entrypoint that references `AGENTS.md`.
- Modify `README.md`: document quick development commands.
- Create `tests/unit/test_development_tooling.py`: guardrails that ensure the tooling files and command names stay present.

---

## Task 1: Modernize Python And uv Metadata

**Files:**
- Modify: `pyproject.toml`
- Create: `.python-version`
- Create: `uv.lock`
- Create: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write failing metadata tests**

Create `tests/unit/test_development_tooling.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/unit/test_development_tooling.py -q
```

Expected: fail because `.python-version`, `uv.lock`, and `[dependency-groups]` do not exist yet.

- [ ] **Step 3: Update `pyproject.toml` Python baseline**

In `pyproject.toml`, replace:

```toml
requires-python = ">=3.9"
```

with:

```toml
requires-python = ">=3.11"
```

Remove Python 3.9 and 3.10 classifiers. Add Python 3.13:

```toml
"Programming Language :: Python :: 3.11",
"Programming Language :: Python :: 3.12",
"Programming Language :: Python :: 3.13",
```

- [ ] **Step 4: Replace optional dev dependencies with uv dependency group**

Keep `[project.optional-dependencies]` only if runtime extras are later needed. Replace the existing `dev = [...]` optional dependency with:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3.0,<9.0.0",
    "pytest-asyncio>=0.25.0,<1.0.0",
    "pytest-cov>=6.0.0,<8.0.0",
    "pytest-mock>=3.14.0,<4.0.0",
    "pytest-xdist>=3.6.0,<4.0.0",
    "httpx>=0.28.0,<1.0.0",
    "ruff>=0.8.0,<1.0.0",
    "mypy>=1.14.0,<2.0.0",
    "pre-commit>=4.0.0,<5.0.0",
]
```

- [ ] **Step 5: Add `.python-version`**

Create `.python-version`:

```text
3.11
```

- [ ] **Step 6: Lock dependencies**

Run:

```bash
uv lock
```

Expected: creates `uv.lock`. If this fails because current MCP/FastMCP ranges conflict with Python metadata, first execute Task 1 of `docs/superpowers/plans/2026-04-29-modern-mcp-docker-npm-hardening.md`, then return here.

- [ ] **Step 7: Verify metadata tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .python-version uv.lock tests/unit/test_development_tooling.py
git commit -m "chore: add uv python development baseline"
```

---

## Task 2: Tighten Ruff, mypy, And pytest Configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Add config guardrail tests**

Append to `tests/unit/test_development_tooling.py`:

```python
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
```

- [ ] **Step 2: Run failing config tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected: fail because Ruff targets `py39`, mypy targets `3.10`, and pytest always runs coverage.

- [ ] **Step 3: Update Ruff config**

In `pyproject.toml`, set:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
extend-select = [
    "E",
    "W",
    "F",
    "I",
    "N",
    "UP",
    "B",
    "C4",
    "S",
    "T20",
    "SIM",
    "RUF",
]
ignore = [
    "S101",
    "E501",
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"
```

- [ ] **Step 4: Update mypy config**

In `pyproject.toml`, set:

```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
warn_unreachable = true
exclude = [
    ".*site-packages.*",
    ".*/miniforge3/.*",
    ".*/venv/.*",
    ".*/.venv/.*",
    "htmlcov/.*",
]
```

- [ ] **Step 5: Make default pytest fast**

In `[tool.pytest.ini_options]`, replace `addopts` with:

```toml
addopts = [
    "--strict-markers",
    "-ra",
]
```

Keep coverage available through Makefile targets in Task 3.

- [ ] **Step 6: Verify config tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tests/unit/test_development_tooling.py
git commit -m "chore: tune ruff mypy and pytest defaults"
```

---

## Task 3: Add Makefile Command Surface

**Files:**
- Create: `Makefile`
- Modify: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Add Makefile tests**

Append to `tests/unit/test_development_tooling.py`:

```python
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
```

- [ ] **Step 2: Run failing Makefile tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_makefile_exposes_expected_developer_commands -q
```

Expected: fail because `Makefile` does not exist.

- [ ] **Step 3: Create `Makefile`**

Create `Makefile`:

```makefile
.PHONY: help install lock upgrade sync format format-check lint lint-ci lint-fix typecheck typecheck-fast typecheck-stop typecheck-fresh test test-fast test-unit test-integration test-cov test-all check ci-local precommit clean dev mcp-serve mcp-serve-http docker-build docker-up docker-down docker-logs docker-prod-config docker-npm-config

DOCKER_COMPOSE := $(shell if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then echo "docker compose"; elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)

.DEFAULT_GOAL := help

help: ## Display this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install project and development dependencies with uv
	uv sync --group dev

sync: install ## Alias for install

lock: ## Resolve and update uv.lock
	uv lock

upgrade: ## Upgrade locked dependencies
	uv lock --upgrade

format: ## Format Python code
	uv run ruff format pubtator_link tests server.py mcp_server.py

format-check: ## Check formatting without writing
	uv run ruff format --check pubtator_link tests server.py mcp_server.py

lint: ## Lint Python code
	uv run ruff check pubtator_link tests server.py mcp_server.py

lint-ci: ## Lint Python code without modifying files
	uv run ruff check pubtator_link tests server.py mcp_server.py --output-format=github

lint-fix: ## Lint and apply safe fixes
	uv run ruff check pubtator_link tests server.py mcp_server.py --fix

typecheck: ## Type check package
	uv run mypy pubtator_link server.py mcp_server.py

typecheck-fast: ## Type check with mypy daemon and fallback
	@tmp_log=$$(mktemp); \
	if uv run dmypy run -- pubtator_link server.py mcp_server.py >$$tmp_log 2>&1; then \
		cat $$tmp_log; \
	elif grep -Eq "Daemon crashed!|INTERNAL ERROR" $$tmp_log; then \
		echo "dmypy crashed; retrying with a fresh daemon..."; \
		uv run dmypy stop >/dev/null 2>&1 || true; \
		if uv run dmypy run -- pubtator_link server.py mcp_server.py >$$tmp_log 2>&1; then \
			cat $$tmp_log; \
		else \
			cat $$tmp_log; \
			echo "Falling back to plain mypy..."; \
			uv run dmypy stop >/dev/null 2>&1 || true; \
			uv run mypy pubtator_link server.py mcp_server.py; \
		fi; \
	else \
		cat $$tmp_log; \
		rm -f $$tmp_log; \
		exit 1; \
	fi; \
	rm -f $$tmp_log

typecheck-stop: ## Stop mypy daemon
	uv run dmypy stop

typecheck-fresh: ## Clear mypy cache and run typecheck
	rm -rf .mypy_cache
	uv run mypy pubtator_link server.py mcp_server.py

test: ## Run tests quickly
	uv run pytest tests -q

test-fast: ## Run tests in parallel with pytest-xdist
	uv run pytest tests -q -n auto

test-unit: ## Run unit tests in parallel
	uv run pytest tests -q -n auto -m "not integration and not slow"

test-integration: ## Run integration tests serially
	uv run pytest tests -q -m "integration"

test-cov: ## Run tests with coverage
	uv run pytest tests --cov=pubtator_link --cov-report=term-missing --cov-report=html

test-all: test-cov ## Alias for full test run with coverage

check: format lint ## Format and lint

ci-local: format-check lint-ci typecheck-fast test-fast ## Run fast local CI-equivalent checks

precommit: ci-local ## Run checks expected before commit

clean: ## Remove local caches and generated reports
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage

dev: ## Start REST plus MCP development server
	uv run python server.py --transport unified --host 127.0.0.1 --port 8000

mcp-serve: ## Start local stdio MCP server
	uv run python mcp_server.py

mcp-serve-http: ## Start hosted MCP endpoint with REST API
	uv run python server.py --transport unified --host 127.0.0.1 --port 8000

docker-build: ## Build Docker image
	$(DOCKER_COMPOSE) -f docker/docker-compose.yml build

docker-up: ## Start Docker development stack
	$(DOCKER_COMPOSE) -f docker/docker-compose.yml up -d

docker-down: ## Stop Docker development stack
	$(DOCKER_COMPOSE) -f docker/docker-compose.yml down

docker-logs: ## Follow Docker logs
	$(DOCKER_COMPOSE) -f docker/docker-compose.yml logs -f

docker-prod-config: ## Render production Compose configuration
	$(DOCKER_COMPOSE) -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config

docker-npm-config: ## Render NPM Compose configuration
	$(DOCKER_COMPOSE) --env-file docker/.env.npm.example -f docker/docker-compose.yml -f docker/docker-compose.prod.yml -f docker/docker-compose.npm.yml config
```

- [ ] **Step 4: Verify Makefile tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_makefile_exposes_expected_developer_commands -q
```

Expected: pass.

- [ ] **Step 5: Smoke test help target**

Run:

```bash
make help
```

Expected: lists targets without errors.

- [ ] **Step 6: Commit**

```bash
git add Makefile tests/unit/test_development_tooling.py
git commit -m "chore: add make development command surface"
```

---

## Task 4: Add pre-commit And Editor Defaults

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `.editorconfig`
- Modify: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Add config presence tests**

Append to `tests/unit/test_development_tooling.py`:

```python
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
```

- [ ] **Step 2: Run failing config tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_pre_commit_config_uses_ruff_and_mypy tests/unit/test_development_tooling.py::test_editorconfig_sets_project_defaults -q
```

Expected: fail because config files do not exist.

- [ ] **Step 3: Create `.editorconfig`**

Create `.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yml,yaml,toml,json,md}]
indent_size = 2

[Makefile]
indent_style = tab
```

- [ ] **Step 4: Create `.pre-commit-config.yaml`**

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-json
      - id: check-added-large-files
      - id: check-merge-conflict
      - id: debug-statements

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.6
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy pubtator_link server.py mcp_server.py
        language: system
        pass_filenames: false
```

- [ ] **Step 5: Verify config tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_pre_commit_config_uses_ruff_and_mypy tests/unit/test_development_tooling.py::test_editorconfig_sets_project_defaults -q
```

Expected: pass.

- [ ] **Step 6: Run pre-commit on changed files**

Run:

```bash
uv run pre-commit run --files .pre-commit-config.yaml .editorconfig pyproject.toml Makefile
```

Expected: pass or auto-fix formatting; if auto-fixed, rerun until pass.

- [ ] **Step 7: Commit**

```bash
git add .pre-commit-config.yaml .editorconfig tests/unit/test_development_tooling.py
git commit -m "chore: add pre-commit and editor defaults"
```

---

## Task 5: Add Agentic Tool Instructions

**Files:**
- Create: `AGENTS.md`
- Create: `CLAUDE.md`
- Modify: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Add agent instruction tests**

Append to `tests/unit/test_development_tooling.py`:

```python
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
```

- [ ] **Step 2: Run failing agent instruction tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_agents_md_contains_shared_agent_guidance tests/unit/test_development_tooling.py::test_claude_md_is_lean_and_references_agents -q
```

Expected: fail because `AGENTS.md` and `CLAUDE.md` do not exist.

- [ ] **Step 3: Create `AGENTS.md`**

Create `AGENTS.md`:

```markdown
# AGENTS.md

Shared repository instructions for agentic coding tools working in PubTator-Link.

## Project

PubTator-Link is a Python FastAPI and MCP server for the PubTator3 biomedical
literature API.

Primary areas:

- `pubtator_link/` - Python package, FastAPI routes, services, client, MCP code
- `tests/` - unit and integration tests
- `docker/` - Dockerfile and Compose deployment files
- `docs/superpowers/plans/` - implementation plans for agentic workers

## Source Of Truth

- Use this file for shared repo-wide agent guidance.
- Keep `CLAUDE.md` lean and Claude-specific; it should reference this file.
- Prefer `Makefile` targets over ad hoc commands.
- Use `uv.lock` as the dependency lock source of truth.

## Working Rules

- Do not revert or overwrite changes you did not make unless explicitly asked.
- Keep edits scoped to the task and avoid unrelated refactors.
- Prefer existing code patterns over new abstractions.
- Put tests under `tests/`; do not create alternate test roots.
- Use ASCII unless a file already requires non-ASCII content.
- For MCP work, keep public hosted tools research-use scoped and avoid exposing destructive cache operations.

## Commands

Required checks before claiming completion:

- `make ci-local`

Useful focused commands:

- `make install`
- `make lock`
- `make format`
- `make lint`
- `make lint-fix`
- `make typecheck`
- `make typecheck-fast`
- `make test`
- `make test-fast`
- `make test-unit`
- `make test-integration`
- `make test-cov`
- `make precommit`
- `make dev`
- `make mcp-serve-http`
- `make docker-build`
- `make docker-up`
- `make docker-down`

## Coding Standards

- Use `uv` for dependency management; do not use direct `pip` installs.
- Use modern Python typing: `list[str]`, `dict[str, int]`, `str | None`.
- Format and lint Python with Ruff.
- Type check with mypy targeting Python 3.11.
- Keep FastAPI route behavior covered by route tests and service behavior covered by unit tests.

## Testing Notes

- `make test` is the fast default.
- `make test-cov` runs coverage.
- `make ci-local` runs formatting, linting, type checking, and tests.
- Treat failing checks as real issues unless you have clear evidence otherwise.
```

- [ ] **Step 4: Create lean `CLAUDE.md`**

Create `CLAUDE.md`:

```markdown
# CLAUDE.md

@AGENTS.md

Claude Code entrypoint only:

- Use `AGENTS.md` for shared repository instructions.
- Keep Claude-specific additions here short and tool-specific.
- Prefer `make ci-local` before final handoff.
```

- [ ] **Step 5: Verify agent instruction tests**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_agents_md_contains_shared_agent_guidance tests/unit/test_development_tooling.py::test_claude_md_is_lean_and_references_agents -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md CLAUDE.md tests/unit/test_development_tooling.py
git commit -m "docs: add shared agent development instructions"
```

---

## Task 6: Update README Development Quickstart

**Files:**
- Modify: `README.md`
- Modify: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Add README guardrail test**

Append to `tests/unit/test_development_tooling.py`:

```python
def test_readme_documents_modern_development_commands() -> None:
    readme = Path("README.md").read_text()

    assert "make install" in readme
    assert "make ci-local" in readme
    assert "uv lock" in readme
    assert "AGENTS.md" in readme
```

- [ ] **Step 2: Run failing README test**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_readme_documents_modern_development_commands -q
```

Expected: fail until README is updated.

- [ ] **Step 3: Add development section to README**

In `README.md`, add a section near the installation or development area:

```markdown
## Modern Development Workflow

This project uses `uv` and `make` as the primary local development interface.

```bash
make install       # install project and dev dependencies
make lock          # update uv.lock
make format        # format with Ruff
make lint          # lint with Ruff
make typecheck     # run mypy
make test          # run tests
make test-fast     # run tests in parallel
make ci-local      # run local CI checks
```

Dependencies are locked in `uv.lock`; update them with `uv lock` or
`make lock`. Agentic coding tools should follow `AGENTS.md`; Claude Code also
loads the lean `CLAUDE.md` entrypoint.
```

- [ ] **Step 4: Verify README test**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py::test_readme_documents_modern_development_commands -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/unit/test_development_tooling.py
git commit -m "docs: document modern development workflow"
```

---

## Task 7: Final Verification

**Files:**
- Create: `.planning/analysis/2026-04-29-modern-python-agentic-development-verification.md`

- [ ] **Step 1: Run development tooling guardrails**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected: pass.

- [ ] **Step 2: Run core Makefile checks**

Run:

```bash
make help
make format-check
make lint
make typecheck
make test
make test-fast
```

Expected: pass.

- [ ] **Step 3: Run local CI shortcut**

Run:

```bash
make ci-local
```

Expected: pass.

- [ ] **Step 4: Run pre-commit**

Run:

```bash
uv run pre-commit run --all-files
```

Expected: pass.

- [ ] **Step 5: Record verification notes**

Create `.planning/analysis/2026-04-29-modern-python-agentic-development-verification.md`:

```markdown
# Modern Python Agentic Development Verification

Date: 2026-04-29

## Commands

- `uv run pytest tests/unit/test_development_tooling.py -q`
- `make help`
- `make format-check`
- `make lint`
- `make typecheck`
- `make test`
- `make test-fast`
- `make ci-local`
- `uv run pre-commit run --all-files`

## Outcomes

Record exact pass/fail outcomes and any fixes applied before final handoff.
```

- [ ] **Step 6: Commit verification notes**

```bash
git add .planning/analysis/2026-04-29-modern-python-agentic-development-verification.md
git commit -m "test: record development tooling verification"
```

---

## Acceptance Criteria

- `uv lock` succeeds and `uv.lock` is committed.
- Python baseline is 3.11+ across `pyproject.toml`, `.python-version`, Ruff, and mypy.
- `Makefile` exposes the standard workflow: install, lock, format, lint, fast lint, typecheck, fast typecheck, test, parallel test, unit test, integration test, coverage, CI-local, precommit, dev server, MCP server, and Docker commands.
- Ruff formats and lints project code.
- mypy type checks the package with strict settings.
- pytest default run is fast and does not always force coverage. Parallel test execution is available through `make test-fast` and `pytest-xdist`.
- pre-commit runs Ruff, Ruff format, mypy, and basic file hygiene hooks.
- `AGENTS.md` provides shared agent instructions for Codex, Claude Code, and other coding agents.
- `CLAUDE.md` is a lean Claude Code shim that references `AGENTS.md`.
- README documents the modern development workflow.
- `make ci-local` passes before handoff.

## Self-Review

- Spec coverage: uv, Makefile, Ruff, mypy, pre-commit, README, AGENTS.md, and CLAUDE.md are each covered by a task.
- Placeholder scan: the plan contains no `TBD`, no empty test requests, and no unspecified command targets.
- Type consistency: all package paths use `pubtator_link`; all command references use Makefile target names introduced in Task 3; Python version is consistently 3.11.
