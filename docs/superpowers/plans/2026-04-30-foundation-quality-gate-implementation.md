# Foundation Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PubTator-Link's foundation quality gate enforceable locally and in GitHub Actions while removing current test lifecycle warnings and replacing FastAPI app lifecycle global cleanup with app-scoped resource ownership.

**Architecture:** Add app-owned resource construction and cleanup while preserving existing route dependency names and public REST/MCP behavior. Stabilize tests first, then enforce the verified 78% coverage baseline and add GitHub Actions workflows for CI, Docker validation, and security checks. Keep the work scoped to foundation quality gates; do not split MCP or review re-RAG modules in this plan.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, asyncpg, httpx, async-lru, pytest, pytest-asyncio, pytest-cov, pytest-xdist, Ruff, mypy, uv, Make, GitHub Actions, Docker.

---

## File Map

- Modify `tests/conftest.py`: remove the deprecated custom `event_loop` fixture and add cache cleanup for async-lru cached publication service methods.
- Modify `tests/unit/test_route_dependencies.py`: add regression tests for app-scoped resource construction, context-bound dependency resolution, cleanup, and stale-loop behavior no longer being swallowed in normal cleanup.
- Modify `tests/unit/test_development_tooling.py`: add guardrail tests for coverage threshold, GitHub Actions workflows, PR template, and branch protection docs.
- Modify `pubtator_link/api/routes/dependencies.py`: introduce `AppResources`, app-scoped resource builders/closers, context-aware dependency accessors, and compatibility fallback cleanup.
- Modify `pubtator_link/server_manager.py`: create and close `AppResources` in FastAPI lifespan; stop relying on module-level cleanup during normal app shutdown.
- Modify `pyproject.toml`: add `fail_under = 78` to coverage configuration.
- Create `.github/workflows/ci.yml`: run local CI and coverage on PRs and `main`.
- Create `.github/workflows/docker.yml`: validate Compose overlays and Docker image build.
- Create `.github/workflows/security.yml`: run CodeQL and dependency review.
- Create `.github/pull_request_template.md`: add the contributor quality checklist.
- Create `docs/development/branch-protection.md`: document recommended branch protection settings.

## Task 1: Remove Test Event Loop And async-lru Warnings

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Remove the deprecated custom event loop fixture**

Edit `tests/conftest.py` and remove the `asyncio` import and the custom session-scoped `event_loop` fixture:

```python
import asyncio
```

```python
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
```

The top of the file should start like this after the edit:

```python
"""Test configuration and shared fixtures for PubTator-Link tests."""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
```

- [ ] **Step 2: Add async-lru cache cleanup fixture**

Add this fixture below the imports in `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def clear_publication_service_method_caches() -> None:
    """Prevent async-lru method caches from leaking across test event loops."""
    PublicationService.export_publications.cache_clear()
    PublicationService.export_pmc_publications.cache_clear()
    PublicationService.search_publications.cache_clear()
```

This fixture intentionally clears the class-level async-lru wrappers before each test. It avoids loop-bound cached futures being reused by tests that pytest-asyncio runs on separate function-scoped loops.

- [ ] **Step 3: Run the focused test suite and confirm warnings are gone**

Run:

```bash
uv run pytest tests/test_client.py tests/test_routes/test_publications.py tests/test_services.py tests/integration/test_review_schema_postgres.py -q
```

Expected:

```text
SKIPPED [1] tests/integration/test_review_schema_postgres.py:24: PUBTATOR_LINK_TEST_DATABASE_URL is not set
SKIPPED [1] tests/integration/test_review_schema_postgres.py:58: PUBTATOR_LINK_TEST_DATABASE_URL is not set
```

There should be no warning containing:

```text
The event_loop fixture provided by pytest-asyncio has been redefined
```

There should be no warning containing:

```text
AlruCacheLoopResetWarning
```

- [ ] **Step 4: Commit the test lifecycle cleanup**

Run:

