# Foundation Quality Gate Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

## Goal

Create a fast, enforceable development quality gate for PubTator-Link before larger architecture refactors. The first iteration should make local and remote validation trustworthy, remove current test lifecycle warnings, establish a coverage baseline, and reduce dependency cleanup risk without changing public REST or MCP behavior.

## Background

The maintainability review found that PubTator-Link already has strong local development primitives:

- `uv` and `uv.lock` for reproducible dependency management.
- `Makefile` targets for format, lint, typecheck, tests, coverage, Docker, and local CI.
- Ruff, strict mypy, pytest, pytest-cov, pytest-xdist, and pre-commit.
- Docker production hardening and shared agent instructions in `AGENTS.md`.

The re-review confirmed that the immediate test failure is resolved:

- `make ci-local` passed with 321 passed and 2 skipped.
- `make typecheck-fast` passed with no mypy issues.
- `make test-cov` passed with 321 passed, 2 skipped, and 78% total coverage.

Remaining foundation risks:

- No `.github/workflows` files exist, so PRs and `main` are not protected by remote CI.
- `tests/conftest.py` overrides pytest-asyncio's `event_loop` fixture at session scope, producing a deprecation warning that can become a future failure.
- Some tests trigger `async_lru` event-loop reset warnings, indicating cross-loop cached state in tests.
- FastAPI dependencies still use module-level global singletons for clients, services, queues, and pools. The stale event-loop symptom is handled, but ownership is still implicit.
- Coverage has no enforced threshold, so the 78% baseline can silently regress.

## Scope

In scope:

- Remove pytest lifecycle warnings from the default test and coverage runs.
- Replace or contain module-level dependency global cleanup with app-scoped resource ownership for FastAPI server lifecycles.
- Keep existing dependency function names and route dependency aliases stable.
- Add GitHub Actions CI for PR and `main` validation.
- Add a coverage threshold starting at the current verified baseline of 78%.
- Add Docker build/config validation to CI.
- Add dependency review and CodeQL security workflows where they can run safely without deployment secrets.
- Add branch protection and PR checklist documentation.
- Keep all existing REST routes, MCP tool names, request schemas, and response schemas unchanged.

Out of scope:

- Splitting `pubtator_link/mcp/facade.py`.
- Splitting review re-RAG service/repository modules.
- Adding metrics, tracing, OpenTelemetry, dashboards, or SLOs.
- Publishing Docker images.
- Deployment automation.
- Changing dependency versions except where required for workflow actions.
- Raising coverage above the current baseline in this iteration.
- Making PostgreSQL integration tests mandatory when `PUBTATOR_LINK_TEST_DATABASE_URL` is not set.

## Public Contract

No public API behavior changes are intended.

REST behavior remains unchanged:

- Route paths stay the same.
- Request and response schemas stay the same.
- Error status codes and response body shapes stay the same.

MCP behavior remains unchanged:

- Public tool names stay the same.
- Tool argument schemas stay the same.
- Tool annotations and research-use language stay the same.

Developer contract changes:

- Pull requests must pass CI before merge.
- Coverage must not fall below 78%.
- `make ci-local` remains the local pre-handoff command.
- `make test-cov` becomes a real gate, not just an informational report.
- Default test output should be warning-clean for project-owned warnings.

## Design

### Test Lifecycle Cleanup

Remove the custom session-scoped `event_loop` fixture in `tests/conftest.py`.

Current pytest-asyncio versions support function-scoped event loops by default. Tests that need async execution should use `pytest.mark.asyncio`, `pytest.mark.anyio`, or the existing async test client fixtures instead of overriding the event loop globally.

For the `async_lru` warnings, identify cached functions or services that retain loop-bound state between tests. The first iteration should avoid behavior changes by clearing relevant caches in test teardown or by ensuring tests do not reuse loop-bound clients across event loops.

Acceptance:

- `make test` emits no pytest-asyncio event-loop deprecation warning.
- `make test-cov` emits no pytest-asyncio event-loop deprecation warning.
- The `async_lru` loop reset warning is eliminated from the normal test run.

