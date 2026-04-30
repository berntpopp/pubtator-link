# PubTator-Link Maintainability, CI/CD, And LLM Development Review

Date: 2026-04-30

Post-merge update: 2026-04-30

## Executive Summary

PubTator-Link now has a strong enforceable foundation for local and remote
quality gates. The foundation quality gate work has been merged into `main` and
addressed the highest-priority gaps from the initial review:

- GitHub Actions now cover CI, Docker validation, CodeQL, and dependency review.
- Coverage is enforced with `fail_under = 78`.
- The test lifecycle warnings were removed by dropping the custom pytest event
  loop fixture and resetting async-lru loop metadata in tests.
- FastAPI runtime resources are now app-scoped through lifespan-owned
  `AppResources`, with fallback globals retained only for non-request paths.
- PR quality checklist and branch protection guidance now exist.

The current bottleneck is no longer the missing foundation gate. The next
maintainability gains should come from reducing large, high-change modules and
making MCP/review re-RAG changes smaller, safer, and easier for LLM coding
agents to execute.

## Current Verification Baseline

Verified on merged `main`:

```bash
make format
make lint
make typecheck
make test
```

Observed results:

- `make format`: 75 files unchanged.
- `make lint`: all checks passed.
- `make typecheck`: success, 40 source files.
- `make test`: 333 passed, 2 skipped.

Additional verification during the foundation-gate work:

- `make ci-local`: 333 passed, 2 skipped.
- `make test-cov`: 333 passed, 2 skipped, total coverage 78.64%, threshold 78%.
- `make docker-prod-config`: passed.
- `make docker-npm-config`: passed.
- `docker build -f docker/Dockerfile -t pubtator-link:ci .`: passed.

The two skipped tests are PostgreSQL integration tests that require
`PUBTATOR_LINK_TEST_DATABASE_URL`.

## Review Strategy

This review uses current external engineering guidance as the yardstick:

- Google Engineering Practices: code review should improve code health over
  time, prioritize technical facts over preference, keep changes small, and
  include relevant tests.
- Martin Fowler's Continuous Integration guidance: automate the build, make it
  self-testing, trigger builds on mainline changes, fix broken builds quickly,
  and keep feedback fast.
- Martin Fowler's Test Pyramid: prefer many focused low-level tests, fewer broad
  integration tests, and use higher-level failures to identify missing
  lower-level coverage.
- GitHub Actions security guidance: apply least-privilege permissions, protect
  secrets, avoid unsafe handling of untrusted input, use code scanning, and
  eventually pin third-party actions to full-length SHAs.

References:

- <https://google.github.io/eng-practices/review/reviewer/standard.html>
- <https://google.github.io/eng-practices/review/developer/small-cls.html>
- <https://martinfowler.com/articles/continuousIntegration.html>
- <https://martinfowler.com/bliki/TestPyramid.html>
- <https://docs.github.com/en/actions/reference/security/secure-use>

## Ratings

| Area | Score | Evidence And Rationale |
| --- | ---: | --- |
| Local developer workflow | 9/10 | Strong `uv`, `Makefile`, Ruff, mypy, pytest, pre-commit, `.editorconfig`, `.python-version`, `AGENTS.md`, `CLAUDE.md`, and verified local commands. |
| CI/CD automation | 8/10 | CI, Docker, and security workflows now exist. Remaining gaps: release workflow, action pinning policy, image scanning, SBOM, and published artifacts. |
| Test health | 8/10 | `make test` passes with 333 passed, 2 skipped. Pytest event-loop and async-lru lifecycle warnings were removed. PostgreSQL integration tests still need an opt-in CI service if they should be required. |
| Coverage depth | 7/10 | Coverage is enforced at 78% and currently reports 78.64%. The margin is narrow, and CLI, server manager paths, MCP facade, and some route error paths remain weak. |
| Architecture and modularity | 7/10 | App resource ownership is much cleaner after `AppResources`. Route/service/repository layering is solid. Main remaining risk is large MCP and review re-RAG modules. |
| LLM coding friendliness | 8/10 | Agent instructions, plans/specs, Make targets, PR checklist, branch protection docs, and CI guardrails are strong. Large files still increase edit risk. |
| DRY/KISS/SOLID | 7/10 | App lifecycle is more explicit and less global. Remaining duplication and broad contracts appear mainly in MCP adapters and review re-RAG internals. |
| Production readiness | 7/10 | Docker hardening, health checks, Compose validation, and image build checks are in place. Missing release promotion, readiness checks, metrics, SBOM, and vulnerability scanning. |
| Security posture | 7/10 | URL safety, Docker controls, CodeQL, dependency review, and least-privilege workflow permissions are now present. Action SHA pinning and container scanning remain. |
| Observability and operability | 5/10 | Structured logging and `/health` exist. Metrics, readiness, request IDs, tracing, dashboards, and runbooks are still missing. |