```bash
git add tests/conftest.py
git commit -m "test: remove event loop warning cleanup"
```

## Task 2: Add App-Scoped Resource Tests

**Files:**
- Modify: `tests/unit/test_route_dependencies.py`

- [ ] **Step 1: Add imports for the app resource tests**

Update the imports at the top of `tests/unit/test_route_dependencies.py` to include FastAPI and Request:

```python
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request

from pubtator_link.api.routes import dependencies
```

- [ ] **Step 2: Add lightweight test doubles**

Add these helper classes below the imports:

```python
class CloseableClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class CloseablePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class StoppableQueue:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True
```

- [ ] **Step 3: Add a test for app resource construction without database URL**

Append this test:

```python
@pytest.mark.asyncio
async def test_create_app_resources_builds_core_services_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CloseableClient()
    logger = object()

    monkeypatch.setattr(dependencies, "PubTator3Client", lambda logger=None: client)
    monkeypatch.setattr(dependencies, "PublicationService", lambda client, logger=None: ("pub", client, logger))
    monkeypatch.setattr(
        dependencies,
        "PublicationPassageService",
        lambda publication_service: ("passages", publication_service),
    )
    monkeypatch.setattr(dependencies, "review_rerag_config", SimpleNamespace(database_url=None))

    resources = await dependencies.create_app_resources(logger=logger)

    assert resources.logger is logger
    assert resources.api_client is client
    assert resources.publication_service == ("pub", client, logger)
    assert resources.publication_passage_service == ("passages", ("pub", client, logger))
    assert resources.review_pool is None
    assert resources.review_repository is None
    assert resources.review_queue is None
    assert resources.review_context_service is None
```

- [ ] **Step 4: Add a test for app resource construction with database URL**

Append this test:

```python
@pytest.mark.asyncio
async def test_create_app_resources_builds_review_resources_with_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CloseableClient()
    pool = CloseablePool()
    queue = StoppableQueue()
    logger = object()
    captured_pool_kwargs: dict[str, Any] = {}

    async def create_pool(**kwargs: Any) -> CloseablePool:
        captured_pool_kwargs.update(kwargs)
        return pool

    monkeypatch.setattr(dependencies, "PubTator3Client", lambda logger=None: client)
    monkeypatch.setattr(dependencies, "PublicationService", lambda client, logger=None: ("pub", client, logger))
    monkeypatch.setattr(
        dependencies,
        "PublicationPassageService",
        lambda publication_service: ("passages", publication_service),
    )
    monkeypatch.setattr(dependencies.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(
        dependencies,
        "review_rerag_config",
        SimpleNamespace(
            database_url="postgresql://user:pass@localhost:5434/pubtator_link",
            prep_concurrency=2,
        ),
    )
    monkeypatch.setattr(dependencies, "PostgresReviewReragRepository", lambda pool: ("repo", pool))
    monkeypatch.setattr(
        dependencies,
        "FullTextPreparationService",
        lambda config, repository, pubtator_client, logger: (
            "prep",
            config,
            repository,
            pubtator_client,
            logger,
        ),
    )
    monkeypatch.setattr(
        dependencies,
        "ReviewPreparationQueue",
        lambda config, repository, preparation, logger: queue,
    )
    monkeypatch.setattr(dependencies, "ReviewContextService", lambda repository: ("context", repository))

    resources = await dependencies.create_app_resources(logger=logger)

    assert resources.review_pool is pool
    assert resources.review_repository == ("repo", pool)
    assert resources.review_queue is queue
    assert resources.review_context_service == ("context", ("repo", pool))
    assert captured_pool_kwargs == {
        "dsn": "postgresql://user:pass@localhost:5434/pubtator_link",
        "min_size": 1,
        "max_size": 6,
    }
```

- [ ] **Step 5: Add a test for closing app-owned resources**

Append this test:

```python
@pytest.mark.asyncio
async def test_close_app_resources_closes_only_owned_resources() -> None:
    client = CloseableClient()
    pool = CloseablePool()
    queue = StoppableQueue()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=client,
        publication_service=object(),
        publication_passage_service=object(),
        review_pool=pool,
        review_queue=queue,
    )

    await dependencies.close_app_resources(resources)

    assert queue.stopped is True
    assert pool.closed is True
    assert client.closed is True
```

- [ ] **Step 6: Add tests for context-bound resource access through stable dependency names**

Append these tests:

```python
def test_resources_from_request_returns_app_state_resources() -> None:
    app = FastAPI()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=CloseableClient(),
        publication_service=object(),
        publication_passage_service=object(),
    )
    app.state.pubtator_resources = resources
    request = Request({"type": "http", "app": app})

    assert dependencies.resources_from_request(request) is resources


@pytest.mark.asyncio
async def test_context_bound_resources_are_available_to_existing_dependency_names() -> None:
    client = CloseableClient()
    publication_service = object()
    passage_service = object()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=client,
        publication_service=publication_service,
        publication_passage_service=passage_service,
    )

    token = dependencies.bind_app_resources(resources)
    try:
        assert dependencies.current_app_resources() is resources
        assert await dependencies.get_api_client() is client
        assert await dependencies.get_publication_service() is publication_service
        assert await dependencies.get_publication_passage_service() is passage_service
    finally:
        dependencies.reset_app_resources(token)

    assert dependencies.current_app_resources() is None
```

- [ ] **Step 7: Replace stale closed-loop cleanup test expectation**

Replace `test_cleanup_dependencies_ignores_stale_closed_loop_client` with:

```python
@pytest.mark.asyncio
async def test_cleanup_dependencies_clears_fallback_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CloseableClient()
    monkeypatch.setattr(dependencies, "_api_client", client)
    monkeypatch.setattr(dependencies, "_review_queue", None)
    monkeypatch.setattr(dependencies, "_review_pool", None)

    await dependencies.cleanup_dependencies()

    assert client.closed is True
    assert dependencies._api_client is None
```

- [ ] **Step 8: Run the new tests and verify they fail before implementation**

Run:

```bash
uv run pytest tests/unit/test_route_dependencies.py -q
```

Expected before implementation:

```text
FAILED tests/unit/test_route_dependencies.py::test_create_app_resources_builds_core_services_without_database
FAILED tests/unit/test_route_dependencies.py::test_create_app_resources_builds_review_resources_with_database
FAILED tests/unit/test_route_dependencies.py::test_close_app_resources_closes_only_owned_resources
FAILED tests/unit/test_route_dependencies.py::test_resources_from_request_returns_app_state_resources
FAILED tests/unit/test_route_dependencies.py::test_context_bound_resources_are_available_to_existing_dependency_names
```

The failures should mention missing `AppResources`, `create_app_resources`, `close_app_resources`, `resources_from_request`, `bind_app_resources`, `reset_app_resources`, or `current_app_resources`.

## Task 3: Implement App-Scoped Resources And Lifecycle Ownership

**Files:**
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/server_manager.py`
- Test: `tests/unit/test_route_dependencies.py`

- [ ] **Step 1: Add app resource imports**

In `pubtator_link/api/routes/dependencies.py`, update imports:

```python
from dataclasses import dataclass
from contextvars import ContextVar, Token
```

```python
from fastapi import Depends, HTTPException, Request
```

- [ ] **Step 2: Add `AppResources` and request resolver**

Add this below the module-level globals in `pubtator_link/api/routes/dependencies.py`:

```python
@dataclass
class AppResources:
    """Runtime resources owned by one FastAPI application lifespan."""

    logger: FilteringBoundLogger
    api_client: PubTator3Client
    publication_service: PublicationService
    publication_passage_service: PublicationPassageService
    review_pool: asyncpg.Pool | None = None
    review_repository: PostgresReviewReragRepository | None = None
    review_queue: ReviewPreparationQueue | None = None
    review_context_service: ReviewContextService | None = None


