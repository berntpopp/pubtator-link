# PubTator-Link Maintainability, CI/CD, And LLM Development Review

Date: 2026-04-30

Re-review update: 2026-04-30

## Executive Summary

PubTator-Link has a solid local engineering foundation: modern Python packaging with `uv`, a clear `Makefile` command surface, Ruff formatting and linting, strict mypy, pytest coverage support, Docker hardening, and shared agent instructions in `AGENTS.md`.

The project is not yet production-grade from a CI/CD and long-term maintainability perspective. The main gaps are:

- No `.github/workflows` CI/CD configuration exists in this checkout.
- The local test gate is now green: `make ci-local` passed, and `make test-cov` produced 321 passed, 2 skipped, with 78% total coverage.
- Several high-change modules are large enough to become difficult for LLM coding agents and human reviewers to modify safely.
- Runtime dependency lifecycle management still relies on module-level global singletons. The stale event-loop symptom is now handled, but the underlying ownership boundary remains a maintainability risk.

The fastest path forward is to add GitHub Actions as a remote quality gate, ratchet coverage, replace lifecycle globals with app-scoped resources, and split the largest MCP/re-RAG modules behind smaller contracts.

## Review Strategy

This review used current external engineering guidance as the yardstick:

- Google Engineering Practices: code review should improve code health over time, prioritize technical facts over preference, keep changes small, and include relevant tests.
- Martin Fowler's Continuous Integration guidance: automate the build, make it self-testing, trigger builds on mainline changes, fix broken builds quickly, and keep feedback fast.
- Martin Fowler's Test Pyramid: prefer many focused low-level tests, fewer broad integration tests, and use higher-level failures to identify missing lower-level coverage.
- GitHub Actions security guidance: apply least-privilege permissions, protect secrets, avoid unsafe handling of untrusted input, use code scanning, and pin third-party actions for stronger supply-chain security.

References:

- <https://google.github.io/eng-practices/review/reviewer/standard.html>
- <https://google.github.io/eng-practices/review/developer/small-cls.html>
- <https://martinfowler.com/articles/continuousIntegration.html>
- <https://martinfowler.com/bliki/TestPyramid.html>
- <https://docs.github.com/en/actions/reference/security/secure-use>

## Ratings

| Area | Score | Evidence And Rationale |
| --- | ---: | --- |
| Local developer workflow | 8/10 | Strong `uv`, `Makefile`, Ruff, mypy, pytest, pre-commit, `.editorconfig`, `.python-version`, `AGENTS.md`, and `CLAUDE.md` setup. |
| CI/CD automation | 3/10 | `make ci-local` exists, but no `.github/workflows` files were present, so quality gates are not enforced remotely. |
| Test health | 7/10 | Re-review: `make ci-local` passed and `make test-cov` produced 321 passed, 2 skipped. Remaining issue: pytest-asyncio and async-lru warnings indicate test lifecycle cleanup is still not fully clean. |
| Coverage depth | 6/10 | Total coverage was 78%. Strong coverage exists in several core models/services, but CLI, server manager, MCP facade, annotations routes, and prompts/resources are weak. |
| Architecture and modularity | 6/10 | The route/service/repository/MCP layering is good. The main risk is large coordination modules: `review_context_service.py`, `repositories/review_rerag.py`, and `mcp/facade.py`. |
| LLM coding friendliness | 7/10 | Shared agent guidance and Makefile commands are excellent. Large files, private framework internals, and global singletons make automated edits riskier. |
| DRY/KISS/SOLID | 6/10 | There is useful separation of services and repositories, but REST/MCP adapter patterns repeat and broad `Any`/`cast` usage weakens explicit contracts. |
| Production readiness | 6/10 | Docker hardening is strong: non-root user, healthcheck, read-only production overlay, cap drop, tmpfs, and resource limits. Missing release workflow, image scanning, SBOM, dependency review, and deployment promotion. |
| Security posture | 6/10 | URL safety and Docker controls are good. CI security, CodeQL, dependency review, and image scanning are absent because CI is absent. |
| Observability and operability | 5/10 | Structured logging and `/health` exist. Metrics, dependency readiness checks, tracing, error budgets, and production dashboards are not present. |

## Key Findings