## What Improved

### 1. CI/CD Is Now Enforced Remotely

Added workflows:

- `.github/workflows/ci.yml`
- `.github/workflows/docker.yml`
- `.github/workflows/security.yml`

The CI workflow runs `uv sync --group dev --frozen`, `make ci-local`, and
`make test-cov`. Docker validation renders the production and NPM Compose
overlays and builds the Docker image. Security runs CodeQL and dependency
review with narrowed permissions.

Impact:

- PRs can now receive fast automated feedback.
- The local `Makefile` gate and remote CI gate are aligned.
- LLM-produced changes have an external correctness loop.

Remaining work:

- Enable branch protection in GitHub using `docs/development/branch-protection.md`.
- Decide whether to pin actions to full-length SHAs.
- Add release/image publishing workflow when deployment is ready.

### 2. Test Lifecycle Is Cleaner

The custom session-scoped pytest `event_loop` fixture was removed. Tests now
reset async-lru method cache loop metadata for `PublicationService` methods that
otherwise retain event-loop state across function-scoped pytest loops.

Impact:

- Test output is cleaner.
- Future pytest-asyncio upgrades are less likely to break the suite.
- The stale closed-loop cleanup workaround is no longer the main lifecycle
  strategy.

### 3. Runtime Resource Ownership Is Better

`pubtator_link/api/routes/dependencies.py` now defines app-owned resources
through `AppResources`. `UnifiedServerManager` creates and closes those
resources in FastAPI lifespan, binds them during HTTP requests, and avoids
closing active resources prematurely during server shutdown.

Impact:

- Multiple app instances are easier to reason about.
- Tests are less likely to leak shared module-level state.
- Lifespan ownership is clearer for API client, publication services, review
  pool, review queue, and review context service.

Remaining work:

- Keep fallback globals only for CLI/MCP standalone paths.
- Add more server-manager coverage for startup failure and transport paths as
  future changes touch them.

### 4. Repository Guidance Is Stronger

Added:

- `.github/pull_request_template.md`
- `docs/development/branch-protection.md`
- Guardrail tests in `tests/unit/test_development_tooling.py`

Impact:

- PR authors and LLM agents get clearer quality expectations.
- Required checks are documented by their expected GitHub names.
- Tooling drift is now covered by tests.

## Remaining Key Findings

### 1. Coverage Threshold Has Very Little Headroom

Current coverage is 78.64% with `fail_under = 78`.

Impact:

- A small uncovered change can break CI.
- This is acceptable as a first gate, but it will feel brittle unless the next
  few implementation PRs include focused tests.

Priority: P1.

Recommended next move:

- Add targeted tests that raise coverage to at least 80% before larger refactors.
- Do not raise `fail_under` until the new level is consistently above the target.

### 2. MCP Facade Remains Too Large

`pubtator_link/mcp/facade.py` still centralizes server creation, tool
registration, annotations, resources, prompts, and compatibility inspection.

Impact:

- Tool additions create broad merge conflict risk.
- LLM agents must edit a high-context file for small domain changes.
- Private FastMCP compatibility logic is still a localized upgrade risk.

Priority: P1.

Recommended direction:

- Split tools by domain while preserving public tool names and schemas.
- Isolate private FastMCP inspection code in one compatibility module.
- Add tests that lock public MCP tool names, resource URIs, and prompt names.

### 3. Review re-RAG Internals Need Smaller Boundaries

Large modules remain:

- `pubtator_link/services/review_context_service.py`
- `pubtator_link/repositories/review_rerag.py`
- `pubtator_link/services/full_text_preparation.py`

Impact:

- Harder review and higher regression risk.
- Less direct unit testing around ranking, packing, diagnostics, and row
  mapping.
- More difficult for LLM coding agents to make focused edits.

Priority: P1.

Recommended direction:

- Extract pure context packing functions.
- Extract reranking and budget strategy.
- Extract diagnostics construction.
- Extract repository row mapping helpers.
- Keep public REST/MCP behavior stable during the split.

### 4. Production Operability Is Still Basic

The app has structured logging and `/health`, but not full production
operability.

Priority: P2.

Recommended direction:

- Add readiness endpoint that checks database connectivity when review re-RAG is
  enabled.