_app_resources_context: ContextVar[AppResources | None] = ContextVar(
    "pubtator_app_resources",
    default=None,
)


def bind_app_resources(resources: AppResources) -> Token[AppResources | None]:
    """Bind app resources to the current request context."""
    return _app_resources_context.set(resources)


def reset_app_resources(token: Token[AppResources | None]) -> None:
    """Reset the current request context resource binding."""
    _app_resources_context.reset(token)


def current_app_resources() -> AppResources | None:
    """Return resources bound to the current request context, if any."""
    return _app_resources_context.get()


def resources_from_request(request: Request) -> AppResources:
    """Return app-scoped resources for route dependency resolution."""
    resources = getattr(request.app.state, "pubtator_resources", None)
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are not initialized")
    return resources
```

- [ ] **Step 3: Add shared review pool parameter helper**

Add this helper below `resources_from_request`:

```python
def review_pool_kwargs() -> dict[str, Any]:
    """Return asyncpg pool arguments for review re-RAG storage."""
    if review_rerag_config.database_url is None:
        raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
    return {
        "dsn": review_rerag_config.database_url,
        "min_size": 1,
        "max_size": max(2, review_rerag_config.prep_concurrency * 2 + 2),
    }
```

- [ ] **Step 4: Add app resource creation and cleanup functions**

Add these functions below `review_pool_kwargs`:

```python
async def create_app_resources(logger: FilteringBoundLogger) -> AppResources:
    """Create resources owned by one FastAPI application lifespan."""
    api_client = PubTator3Client(logger=logger)
    publication_service = PublicationService(client=api_client, logger=logger)
    publication_passage_service = PublicationPassageService(
        publication_service=publication_service
    )

    review_pool: asyncpg.Pool | None = None
    review_repository: PostgresReviewReragRepository | None = None
    review_queue: ReviewPreparationQueue | None = None
    review_context_service: ReviewContextService | None = None

    if review_rerag_config.database_url is not None:
        review_pool = await asyncpg.create_pool(**review_pool_kwargs())
        review_repository = PostgresReviewReragRepository(review_pool)
        preparation = FullTextPreparationService(
            config=review_rerag_config,
            repository=review_repository,
            pubtator_client=api_client,
            logger=logger,
        )
        review_queue = ReviewPreparationQueue(
            config=review_rerag_config,
            repository=review_repository,
            preparation=preparation,
            logger=logger,
        )
        review_context_service = ReviewContextService(repository=review_repository)

    return AppResources(
        logger=logger,
        api_client=api_client,
        publication_service=publication_service,
        publication_passage_service=publication_passage_service,
        review_pool=review_pool,
        review_repository=review_repository,
        review_queue=review_queue,
        review_context_service=review_context_service,
    )


async def close_app_resources(resources: AppResources) -> None:
    """Close resources owned by one FastAPI application lifespan."""
    if resources.review_queue is not None:
        await resources.review_queue.stop()
    if resources.review_pool is not None:
        await resources.review_pool.close()
    await resources.api_client.close()
```

- [ ] **Step 5: Update review pool fallback to reuse the helper**

Replace the body of `get_review_pool()` with:

```python
async def get_review_pool() -> asyncpg.Pool:
    """Get fallback asyncpg pool for review re-RAG storage."""
    global _review_pool
    if _review_pool is None:
        _review_pool = await asyncpg.create_pool(**review_pool_kwargs())
    return _review_pool
```

- [ ] **Step 6: Make existing dependency functions context-aware without renaming them**

Replace the existing `get_logger`, `get_api_client`, `get_publication_service`, `get_publication_passage_service`, `get_review_queue`, and `get_review_context_service` functions with these context-aware versions. The function names intentionally stay the same so existing route dependency overrides continue to work and MCP helper calls can still call them without a request:

```python
async def get_logger() -> FilteringBoundLogger:
    """Get structured logger instance."""
    global _logger
    resources = current_app_resources()
    if resources is not None:
        return resources.logger
    if _logger is None:
        _logger = configure_logging()
    return _logger


