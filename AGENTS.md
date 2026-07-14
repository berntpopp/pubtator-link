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
- `.claude/skills/` - repo-local Claude Code workflows for recurring tasks

## Source Of Truth

- Use this file for shared repo-wide agent guidance.
- Keep `CLAUDE.md` lean and Claude-specific; it should reference this file.
- Use repo-local `.claude/skills/` workflows when a task matches their scope.
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
- `make lint-loc`
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
- Dependencies are locked in `uv.lock`; update them with `uv lock` (or `make lock`).
  Never hand-edit the lock file.
- Install the locked development environment with `make install` (`uv sync --group dev`).
- Use modern Python typing: `list[str]`, `dict[str, int]`, `str | None`.
- Format and lint Python with Ruff.
- Type check with mypy targeting Python 3.11.
- Keep FastAPI route behavior covered by route tests and service behavior covered by unit tests.

## Documentation Layout

The README is the front door, not the manual: it follows the GeneFoundry README Standard v1
(hard ceiling 200 lines, fixed section order, four badges, no hand-typed counts), enforced by
`make lint-readme`. Reference material lives in `docs/` and MUST NOT be moved back into it:

- `docs/configuration.md` — environment variables, tool profiles, caching, CLI.
- `docs/rest-api.md` — the FastAPI REST surface.
- `docs/architecture.md` — package layout, transports, review re-RAG subsystem.
- `docs/deployment.md` — Docker, the pgvector sidecar, health, observability.
- `docs/SECURITY.md` — trust boundary, service token, write-surface hardening.
- `docs/MCP_CONNECTION_GUIDE.md` — MCP clients, review workflow, response modes.

The README's `## Tools` table is machine-verified against the registered `readonly` tool
surface by `tests/unit/test_readme_tools.py`. Adding or renaming a tool means updating that
table in the same commit, or CI fails.

## File Size Discipline

Hard cap: **600 lines per Python module** in `pubtator_link/`, `server.py`, and `mcp_server.py`. Enforced by `make lint-loc` (wired into `ci-local` and pre-commit). Tests are exempt.

Why: large modules concentrate complexity, slow mypy and import cost, and degrade LLM-assisted refactors (a single edit risks unrelated breakage). When a file approaches 500 lines, plan its split.

How:

- New files MUST stay under 600 lines.
- Existing oversized files are grandfathered in `.loc-allowlist` with their current line count as the ceiling. They may shrink but not grow. Removing an entry after a successful split is the goal.
- Prefer cohesive splits: one module per responsibility (e.g., `repositories/review/{jobs,passages,sources}.py`), not random partitioning to slip under the cap.
- Keep the public Protocol or facade stable across splits so call sites don't churn.
- If you must add to an allowlisted file as part of an unrelated fix, raise the ceiling explicitly in `.loc-allowlist` in the same commit and link the decomposition plan in the message.

The active decomposition backlog lives in `.planning/reviews/` (latest senior audit, Phase 5).

## Testing Notes

- `make test` is the fast default.
- `make test-cov` runs coverage.
- `make ci-local` runs formatting, linting, type checking, and tests.
- Treat failing checks as real issues unless you have clear evidence otherwise.