- Add request IDs/correlation IDs.
- Add metrics or OpenTelemetry instrumentation.
- Add runbook documentation for deploy, rollback, and incident checks.

### 5. Release Security Is Not Complete

CI security exists, but release security is still early.

Priority: P2.

Recommended direction:

- Add Docker image vulnerability scanning.
- Add SBOM generation.
- Decide on action pinning policy.
- Add a release workflow for tagged Docker images.

## Updated Fast Path

### Phase 1: Turn On Branch Protection

Target time: 15-30 minutes.

Actions:

1. Open GitHub repository settings.
2. Protect `main`.
3. Require PRs before merging.
4. Require status checks from `docs/development/branch-protection.md`.
5. Require branches to be up to date before merging.
6. Require stale approval dismissal.

Exit criteria:

- `main` cannot be updated without the new CI/Docker/security gates.

### Phase 2: Raise Coverage Headroom

Target time: 0.5-1 day.

Actions:

1. Add focused tests for low-coverage high-value areas:
   - `server_manager.py` startup/shutdown and transport choices.
   - MCP facade registration stability.
   - annotation route error paths.
   - CLI smoke behavior.
2. Re-run `make test-cov`.
3. If coverage is consistently above 80%, consider raising `fail_under` to 80.

Exit criteria:

- Coverage is at least 80%.
- New tests cover behavior rather than implementation trivia.

### Phase 3: Split MCP By Domain

Target time: 1-2 days.

Actions:

1. Create a spec and plan under `docs/superpowers/specs/` and
   `docs/superpowers/plans/`.
2. Add characterization tests for current MCP tool names, resources, prompts,
   and schema-relevant metadata.
3. Split tool registration into domain modules.
4. Keep `facade.py` as an orchestration layer.
5. Preserve public tool names.

Exit criteria:

- Adding a new MCP tool requires touching a small domain file.
- Existing MCP tests and characterization tests pass.

### Phase 4: Split Review re-RAG Internals

Target time: 2-4 days.

Actions:

1. Extract context packing into pure functions/classes.
2. Extract ranking/budget strategy.
3. Extract diagnostics assembly.
4. Extract row mappers from repository SQL execution.
5. Add focused tests for each extracted unit.

Exit criteria:

- Large files shrink.
- Regression tests protect current review output shape.
- REST and MCP behavior remains stable.

### Phase 5: Add Release And Operability Hardening

Target time: 1-3 days.

Actions:

1. Add image scanning.
2. Add SBOM generation.
3. Add tagged release workflow.
4. Add readiness endpoint.
5. Add request IDs and basic metrics.
6. Document deployment and rollback.

Exit criteria:

- A release can be built, scanned, and promoted consistently.
- Operators can distinguish process health from dependency readiness.

## High-Value Backlog

| Priority | Item | Status | Why It Matters |
| --- | --- | --- | --- |
| P0 | Add GitHub Actions CI | Done | Prevents broken merges and supports fast LLM iteration. |
| P0 | Add branch protection docs | Done | Documents how to make CI meaningful. |
| P0 | Enable branch protection in GitHub | Next | Converts documentation into enforcement. |
| P1 | Remove pytest-asyncio event-loop warning | Done | Avoids future pytest-asyncio breakage. |
| P1 | Move dependencies to app-scoped resources | Done | Reduces lifecycle bugs and test leakage. |
| P1 | Add coverage threshold | Done | Prevents silent coverage regression. |
| P1 | Raise coverage above 80% | Next | Gives the threshold headroom. |
| P1 | Split MCP facade by domain | Next | Reduces merge conflicts and LLM edit risk. |
| P1 | Split re-RAG packing/ranking/diagnostics | Next | Improves testability and modularity. |
| P1 | Add architecture guide for agents | Next | Gives LLMs clearer boundaries. |
| P2 | Add image scanning and SBOM | Later | Improves production release safety. |
| P2 | Add metrics/readiness/tracing | Later | Improves operability. |

## Final Assessment

PubTator-Link has moved from "good local practices but weak enforcement" to a
much stronger foundation: local gates, remote CI, coverage enforcement, Docker
validation, security checks, PR guidance, and clearer runtime ownership.

The next quality jump should focus on reducing change risk:

1. Enable branch protection so the new workflows matter.
2. Add enough tests to move coverage above 80%.
3. Split the MCP facade by domain.
4. Split review re-RAG internals into smaller tested units.
5. Add release and operability hardening when deployment is the priority.

That sequence keeps momentum high: it protects `main`, gives LLM agents faster
feedback, and makes future feature work smaller and safer.