### 1. The Test Suite Is Now Green, With Lifecycle Warnings Remaining

Command run:

```bash
make test-cov
```

Initial observed result:

- 317 tests collected
- 314 passed
- 1 failed
- 2 skipped
- Total coverage: 78%

Re-review observed result:

- 323 tests collected
- 321 passed
- 2 skipped
- Total coverage: 78%

Previously failing test:

```text
tests/test_routes/test_publications.py::TestPublicationRoutes::test_publication_passages_endpoint_returns_compact_passages
```

Failure mode:

```text
RuntimeError: Event loop is closed
```

The failure occurred during `TestClient` shutdown through `UnifiedServerManager.lifespan()` and `cleanup_dependencies()`, where a global `_api_client` was closed after its owning event loop had already closed.

Current implementation status:

- `cleanup_dependencies()` now clears `_api_client` before closing it.
- It ignores `RuntimeError("Event loop is closed")` during stale client cleanup.
- A regression test covers this stale closed-loop cleanup path.

Impact:

- CI can now be added without immediately failing on this test.
- Tests still emit lifecycle warnings, so there is remaining cleanup debt.
- Module-level singleton dependencies still make ownership less explicit than app-scoped resources.

Priority: P1.

Recommended fix:

- Move shared runtime dependencies into FastAPI app lifespan state instead of module-level globals.
- Make cleanup idempotent and scoped to the application instance that created the resources.
- Add regression tests around repeated `TestClient(app)` startup/shutdown and parallel route tests.
- Remove the custom session-scoped `event_loop` fixture before pytest-asyncio makes this deprecation a hard failure.

### 2. CI/CD Is Missing

No `.github/workflows` files were found in the checkout.

The repository already has a good local gate:

```bash
make ci-local
```

Current local CI target runs:

- `format-check`
- `lint-ci`
- `typecheck-fast`
- `test-fast`

Impact:

- PRs can merge without automated validation.
- Broken tests, formatting drift, or type errors may be discovered late.
- LLM coding workflows lose a critical external feedback loop.

Priority: P0.

Recommended workflow set:

- `ci.yml`: run on pull request and push to main.
- `coverage.yml`: run `make test-cov`, upload coverage artifact, enforce threshold.
- `docker.yml`: build Docker image and render Compose configs.
- `security.yml`: CodeQL, dependency review, and image vulnerability scan.

Minimum initial CI job:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<pinned-sha>
      - uses: astral-sh/setup-uv@<pinned-sha>
      - run: uv sync --group dev --frozen
      - run: make ci-local
