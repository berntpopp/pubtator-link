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

## Architecture invariants (do not break)

### Fleet deploy contract

- `docker/docker-compose.npm.yml` is the file the fleet controller
  (`strato_v6_docker_npm`) deploys and validates — as the third file in the
  `docker-compose.yml` + `docker-compose.prod.yml` + `docker-compose.npm.yml`
  stack it renders for this repo. Every service there declares
  `user: "<uid>:<gid>"` numerically: `999:999` for `pubtator-link` (this
  image's own uid:gid from `docker/Dockerfile`) and `999:999` for the
  `pubtator-postgres` sidecar (the `pgvector/pgvector` image's own uid:gid) —
  never copied from a sibling `-link` repo.
- `user` must be numeric non-root wherever it appears in the Compose files
  listed in `container-release.json` (`docker/docker-compose.yml`,
  `docker/docker-compose.prod.yml`). Unlike most sibling repos, this repo's
  `container-release.json` already contracts an explicit `user: "999:999"` for
  the `pubtator-postgres` auxiliary service (see `service.auxiliary`), so those
  files legitimately declare `user` — the shared release gate
  (`container_release.py validate-compose`) does not forbid it outright here,
  it only requires the declared value to be numeric non-root and to match the
  rendered Compose service exactly.
- Both rules are enforced by `tests/unit/test_deploy_overlay_user.py`.
- **The release gate validates the deployed overlay, not just the release compose
  files.** `container-release.json` (`service.deployed_compose_files`) declares the
  exact three-file set the fleet controller renders (base + prod + npm, in that
  order) and `service.deployed_sidecars` declares `pubtator-postgres`'s exact pinned
  `pgvector/pgvector` image, so the shared `_container-release.yml` workflow's
  `validate-deployed-overlay` step (pinned in `.github/workflows/container-release.yml`
  and `.github/workflows/container-ci.yml`) checks the real deployed stack — this repo
  has no read-only seed bind, so `deployed_seed_binds` stays unset. Guarded by
  `test_container_release_manifest_declares_the_deployed_overlay` in
  `tests/unit/test_container_release_contract.py`.
- Self-check the rendered projection the way the controller does (from
  `strato_v6_docker_npm`):

  ```bash
  export PUBTATOR_LINK_IMAGE="ghcr.io/berntpopp/pubtator-link@sha256:<64 hex>"
  export PUBTATOR_LINK_POSTGRES_PASSWORD="<any value>"
  docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml \
    -f docker/docker-compose.npm.yml config --format json > /tmp/pubtator-link-rendered.json
  # from strato_v6_docker_npm:
  uv run python -c "import sys,json; sys.path.insert(0,'scripts'); \
    from utils.deployment_preflight import canonical_projection; \
    canonical_projection(json.load(open('/tmp/pubtator-link-rendered.json')), project='pubtator-link'); \
    print('PROJECTION OK')"
  ```
- **Release checklist** (fleet controller pulls a tagged, attested image — it
  never builds from source): bump `pyproject.toml`, `uv lock`, add a
  `CHANGELOG.md` heading `## [x.y.z] - YYYY-MM-DD`, bump `CITATION.cff`
  `version:` (the file is generated — see its header comment; `date-released`
  is **not** touched by this repo's release process, it is regenerated
  externally by `genefoundry-router`'s `make citation-write`), tag `vx.y.z`,
  then approve the `release` environment gate via
  `gh api repos/berntpopp/pubtator-link/actions/runs/<id>/pending_deployments`
  (may need approving twice; `status: waiting` is the gate, not a slow build).

## Testing Notes

- `make test` is the fast default.
- `make test-cov` runs coverage.
- `make ci-local` runs formatting, linting, type checking, and tests.
- Treat failing checks as real issues unless you have clear evidence otherwise.