async def get_api_client() -> PubTator3Client:
    """Get PubTator3 API client instance."""
    global _api_client
    resources = current_app_resources()
    if resources is not None:
        return resources.api_client
    if _api_client is None:
        logger_instance = await get_logger()
        _api_client = PubTator3Client(logger=logger_instance)
    return _api_client


async def get_publication_service() -> PublicationService:
    """Get publication service instance."""
    global _publication_service
    resources = current_app_resources()
    if resources is not None:
        return resources.publication_service
    if _publication_service is None:
        client = await get_api_client()
        logger_instance = await get_logger()
        _publication_service = PublicationService(client=client, logger=logger_instance)
    return _publication_service


async def get_publication_passage_service() -> PublicationPassageService:
    """Get compact publication passage service."""
    global _publication_passage_service
    resources = current_app_resources()
    if resources is not None:
        return resources.publication_passage_service
    if _publication_passage_service is None:
        _publication_passage_service = PublicationPassageService(
            publication_service=await get_publication_service()
        )
    return _publication_passage_service


async def get_review_queue() -> ReviewPreparationQueue:
    """Get review preparation queue."""
    global _review_queue
    resources = current_app_resources()
    if resources is not None:
        if resources.review_queue is None:
            raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
        return resources.review_queue
    if _review_queue is None:
        repository = await get_review_repository()
        client = await get_api_client()
        logger_instance = await get_logger()
        preparation = FullTextPreparationService(
            config=review_rerag_config,
            repository=repository,
            pubtator_client=client,
            logger=logger_instance,
        )
        _review_queue = ReviewPreparationQueue(
            config=review_rerag_config,
            repository=repository,
            preparation=preparation,
            logger=logger_instance,
        )
    return _review_queue


async def get_review_context_service() -> ReviewContextService:
    """Get review context retrieval service."""
    global _review_context_service
    resources = current_app_resources()
    if resources is not None:
        if resources.review_context_service is None:
            raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
        return resources.review_context_service
    if _review_context_service is None:
        _review_context_service = ReviewContextService(repository=await get_review_repository())
    return _review_context_service


# Type aliases for dependency injection
LoggerDep = Annotated[FilteringBoundLogger, Depends(get_logger)]
ClientDep = Annotated[PubTator3Client, Depends(get_api_client)]
PublicationServiceDep = Annotated[PublicationService, Depends(get_publication_service)]
PublicationPassageServiceDep = Annotated[
    PublicationPassageService, Depends(get_publication_passage_service)
]
ReviewQueueDep = Annotated[ReviewPreparationQueue, Depends(get_review_queue)]
ReviewContextServiceDep = Annotated[ReviewContextService, Depends(get_review_context_service)]
```

This preserves the existing dependency function objects used by route tests, such as `app.dependency_overrides[get_publication_passage_service] = lambda: service`.

- [ ] **Step 7: Remove stale event-loop suppression from fallback cleanup**

Replace the `_api_client` cleanup block in `cleanup_dependencies()` with:

```python
    if _api_client:
        api_client = _api_client
        _api_client = None
        await api_client.close()