```

Use pinned full-length SHAs for third-party actions if the project wants the strongest supply-chain posture.

### 3. Runtime Dependency Globals Are A Maintainability Risk

The FastAPI dependency module stores runtime state in module globals:

- `_api_client`
- `_publication_service`
- `_publication_passage_service`
- `_review_pool`
- `_review_repository`
- `_review_queue`
- `_review_context_service`

Impact:

- Tests can leak state between cases.
- Multiple app instances can share resources accidentally.
- Cleanup can close resources owned by another lifecycle.
- Gunicorn/multi-worker behavior is harder to reason about.
- LLM agents may patch symptoms instead of fixing ownership boundaries.

Priority: P0/P1.

Recommended direction:

- Introduce an application container object, for example `AppResources`.
- Create resources in FastAPI lifespan startup.
- Attach them to `app.state`.
- Resolve route dependencies from request/app state.
- Keep module-level fallback only if truly needed for CLI/MCP standalone paths, and test it separately.

### 4. MCP Facade Is Too Large And Coupled To Private Internals

`pubtator_link/mcp/facade.py` defines the MCP server, tool annotations, many tool registrations, resource registration, prompt registration, and an inspection compatibility helper. It also relies on private FastMCP internals such as `_components`, `_tool_manager`, `_resource_manager`, and `_prompt_manager`.

Impact:

- FastMCP upgrades can break tests or runtime behavior.
- Tool additions will keep increasing file size and review complexity.
- LLM coding agents must edit a broad, high-conflict file for unrelated MCP features.

Priority: P1.

Recommended split:

- `pubtator_link/mcp/server.py`: create top-level `FastMCP`.
- `pubtator_link/mcp/tools/literature.py`: search/entity/relation tools.
- `pubtator_link/mcp/tools/publications.py`: publication and passage tools.
- `pubtator_link/mcp/tools/review_rerag.py`: review indexing/retrieval tools.
- `pubtator_link/mcp/inspection.py`: isolate private FastMCP compatibility logic.
- `pubtator_link/mcp/contracts.py`: shared annotations and small typed contracts.

Keep the current public tool names stable while moving implementation.

### 5. Review re-RAG Modules Need Smaller Internal Boundaries

Large modules:

- `pubtator_link/services/review_context_service.py`
- `pubtator_link/repositories/review_rerag.py`
- `pubtator_link/services/full_text_preparation.py`

These modules contain multiple concerns: retrieval, reranking, diagnostics, packing, query execution, row mapping, source summarization, and SQL composition.

Impact:

- Harder code review.
- Harder focused testing.
- Higher merge conflict risk.
- More likely LLM edits will modify unrelated behavior.

Priority: P1.

Recommended split:

- Extract context packing into pure functions or a `ContextPacker`.
- Extract reranking and budget strategy into `review_rerag/ranking.py`.
- Extract diagnostics construction into `review_rerag/diagnostics.py`.
- Extract repository row mappers into `review_rerag_row_mappers.py`.
- Keep SQL execution in repository methods, but move repeated SQL fragments into named constants or small query builder helpers only where it reduces duplication.

### 6. Coverage Is Useful But Should Be Ratcheted

Coverage snapshot from `make test-cov`:

- Total: 78%
- `pubtator_link/cli.py`: 0%
- `pubtator_link/api/routes/annotations.py`: 59%
- `pubtator_link/server_manager.py`: 65%
- `pubtator_link/mcp/facade.py`: 67%
- `pubtator_link/services/publication_service.py`: 70%
- `pubtator_link/services/full_text_preparation.py`: 71%

Priority: P1.

Recommended approach:

- First fix the failing test.
- Set initial coverage threshold at the current verified baseline.
- Increase gradually:
  - Phase 1: 78%
  - Phase 2: 82%
  - Phase 3: 85%
  - Phase 4: 90% for core non-CLI modules
- Add focused tests for lifecycle, MCP registration, annotation route error paths, CLI smoke behavior, and publication service parsing edge cases.

### 7. Strong Existing Practices Should Be Preserved

The following are already strong and should remain project standards:

- `uv.lock` as dependency source of truth.
- `make` as the human and agent command surface.
- Ruff formatting/linting.
- Strict mypy.
- Fast default pytest, with coverage available explicitly.
- Shared `AGENTS.md` guidance.
- Lean `CLAUDE.md` that points to `AGENTS.md`.
- Docker non-root runtime.
- Production Compose hardening with read-only filesystem, tmpfs, no-new-privileges, and dropped capabilities.
- URL safety protections for public/full-text retrieval.

## Recommended Fast Path

### Phase 1: Stabilize The Test Gate And Remove Lifecycle Warnings

Target time: 0.5-1 day.

Actions:

1. Remove or replace the custom session-scoped `event_loop` fixture in `tests/conftest.py`.
2. Eliminate the async-lru event-loop reset warnings by clearing caches explicitly or avoiding cross-loop cached service state in tests.
3. Run `make ci-local`.
4. Run `make test-cov`.
5. Record the passing coverage baseline.

Exit criteria:

- `make ci-local` passes.
- `make test-cov` passes.
- Test output has no pytest-asyncio deprecation warning.
- Coverage baseline is documented and enforced.

### Phase 2: Add CI/CD Enforcement

Target time: 0.5-1 day.

Actions:

1. Add `.github/workflows/ci.yml`.
2. Add `.github/workflows/security.yml`.
3. Add `.github/workflows/docker.yml`.
4. Add branch protection requiring CI.
5. Add dependency review for PRs.

Exit criteria:

- Every PR runs format, lint, typecheck, tests, and Docker build checks.
- CI token permissions are least-privilege.
- Security checks run without requiring secrets on untrusted pull requests.

### Phase 3: Make The Codebase Easier For LLM Agents To Change

Target time: 2-4 days.

Actions:

1. Add `docs/development/architecture.md`.
2. Document where to add:
   - REST routes
   - service logic
   - repository queries
   - MCP tools
   - tests
3. Split MCP tool registration by domain.
4. Move private FastMCP inspection logic behind a single compatibility helper.
5. Add tests that assert public MCP tool names and schemas remain stable.

Exit criteria:

- Adding a new MCP tool requires touching a small domain file, not the whole facade.
- Architecture documentation gives LLM agents a clear edit map.
- Existing MCP tests pass.

### Phase 4: Refactor re-RAG Internals In Small PRs

Target time: 3-7 days.

Actions:

1. Extract pure context packing functions and test them directly.
2. Extract reranking strategy and budget strategy.
3. Extract diagnostics construction.
4. Extract repository row mapping helpers.
5. Keep behavior stable with regression tests.

Exit criteria:

- Large files shrink.
- Core retrieval behavior is covered by focused unit tests.
- No public API or MCP tool behavior changes unless explicitly planned.

### Phase 5: Production Hardening

Target time: 2-5 days.

Actions:

1. Add readiness endpoint that checks optional database connectivity when review re-RAG is enabled.
2. Add Prometheus-style metrics or OpenTelemetry instrumentation.
3. Add structured request IDs/correlation IDs.
4. Add Docker image vulnerability scanning.
5. Add SBOM generation.
6. Define release and rollback process.

Exit criteria:

- Operators can distinguish process health from dependency readiness.
- Releases are reproducible.
- Image and dependency risk are visible before deployment.

## Suggested GitHub Actions Roadmap

### Required

- CI on PR and push to main.
- Coverage report and threshold.
- Docker build verification.
- Dependency review.
- CodeQL.

### Recommended

- Scheduled dependency update workflow or Dependabot configuration.
- Release workflow that builds and publishes tagged Docker images.
- SBOM generation.
- Container vulnerability scanning.
- Workflow permissions restricted at top level and tightened per job where needed.

### Example Job Matrix

Start with Python 3.11 only because `.python-version` is 3.11 and mypy targets 3.11.

Later add:

- Python 3.12 smoke test.
- Python 3.13 smoke test if all dependencies support it.

Do not expand the matrix until the single-version gate is stable.

## Suggested Pull Request Checklist

Add this to a PR template:

```markdown
## Quality Checklist