### App-Scoped Dependency Resources

Introduce an explicit runtime resource container for app-owned dependencies.

Suggested shape:

```python
@dataclass
class AppResources:
    logger: FilteringBoundLogger
    api_client: PubTator3Client
    publication_service: PublicationService
    publication_passage_service: PublicationPassageService
    review_pool: asyncpg.Pool | None = None
    review_repository: PostgresReviewReragRepository | None = None
    review_queue: ReviewPreparationQueue | None = None
    review_context_service: ReviewContextService | None = None
```

`UnifiedServerManager.lifespan()` should create `AppResources`, attach it to `app.state.pubtator_resources`, start optional review queue resources when `settings.database_url` is configured, and close only resources that were created for that app instance.

Route dependency functions should first resolve app-scoped resources when request context is available. Existing dependency aliases such as `ClientDep`, `PublicationServiceDep`, `PublicationPassageServiceDep`, `ReviewQueueDep`, and `ReviewContextServiceDep` should keep their names so route code does not churn.

The existing module-level fallback can remain temporarily for non-request contexts or MCP helpers if needed, but FastAPI application lifecycles should not rely on it. Any fallback should be small, tested, and documented as compatibility code.

Acceptance:

- Repeated `TestClient(UnifiedServerManager().create_app())` startup/shutdown does not rely on ignoring stale event-loop runtime errors.
- `cleanup_dependencies()` no longer needs to swallow `RuntimeError("Event loop is closed")` for normal FastAPI app shutdown.
- Route dependency override tests continue to work.
- Review queue startup/shutdown behavior remains covered.

### Coverage Baseline

Set the coverage gate to the verified current baseline:

```toml
[tool.coverage.report]
fail_under = 78
```

Keep HTML and terminal missing-line reports.

This iteration should not chase broad coverage increases. The purpose is to prevent regression. Future ratchets should be explicit follow-up work.

Recommended follow-up ratchet:

- 78% now.
- 82% after CLI/server-manager/MCP facade smoke coverage.
- 85% after route error-path coverage.
- 90% for selected core non-CLI modules after architecture refactors.

Acceptance:

- `make test-cov` fails below 78%.
- `make test-cov` passes at the current baseline.
- CI runs the same coverage gate.

### GitHub Actions CI

Add `.github/workflows/ci.yml`.

Trigger:

- `pull_request`
- `push` to `main`

Permissions:

```yaml
permissions:
  contents: read
```

Jobs:

- Install Python 3.11.
- Install `uv`.
- Run `uv sync --group dev --frozen`.
- Run `make ci-local`.
- Run `make test-cov`.

Use Python 3.11 only in this first iteration because `.python-version`, Ruff, mypy, and current local verification all target Python 3.11. Add Python 3.12/3.13 smoke jobs later after the base gate is stable.

Acceptance:

- CI uses the same commands documented in `AGENTS.md`.
- CI fails on format, lint, typecheck, tests, or coverage regression.
- CI does not require secrets.

### Docker Validation CI

Add `.github/workflows/docker.yml` or a separate job in `ci.yml`.

Validation:

- `make docker-prod-config`
- `make docker-npm-config`
- `docker build -f docker/Dockerfile -t pubtator-link:ci .`

Acceptance:

- Docker image build is validated on PRs.
- Compose production and NPM overlays render successfully.
- No registry credentials are required.

### Security CI

Add `.github/workflows/security.yml`.

Initial checks:

- CodeQL for Python.
- Dependency review on pull requests.

Optional if workflow time remains acceptable:

- Docker image vulnerability scan against the locally built image.
- SBOM generation as an artifact.

Security workflows should use least-privilege permissions and must not run deployment or registry credentials on untrusted pull requests.

Acceptance:

- CodeQL runs on pull requests and `main`.
- Dependency review runs on pull requests.
- Security workflows do not require project secrets.

### PR Checklist And Branch Protection Docs

Add `.github/pull_request_template.md` with a compact quality checklist:

- Focused change.
- Tests added or updated.
- `make ci-local` passed locally.
- Public REST/MCP behavior documented when changed.
- New dependencies justified.
- Network/file/database behavior has limits.
- MCP tools remain research-use scoped.
- Database changes include schema tests.

Add `docs/development/branch-protection.md` documenting recommended GitHub branch protection:

- Require `ci` workflow.
- Require coverage job.
- Require Docker validation.
- Require CodeQL/dependency review where available.
- Require pull request review before merge.
- Dismiss stale approvals when new commits are pushed.
- Require linear history if the repository prefers it.

Acceptance:

- Contributors see the checklist when opening PRs.
- Maintainers have exact branch-protection guidance.

## Error Handling

CI failures should be straightforward:

- Format/lint/typecheck/test failures should point to `make ci-local`.
- Coverage failures should point to `make test-cov`.
- Docker failures should point to `make docker-prod-config`, `make docker-npm-config`, or `docker build -f docker/Dockerfile -t pubtator-link:ci .`.

Runtime app behavior should not change. If app-scoped resource creation fails, startup should fail loudly rather than falling back to partially initialized globals.

## Testing Strategy

Local verification:

```bash
make ci-local
make test-cov
make docker-prod-config
make docker-npm-config
docker build -f docker/Dockerfile -t pubtator-link:ci .
```

Focused tests to add or update:

- Unit tests for app-scoped resource startup/shutdown.
- Regression tests for repeated `TestClient` lifecycle creation.
- Tests confirming route dependency overrides still work.
- Tests confirming `cleanup_dependencies()` remains safe for compatibility fallback.
- Development-tooling tests that assert the new workflow/template/docs files exist and reference expected commands.

The PostgreSQL integration tests should remain skipped unless `PUBTATOR_LINK_TEST_DATABASE_URL` is set.

## Migration Plan

1. Remove test lifecycle warnings while keeping behavior unchanged.
2. Introduce app-scoped resource ownership with compatibility fallback.
3. Add coverage threshold after confirming the current baseline still passes.
4. Add CI workflow.
5. Add Docker validation workflow.
6. Add security workflow.
7. Add PR checklist and branch protection docs.
8. Run full local verification and record results.

## Risks

### Risk: App-Scoped Resource Refactor Touches Too Much

Mitigation:

- Keep public dependency aliases stable.
- Add tests before changing dependency ownership.
- Keep compatibility fallback temporarily instead of forcing every caller through request state in one step.

### Risk: CI Runtime Becomes Too Slow

Mitigation:

- Start with Python 3.11 only.
- Keep the default gate aligned with existing `make ci-local`.
- Use Docker validation in one job, not a large matrix.

### Risk: Coverage Threshold Is Brittle

Mitigation:

- Start at 78%, the verified baseline.
- Do not ratchet in this iteration.
- Let future feature/refactor work raise the threshold after adding targeted tests.

### Risk: Security Workflows Need Repository Settings

Mitigation:

- Use workflows that run without secrets.
- Document branch protection separately so maintainers can enable required checks in GitHub UI.

## Success Criteria

- `make ci-local` passes locally.
- `make test-cov` passes locally and enforces `fail_under = 78`.
- Default test runs no longer emit pytest-asyncio event-loop deprecation warnings.
- Default test runs no longer emit async-lru event-loop reset warnings.
- FastAPI app lifecycle owns and closes its own resources without relying on stale event-loop suppression.
- GitHub Actions validate format, lint, typecheck, tests, coverage, Docker build/config, CodeQL, and dependency review.
- PR template and branch protection documentation exist.
- REST and MCP public contracts remain unchanged.

## Future Work

- Split `pubtator_link/mcp/facade.py` by MCP domain.
- Split review re-RAG packing, ranking, diagnostics, and repository row mapping into smaller modules.
- Add readiness checks for optional database-backed features.
- Add metrics and tracing.
- Add Docker image publication and release promotion.
- Add SBOM artifacts and image vulnerability scanning if not included in the first security workflow.