```

- [ ] **Step 8: Update server manager imports**

In `pubtator_link/server_manager.py`, update the standard library import:

```python
from collections.abc import AsyncGenerator, Awaitable, Callable
```

Replace the FastAPI import:

```python
from fastapi import FastAPI
```

with:

```python
from fastapi import FastAPI, Request
from starlette.responses import Response
```

Replace:

```python
from .api.routes.dependencies import cleanup_dependencies, get_review_queue
```

with:

```python
from .api.routes.dependencies import (
    bind_app_resources,
    close_app_resources,
    create_app_resources,
    reset_app_resources,
    resources_from_request,
)
```

Remove these unused imports from `server_manager.py`:

```python
from .api.client import PubTator3Client
from .services.publication_service import PublicationService
```

- [ ] **Step 9: Update server manager instance attributes**

In `UnifiedServerManager.__init__`, remove:

```python
self.client: PubTator3Client | None = None
self.publication_service: PublicationService | None = None
```

Add:

```python
self.resources = None
```

- [ ] **Step 10: Update FastAPI lifespan to own resources**

Replace the body of `UnifiedServerManager.lifespan()` with:

```python
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage FastAPI lifespan context."""
        self.logger.info("Starting PubTator-Link server")

        self.resources = await create_app_resources(logger=self.logger)
        app.state.pubtator_resources = self.resources

        if self.resources.review_queue is not None:
            await self.resources.review_queue.start()

        self.logger.info("Server started successfully")

        try:
            yield
        finally:
            self.logger.info("Shutting down server")
            await close_app_resources(self.resources)
            self.resources = None
            if hasattr(app.state, "pubtator_resources"):
                delattr(app.state, "pubtator_resources")
            self.logger.info("Server shutdown complete")
```

- [ ] **Step 11: Bind app resources during HTTP request handling**

In `UnifiedServerManager.create_app()`, add this middleware after the health route definitions and before router inclusion:

```python
        @app.middleware("http")
        async def bind_pubtator_resources(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            resources = resources_from_request(request)
            token = bind_app_resources(resources)
            try:
                return await call_next(request)
            finally:
                reset_app_resources(token)
```

This middleware binds the app-owned resources for the current request so existing dependency functions can keep their zero-argument signatures and still resolve app-scoped resources.

- [ ] **Step 12: Update server manager shutdown**

Replace the client close block in `UnifiedServerManager.shutdown()`:

```python
        if self.client:
            await self.client.close()
```

with:

```python
        if self.resources is not None:
            await close_app_resources(self.resources)
            self.resources = None
```

- [ ] **Step 13: Run focused tests and verify app resource tests pass**

Run:

```bash
uv run pytest tests/unit/test_route_dependencies.py tests/test_routes/test_health.py tests/test_routes/test_publications.py -q
```

Expected:

```text
passed
```

No pytest-asyncio event-loop deprecation warning should appear.

- [ ] **Step 14: Run mypy for changed package files**

Run:

```bash
uv run mypy pubtator_link/server_manager.py pubtator_link/api/routes/dependencies.py
```

Expected:

```text
Success: no issues found in 2 source files
```

- [ ] **Step 15: Commit app-scoped resource lifecycle**

Run:

```bash
git add pubtator_link/api/routes/dependencies.py pubtator_link/server_manager.py tests/unit/test_route_dependencies.py
git commit -m "refactor: scope app dependencies to lifespan"
```

## Task 4: Enforce Coverage Baseline And Tooling Guardrails

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Add failing tooling tests for coverage and workflow files**

Append these tests to `tests/unit/test_development_tooling.py`:

```python
def test_coverage_threshold_matches_verified_baseline() -> None:
    coverage = _pyproject()["tool"]["coverage"]["report"]

    assert coverage["fail_under"] == 78


def test_github_actions_workflows_exist_and_use_make_targets() -> None:
    ci = Path(".github/workflows/ci.yml").read_text()
    docker = Path(".github/workflows/docker.yml").read_text()
    security = Path(".github/workflows/security.yml").read_text()

    assert "permissions:" in ci
    assert "contents: read" in ci
    assert "uv sync --group dev --frozen" in ci
    assert "make ci-local" in ci
    assert "make test-cov" in ci

    assert "make docker-prod-config" in docker
    assert "make docker-npm-config" in docker
    assert "docker build -f docker/Dockerfile -t pubtator-link:ci ." in docker

    assert "github/codeql-action/init" in security
    assert "actions/dependency-review-action" in security


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
    assert "CodeQL" in docs
```

- [ ] **Step 2: Run tooling tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected before implementation:

```text
FAILED tests/unit/test_development_tooling.py::test_coverage_threshold_matches_verified_baseline
FAILED tests/unit/test_development_tooling.py::test_github_actions_workflows_exist_and_use_make_targets
FAILED tests/unit/test_development_tooling.py::test_pull_request_template_contains_quality_checklist
FAILED tests/unit/test_development_tooling.py::test_branch_protection_docs_define_required_checks
```

- [ ] **Step 3: Add coverage threshold**

In `pyproject.toml`, add `fail_under = 78` under `[tool.coverage.report]`:

```toml
[tool.coverage.report]
fail_under = 78
exclude_lines = [
```

- [ ] **Step 4: Run coverage to verify the threshold passes**

Run:

```bash
make test-cov
```

Expected:

```text
TOTAL
Coverage HTML written to dir htmlcov
passed
```

The command must exit 0.

## Task 5: Add GitHub Actions Workflows

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/docker.yml`
- Create: `.github/workflows/security.yml`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Create CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches:
      - main

permissions:
  contents: read

jobs:
  quality:
    name: Format, lint, typecheck, tests, and coverage
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --group dev --frozen

      - name: Run local CI gate
        run: make ci-local

      - name: Run coverage gate
        run: make test-cov
```

- [ ] **Step 2: Create Docker workflow**

Create `.github/workflows/docker.yml`:

```yaml
name: Docker

on:
  pull_request:
  push:
    branches:
      - main

permissions:
  contents: read

jobs:
  docker:
    name: Docker build and Compose validation
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --group dev --frozen

      - name: Validate production Compose config
        run: make docker-prod-config

      - name: Validate NPM Compose config
        run: make docker-npm-config

      - name: Build Docker image
        run: docker build -f docker/Dockerfile -t pubtator-link:ci .
```

- [ ] **Step 3: Create security workflow**

Create `.github/workflows/security.yml`:

```yaml
name: Security

on:
  pull_request:
  push:
    branches:
      - main
  schedule:
    - cron: "17 3 * * 1"

permissions:
  contents: read
  security-events: write
  pull-requests: read

jobs:
  codeql:
    name: CodeQL
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          languages: python

      - name: Autobuild
        uses: github/codeql-action/autobuild@v3

      - name: Analyze
        uses: github/codeql-action/analyze@v3

  dependency-review:
    name: Dependency review
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    permissions:
      contents: read
      pull-requests: read
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Review dependencies
        uses: actions/dependency-review-action@v4
```

This first workflow version intentionally uses version tags for readability. A follow-up hardening task can pin actions to full-length commit SHAs after maintainers decide on update policy.

- [ ] **Step 4: Run tooling tests again**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected:

```text
FAILED tests/unit/test_development_tooling.py::test_pull_request_template_contains_quality_checklist
FAILED tests/unit/test_development_tooling.py::test_branch_protection_docs_define_required_checks
```

The workflow and coverage tests should pass.

- [ ] **Step 5: Commit coverage and workflows**

Run:

```bash
git add pyproject.toml .github/workflows/ci.yml .github/workflows/docker.yml .github/workflows/security.yml tests/unit/test_development_tooling.py
git commit -m "ci: add foundation quality workflows"
```

## Task 6: Add PR Checklist And Branch Protection Documentation

**Files:**
- Create: `.github/pull_request_template.md`
- Create: `docs/development/branch-protection.md`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Create pull request template**

Create `.github/pull_request_template.md`:

```markdown
## Summary

- 

## Quality Checklist

- [ ] Change is focused and small enough to review.
- [ ] Related tests were added or updated.
- [ ] `make ci-local` passes locally.
- [ ] `make test-cov` passes locally when coverage-relevant code changed.
- [ ] Public REST/MCP behavior changes are documented.
- [ ] New dependencies are justified.
- [ ] New network, file, or database behavior has explicit limits.
- [ ] MCP tools remain research-use scoped and avoid clinical decision support claims.
- [ ] Database changes include schema or integration tests.
```

- [ ] **Step 2: Create branch protection guide**

Create `docs/development/branch-protection.md`:

```markdown
# Branch Protection

Recommended GitHub branch protection for `main`.

## Required Settings

- Require pull request before merging.
- Require approvals before merging.
- Dismiss stale pull request approvals when new commits are pushed.
- Require status checks to pass before merging.
- Require branches to be up to date before merging.

## Required Checks

Enable these checks once the workflows have run at least once:

- `CI / Format, lint, typecheck, tests, and coverage`
- `Docker / Docker build and Compose validation`
- `Security / CodeQL`
- `Security / Dependency review`

The CI workflow runs `make ci-local` and `make test-cov`. The Docker validation workflow runs `make docker-prod-config`, `make docker-npm-config`, and `docker build -f docker/Dockerfile -t pubtator-link:ci .`.

## Optional Settings

- Require linear history if the repository wants squash or rebase-only merges.
- Require conversation resolution before merging.
- Restrict who can push to matching branches.

## Notes

Do not require PostgreSQL integration tests unless the repository has a reliable `PUBTATOR_LINK_TEST_DATABASE_URL` secret and a database service configured in CI. Those tests intentionally skip when the environment variable is absent.
```

- [ ] **Step 3: Run tooling tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected:

```text
18 passed
```

The exact count may be higher if other tooling tests are added before this plan is executed, but there must be no failures.

- [ ] **Step 4: Commit PR and branch protection docs**

Run:

```bash
git add .github/pull_request_template.md docs/development/branch-protection.md tests/unit/test_development_tooling.py
git commit -m "docs: add repository quality gate guidance"
```

## Task 7: Full Local Verification

**Files:**
- Verify all changed files from Tasks 1-6.

- [ ] **Step 1: Run local CI gate**

Run:

```bash
make ci-local
```

Expected:

```text
Success: no issues found
passed
```

The command must exit 0 and must not show pytest-asyncio event-loop deprecation warnings.

- [ ] **Step 2: Run coverage gate**

Run:

```bash
make test-cov
```

Expected:

```text
TOTAL
Coverage HTML written to dir htmlcov
passed
```

The command must exit 0 and coverage must be at least 78%.

- [ ] **Step 3: Validate Docker Compose overlays**

Run:

```bash
make docker-prod-config
make docker-npm-config
```

Expected:

```text
services:
```

Both commands must exit 0.

- [ ] **Step 4: Build Docker image**

Run:

```bash
docker build -f docker/Dockerfile -t pubtator-link:ci .
```

Expected:

```text
Successfully tagged pubtator-link:ci
```

If Docker is unavailable in the execution environment, record that exact blocker in the final handoff and do not claim Docker build verification passed.

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git status --short
git log --oneline -6
```

Expected:

- Only intended files are modified or untracked.
- Recent commits correspond to the task commits in this plan.

- [ ] **Step 6: Final commit for verification notes if needed**

If a verification note file is created, commit it:

```bash
git add docs/superpowers/plans/2026-04-30-foundation-quality-gate-implementation.md
git commit -m "docs: add foundation quality gate implementation plan"
```

If the implementation plan was already committed before execution, skip this step.

## Self-Review Checklist For Implementers

Before final handoff, verify each spec requirement maps to completed work:

- Test lifecycle warnings removed: Task 1 and Task 7.
- App-scoped dependency ownership: Task 2 and Task 3.
- Public REST/MCP behavior unchanged: Task 3 focused dependency aliases and existing route tests.
- Coverage threshold at 78%: Task 4.
- CI workflow: Task 5.
- Docker validation workflow: Task 5 and Task 7.
- Security workflow: Task 5.
- PR checklist and branch protection docs: Task 6.
- PostgreSQL integration tests remain optional: Task 6 docs and Task 7 verification.

Do not mark the plan complete unless `make ci-local` and `make test-cov` have both passed in the current workspace.