- [ ] Change is focused and small enough to review.
- [ ] Related tests were added or updated.
- [ ] `make ci-local` passes locally.
- [ ] Public REST/MCP behavior changes are documented.
- [ ] New runtime dependencies are justified.
- [ ] New network/file/database behavior has safety limits.
- [ ] For MCP tools: descriptions are research-use scoped and schemas are LLM-friendly.
- [ ] For database changes: migration/schema tests are included.
```

## High-Value Backlog

| Priority | Item | Why It Matters |
| --- | --- | --- |
| P0 | Add GitHub Actions CI | Prevents broken merges and supports fast LLM iteration. |
| P0 | Add branch protection | Makes CI meaningful. |
| P1 | Remove pytest-asyncio custom event-loop deprecation | Prevents future pytest-asyncio upgrades from breaking tests. |
| P1 | Move dependency singletons to app-scoped resources | Reduces lifecycle bugs and test leakage. |
| P1 | Add coverage threshold | Prevents silent coverage regression. |
| P1 | Split MCP facade by domain | Reduces merge conflicts and LLM edit risk. |
| P1 | Split re-RAG packing/ranking/diagnostics | Improves testability and modularity. |
| P1 | Add architecture guide for agents | Gives LLMs clear boundaries. |
| P2 | Add CodeQL and dependency review | Improves supply-chain and code security posture. |
| P2 | Add image scanning and SBOM | Improves production release safety. |
| P2 | Add metrics/readiness/tracing | Improves operability. |

## Final Assessment

PubTator-Link is on a good trajectory. The local development system is already stronger than many early-stage Python tools, and the repository contains useful tests and agent guidance.

The next quality jump should not be more feature work. It should be:

1. Make the test suite green.
2. Enforce the local quality gate in GitHub Actions.
3. Reduce the size and coupling of high-change modules.
4. Add lightweight production observability and release security.

That path will improve speed and quality at the same time because it gives both humans and LLM coding agents faster feedback, clearer boundaries, and less risky files to edit.
