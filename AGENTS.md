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
