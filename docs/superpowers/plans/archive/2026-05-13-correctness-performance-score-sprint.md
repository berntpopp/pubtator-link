# Correctness Performance Score Sprint Implementation Plan

> **Status:** Completed and merged via PR #37 on 2026-05-13. Archived after the
> merged implementation and Dependabot rollups were verified on `main`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise PubTator-Link above 8/10 by fixing correctness, retry-audit, MCP annotation, and review preparation concurrency defects without broad refactoring.

**Architecture:** Keep the current FastAPI, service, repository, and MCP module boundaries. Make destructive cache endpoints opt-in, remove dead service code, carry retry metadata beside the response that produced it, classify static MCP write annotations accurately, and replace callback-scoped review preparation locking with a short atomic claim transaction.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, asyncpg, httpx, async-lru, pytest, pytest-asyncio, Ruff, mypy, uv, Makefile targets.

---

## File Map

- Modify `pubtator_link/config.py`: change `ServerSettings.enable_cache_endpoints` default to `False`.
- Modify `pubtator_link/server_manager.py`: include `cache_router` only when `settings.enable_cache_endpoints` is true.
- Modify `pubtator_link/api/routes/cache.py`: update cache clear route docs and reject every non-empty `pattern` with HTTP 400.
- Modify `pubtator_link/services/publication_service.py`: make `clear_cache()` return actual current entries cleared; remove `batch_export_publications()` and its unused imports.
- Modify `tests/test_routes/test_cache.py`: opt cache route tests in explicitly; add default-off 404 tests; update unsupported-pattern expectations.
- Modify `tests/test_services.py`: add direct service tests for actual clear counts and service-level pattern rejection.
- Modify `tests/conftest.py`: remove `mock_publication_service.batch_export_publications`.
- Modify `pubtator_link/api/client.py`: add sidecar metadata request path and `export_publications_with_metadata()`.
- Modify `tests/unit/test_pubtator_client_retry.py`: add client retry metadata sidecar tests.
- Modify `pubtator_link/services/full_text_preparation.py`: consume per-call retry metadata sidecars when available and keep the existing fallback for older fakes.
- Modify `tests/unit/test_full_text_preparation.py`: add sidecar retry metadata and concurrency integrity tests.
- Modify `pubtator_link/mcp/annotations.py`: split review write annotations into idempotent and non-idempotent constants.
- Modify `pubtator_link/mcp/tools/review.py`: apply precise annotations to all six review write tools.
- Modify `tests/unit/mcp/test_mcp_facade.py`: assert exact read/write/idempotency semantics for the six review write tools.
- Modify `pubtator_link/repositories/review_rerag.py`: add `claim_preparation_job()`, remove `mark_job_running()` and `with_preparation_lock()` from the protocol and concrete class.
- Modify `pubtator_link/services/review_preparation_queue.py`: claim jobs before preparation and run upstream work outside repository transactions.
- Modify `tests/unit/test_review_preparation_queue.py`: move worker fakes and expectations to the claim model; add claim-skip and concurrency tests.
- Modify `tests/unit/test_review_rerag_repository.py`: replace running/lock tests with claim SQL tests.
- Modify `tests/integration/test_review_schema_postgres.py`: add opt-in PostgreSQL coverage that claims a queued job once when `PUBTATOR_LINK_TEST_DATABASE_URL` is configured.
- Modify `README.md`: document opt-in cache endpoints and `PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=false` default.
- Modify `docs/development/operations-runbook.md`: document cache endpoint exposure and retry metadata audit behavior.
- Modify `CHANGELOG.md`: add Unreleased bullets for the sprint.

## Task 1: Cache Endpoint Gating And Honest Clear Semantics

**Files:**
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/server_manager.py`
- Modify: `pubtator_link/api/routes/cache.py`
- Modify: `pubtator_link/services/publication_service.py`
- Modify: `tests/test_routes/test_cache.py`
- Modify: `tests/test_services.py`

- [ ] **Step 1: Add failing route tests for default-off cache endpoints**

In `tests/test_routes/test_cache.py`, replace the local `test_client` fixture with explicit opt-in and opt-out fixtures:

```python
@pytest.fixture
def cache_disabled_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("pubtator_link.server_manager.settings.enable_cache_endpoints", False)
    manager = UnifiedServerManager()
    return TestClient(manager.create_app())


@pytest.fixture
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("pubtator_link.server_manager.settings.enable_cache_endpoints", True)
    manager = UnifiedServerManager()
    return TestClient(manager.create_app())
```

Add these tests near the top of `TestCacheRoutes`:

```python
def test_cache_endpoints_are_absent_when_flag_disabled(
    self,
    cache_disabled_client: TestClient,
) -> None:
    stats_response = cache_disabled_client.get("/api/cache/stats")
    clear_response = cache_disabled_client.delete("/api/cache/clear")

    assert stats_response.status_code == 404
    assert clear_response.status_code == 404
    assert stats_response.json()["detail"] == "Not Found"
    assert clear_response.json()["detail"] == "Not Found"


def test_cache_endpoints_are_exposed_when_flag_enabled(self, test_client: TestClient) -> None:
    response = test_client.get("/api/cache/stats")

    assert response.status_code == 200
    assert response.json()["success"] is True
```

Run: `uv run pytest tests/test_routes/test_cache.py::TestCacheRoutes::test_cache_endpoints_are_absent_when_flag_disabled -q`

Expected: FAIL because `server_manager.create_app()` mounts `cache_router` unconditionally.

- [ ] **Step 2: Add failing route tests for unsupported non-empty patterns**

In `tests/test_routes/test_cache.py`, replace the pattern-specific success tests with these exact expectations:

```python
def test_clear_cache_rejects_known_pattern(self, test_client: TestClient) -> None:
    response = test_client.delete("/api/cache/clear", params={"pattern": "pub_export:*"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Pattern-based cache clearing is not supported."


def test_clear_cache_rejects_unknown_pattern(self, test_client: TestClient) -> None:
    response = test_client.delete("/api/cache/clear", params={"pattern": "unknown:*"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Pattern-based cache clearing is not supported."


def test_clear_cache_rejects_whitespace_pattern(self, test_client: TestClient) -> None:
    response = test_client.delete("/api/cache/clear", params={"pattern": "  pub_export:*  "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Pattern-based cache clearing is not supported."
```

Keep `test_clear_cache_empty_pattern`, but change its expected detail to the same message because an empty query string value is still a provided non-`None` pattern:

```python
assert response.status_code == 400
assert response.json()["detail"] == "Pattern-based cache clearing is not supported."
```

Remove these obsolete tests from `tests/test_routes/test_cache.py` because they assert misleading scoped clear behavior:

```python
def test_clear_cache_with_pattern(...)
def test_clear_cache_specific_patterns(...)
def test_clear_cache_wildcard_pattern(...)
def test_clear_cache_nonexistent_pattern(...)
```

Run: `uv run pytest tests/test_routes/test_cache.py::TestCacheRoutes::test_clear_cache_rejects_known_pattern tests/test_routes/test_cache.py::TestCacheRoutes::test_clear_cache_rejects_unknown_pattern -q`

Expected: FAIL because the route currently accepts patterns and clears all caches.

- [ ] **Step 3: Add failing service test for actual clear count**

In `tests/test_services.py`, add this method to `TestPublicationService`:

```python
@pytest.mark.asyncio
async def test_clear_cache_returns_actual_current_entry_count(
    self,
    publication_service: PublicationService,
    mock_client: Mock,
) -> None:
    mock_client.export_publications.return_value = {"documents": [{"id": "1"}]}
    mock_client.export_pmc_publications.return_value = {"documents": [{"id": "PMC1"}]}
    mock_client.search_publications.return_value = {"results": [], "total": 0, "per_page": 20}

    await publication_service.export_publications("1", format="biocjson", full=False)
    await publication_service.export_pmc_publications("PMC1", format="biocjson")
    await publication_service.search_publications("colchicine", page=1)

    cleared = await publication_service.clear_cache()

    assert cleared == 3
    assert publication_service.get_cache_stats()["current_size"] == 0
```

Add this service-boundary test in the same class:

```python
@pytest.mark.asyncio
async def test_clear_cache_rejects_pattern_at_service_boundary(
    self,
    publication_service: PublicationService,
) -> None:
    with pytest.raises(
        ValueError,
        match="Pattern-based cache clearing is not supported.",
    ):
        await publication_service.clear_cache(pattern="pub_export:*")
```

Run: `uv run pytest tests/test_services.py::TestPublicationService::test_clear_cache_returns_actual_current_entry_count tests/test_services.py::TestPublicationService::test_clear_cache_rejects_pattern_at_service_boundary -q`

Expected: FAIL because `PublicationService.clear_cache()` returns `cache_config.size`, not the actual current cache entry count, and currently ignores `pattern`.

- [ ] **Step 4: Gate cache router behind the feature flag**

In `pubtator_link/config.py`, change the feature flag default:

```python
enable_cache_endpoints: bool = Field(
    default=False, description="Enable opt-in cache management endpoints"
)
```

In `pubtator_link/server_manager.py`, change the route inclusion block to:

```python
app.include_router(publications_router)
app.include_router(entities_router)
app.include_router(search_router)
app.include_router(relations_router)
app.include_router(discovery_router)
app.include_router(annotations_router)
if settings.enable_cache_endpoints:
    app.include_router(cache_router)
app.include_router(reviews_router)
app.include_router(variants_router)
```

Run: `uv run pytest tests/test_routes/test_cache.py::TestCacheRoutes::test_cache_endpoints_are_absent_when_flag_disabled tests/test_routes/test_cache.py::TestCacheRoutes::test_cache_endpoints_are_exposed_when_flag_enabled -q`

Expected: PASS.

- [ ] **Step 5: Reject every non-empty or empty-string pattern honestly**

In `pubtator_link/api/routes/cache.py`, update the delete route metadata:

```python
summary="Clear all caches",
description=(
    "Clear all server-side async-lru publication caches. Pattern-based clearing "
    "is not supported."
),
```

Change the `pattern` query description to:

```python
description="Unsupported. Any supplied pattern returns HTTP 400.",
```

At the start of `clear_cache()`, replace the current pattern validation block with:

```python
if pattern is not None:
    raise HTTPException(
        status_code=400,
        detail="Pattern-based cache clearing is not supported.",
    )
```

Set the success message unconditionally:

```python
message = "All cached items cleared successfully"
```

Run: `uv run pytest tests/test_routes/test_cache.py::TestCacheRoutes::test_clear_cache_rejects_known_pattern tests/test_routes/test_cache.py::TestCacheRoutes::test_clear_cache_rejects_unknown_pattern tests/test_routes/test_cache.py::TestCacheRoutes::test_clear_cache_empty_pattern -q`

Expected: PASS.

- [ ] **Step 6: Return actual cache entries cleared**

In `pubtator_link/services/publication_service.py`, replace `clear_cache()` with:

```python
async def clear_cache(self, pattern: str | None = None) -> int:
    """Clear all async-lru cache entries and return the actual number cleared."""
    if pattern is not None:
        raise ValueError("Pattern-based cache clearing is not supported.")

    cache_infos = [
        self.export_publications.cache_info(),
        self.export_pmc_publications.cache_info(),
        self.search_publications.cache_info(),
    ]
    cleared_items = sum(info.currsize for info in cache_infos)

    self.export_publications.cache_clear()
    self.export_pmc_publications.cache_clear()
    self.search_publications.cache_clear()

    if self.logger:
        self.logger.info("Cache cleared", cleared_items=cleared_items)

    return cleared_items
```

Run: `uv run pytest tests/test_services.py::TestPublicationService::test_clear_cache_returns_actual_current_entry_count tests/test_services.py::TestPublicationService::test_clear_cache_rejects_pattern_at_service_boundary tests/test_routes/test_cache.py -q`

Expected: PASS.

- [ ] **Step 7: Commit cache endpoint work**

```bash
git add pubtator_link/config.py pubtator_link/server_manager.py pubtator_link/api/routes/cache.py pubtator_link/services/publication_service.py tests/test_routes/test_cache.py tests/test_services.py
git commit -m "fix: gate cache endpoints and clarify clearing"
```

## Task 2: Dead Batch Export Removal

**Files:**
- Modify: `pubtator_link/services/publication_service.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Verify the dead helper exists and is uncalled**

Run: `rg -n "batch_export_publications\\(" pubtator_link tests`

Expected current output before this task:

```text
pubtator_link/services/publication_service.py:183:    async def batch_export_publications(
tests/conftest.py:79:    service.batch_export_publications = AsyncMock()
```

The helper has no production or test call site outside its own definition and one mock attribute.

- [ ] **Step 2: Remove the helper and dead imports**

In `pubtator_link/services/publication_service.py`, remove:

```python
import asyncio
```

Remove `PublicationBatch` from the `pubtator_link.models.publications` import list.

Delete the full `async def batch_export_publications(...) -> PublicationBatch:` method.

In `tests/conftest.py`, remove:

```python
service.batch_export_publications = AsyncMock()
```

Do not remove `PublicationBatch` from `pubtator_link/models/publications.py` in this sprint because this task targets the broken unexposed helper, not model API cleanup.

- [ ] **Step 3: Verify no helper references remain**

Run: `rg -n "batch_export_publications\\(" pubtator_link tests`

Expected: command exits with no matches.

Run: `uv run pytest tests/test_services.py -q`

Expected: PASS.

Run: `make typecheck-fast`

Expected: PASS.

- [ ] **Step 4: Commit dead helper removal**

```bash
git add pubtator_link/services/publication_service.py tests/conftest.py
git commit -m "fix: remove dead batch publication export helper"
```

## Task 3: Retry Metadata Sidecar Integrity

**Files:**
- Modify: `pubtator_link/api/client.py`
- Modify: `tests/unit/test_pubtator_client_retry.py`
- Modify: `pubtator_link/services/full_text_preparation.py`
- Modify: `tests/unit/test_full_text_preparation.py`

- [ ] **Step 1: Add failing client test for successful retry metadata sidecar**

In `tests/unit/test_pubtator_client_retry.py`, add:

```python
@pytest.mark.asyncio
async def test_export_publications_with_metadata_reports_retry_attempts() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request, text="busy")
        return httpx.Response(200, request=request, json={"documents": []})

    client = _client_with_transports(httpx.MockTransport(handler))
    try:
        payload, metadata = await client.export_publications_with_metadata(
            ["40234174"],
            format="biocjson",
            full=False,
        )
    finally:
        await client.close()

    assert payload == {"documents": []}
    assert len(requests) == 2
    assert metadata.attempt_count == 2
    assert metadata.last_status_code == 200
    assert metadata.terminal_reason is None
```

Run: `uv run pytest tests/unit/test_pubtator_client_retry.py::test_export_publications_with_metadata_reports_retry_attempts -q`

Expected: FAIL because `PubTator3Client.export_publications_with_metadata()` does not exist.

- [ ] **Step 2: Add failing client tests for terminal retry and non-retried POST metadata**

In `tests/unit/test_pubtator_client_retry.py`, add:

```python
@pytest.mark.asyncio
async def test_export_publications_with_metadata_attaches_retry_exhausted_to_error() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request, json={"error": "busy"})

    client = _client_with_transports(httpx.MockTransport(handler))
    try:
        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications_with_metadata(["40234174"], format="biocjson")
    finally:
        await client.close()

    assert len(requests) == 3
    metadata = exc_info.value.response_data["retry_metadata"]
    assert metadata["attempt_count"] == 3
    assert metadata["last_status_code"] == 503
    assert metadata["terminal_reason"] == "retry_exhausted"


@pytest.mark.asyncio
async def test_sidecar_request_metadata_records_single_post_attempt() -> None:
    async def text_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            text="SESSION-1",
            headers={"content-type": "text/plain"},
        )

    client = _client_with_transports(
        httpx.MockTransport(lambda request: httpx.Response(200, request=request, json={})),
        text_transport=httpx.MockTransport(text_handler),
    )
    try:
        payload, metadata = await client._make_request_with_metadata(
            "POST",
            "https://text.example.test/request.cgi",
            data={"text": "MEFV evidence", "bioconcept": "Gene"},
            use_text_client=True,
            retry=False,
        )
    finally:
        await client.close()

    assert payload == {"content": "SESSION-1", "content_type": "text/plain"}
    assert metadata.attempt_count == 1
    assert metadata.last_status_code == 200
    assert metadata.terminal_reason is None
```

Run: `uv run pytest tests/unit/test_pubtator_client_retry.py::test_export_publications_with_metadata_attaches_retry_exhausted_to_error tests/unit/test_pubtator_client_retry.py::test_sidecar_request_metadata_records_single_post_attempt -q`

Expected: FAIL because the sidecar request path does not exist.

- [ ] **Step 3: Implement sidecar request path in the client**

In `pubtator_link/api/client.py`, change the retry import to:

```python
from .retry import RetryAttemptMetadata, RetryPolicy, call_with_retries
```

Add this helper near `PubTatorAPIError` or as a private module function:

```python
def _retry_metadata_payload(metadata: RetryAttemptMetadata) -> dict[str, Any]:
    return {
        "attempt_count": metadata.attempt_count,
        "last_status_code": metadata.last_status_code,
        "retry_after_ms": metadata.retry_after_ms,
        "backoff_ms": metadata.backoff_ms,
        "terminal_reason": metadata.terminal_reason,
    }
```

Add this method to `PubTator3Client` and move the body of `_make_request()` into it:

```python
async def _make_request_with_metadata(
    self,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    use_text_client: bool = False,
    retry: bool = True,
) -> tuple[dict[str, Any], RetryAttemptMetadata]:
    wait_time = await self.rate_limiter.acquire()
    if wait_time > 0 and self.logger:
        log_rate_limit_event(self.logger, endpoint=url, wait_time=wait_time)

    client = self.text_client if use_text_client else self.client
    start_time = time.time()
    policy = RetryPolicy()

    try:
        method_upper = method.upper()
        if method_upper not in {"GET", "POST"}:
            raise ValueError(f"Unsupported HTTP method: {method}")

        async def send() -> httpx.Response:
            if method_upper == "GET":
                return await client.get(url, params=params)
            return await client.post(url, params=params, data=data)

        if retry and method_upper == "GET":
            try:
                response, retry_metadata = await call_with_retries(send, policy=policy)
            except httpx.RequestError as exc:
                retry_metadata = RetryAttemptMetadata(
                    attempt_count=policy.max_attempts,
                    terminal_reason="request_error",
                )
                raise PubTatorAPIError(
                    f"Request failed: {exc!s}",
                    response_data={"retry_metadata": _retry_metadata_payload(retry_metadata)},
                ) from exc
        else:
            try:
                response = await send()
            except httpx.RequestError as exc:
                retry_metadata = RetryAttemptMetadata(
                    attempt_count=1,
                    terminal_reason="request_error",
                )
                raise PubTatorAPIError(
                    f"Request failed: {exc!s}",
                    response_data={"retry_metadata": _retry_metadata_payload(retry_metadata)},
                ) from exc
            retry_metadata = RetryAttemptMetadata(
                attempt_count=1,
                last_status_code=response.status_code,
            )

        response_time = time.time() - start_time
        if self.logger:
            log_api_request(
                self.logger,
                method=method_upper,
                url=str(response.url),
                response_time=response_time,
                status_code=response.status_code,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error_data: dict[str, Any] = {}
            try:
                parsed_error = exc.response.json()
                if isinstance(parsed_error, dict):
                    error_data.update(parsed_error)
            except Exception:
                if self.logger:
                    self.logger.warning("Failed to parse error response as JSON")
            error_data["retry_metadata"] = _retry_metadata_payload(retry_metadata)
            raise PubTatorAPIError(
                f"HTTP {exc.response.status_code}: {exc.response.text}",
                status_code=exc.response.status_code,
                response_data=error_data,
            ) from exc

        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            payload = response.json()
        elif (
            "text/plain" in content_type
            or "text/html" in content_type
            or "application/xml" in content_type
        ):
            payload = {"content": response.text, "content_type": content_type}
        else:
            payload = {"content": response.content, "content_type": content_type}

        return payload, retry_metadata

    except PubTatorAPIError:
        raise
```

Replace `_make_request()` with a delegating wrapper:

```python
async def _make_request(
    self,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    use_text_client: bool = False,
    retry: bool = True,
) -> dict[str, Any]:
    payload, _metadata = await self._make_request_with_metadata(
        method,
        url,
        params=params,
        data=data,
        use_text_client=use_text_client,
        retry=retry,
    )
    return payload
```

Run: `uv run pytest tests/unit/test_pubtator_client_retry.py::test_sidecar_request_metadata_records_single_post_attempt -q`

Expected: PASS.

- [ ] **Step 4: Add publication export sidecar method**

In `pubtator_link/api/client.py`, add:

```python
async def export_publications_with_metadata(
    self, pmids: list[str], format: str = "biocjson", full: bool = False
) -> tuple[dict[str, Any], RetryAttemptMetadata]:
    if format not in self.config.export_formats:
        raise ValueError(f"Unsupported format: {format}")

    if full and format == "pubtator":
        raise ValueError("Full text not supported for pubtator format")

    url = f"{self.config.base_url}/publications/export/{format}"
    params = {"pmids": ",".join(pmids)}
    if full:
        params["full"] = "true"

    return await self._make_request_with_metadata("GET", url, params=params)
```

Replace `export_publications()` body after validation with:

```python
payload, _metadata = await self.export_publications_with_metadata(pmids, format, full)
return payload
```

Run: `uv run pytest tests/unit/test_pubtator_client_retry.py -q`

Expected: PASS.

- [ ] **Step 5: Add failing full-text preparation sidecar tests**

In `tests/unit/test_full_text_preparation.py`, add this fake:

```python
class SidecarPubTatorClient:
    def __init__(self, responses: dict[str, tuple[dict[str, Any], dict[str, Any]]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def export_publications_with_metadata(
        self,
        pmids: list[str],
        format: str = "biocjson",
        full: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        pmid = pmids[0]
        self.calls.append({"pmids": pmids, "format": format, "full": full})
        return self.responses[pmid]

    async def export_publications(
        self,
        pmids: list[str],
        format: str = "biocjson",
        full: bool = False,
    ) -> dict[str, Any]:
        raise AssertionError("sidecar clients should not use shared mutable retry state")
```

Add this test:

```python
@pytest.mark.asyncio
async def test_prepare_pmid_records_sidecar_retry_metadata() -> None:
    repository = RecordingRepository()
    client = SidecarPubTatorClient(
        {
            "40234174": (
                {
                    "documents": [
                        {
                            "id": "40234174",
                            "pmid": "40234174",
                            "passages": [
                                {"infons": {"type": "abstract"}, "text": "Evidence passage."}
                            ],
                        }
                    ]
                },
                {"attempt_count": 2, "last_status_code": 200, "backoff_ms": 125},
            )
        }
    )
    service = FullTextPreparationService(
        config=_config(),
        repository=repository,
        pubtator_client=client,
    )

    status = await service.prepare_pmid("review-1", "40234174")

    assert status == "complete"
    assert repository.attempts[0]["attempt_count"] == 2
    assert repository.attempts[0]["last_status_code"] == 200
    assert repository.attempts[0]["backoff_ms"] == 125
```

Add this concurrency integrity test:

```python
@pytest.mark.asyncio
async def test_prepare_pmid_sidecar_metadata_is_not_overwritten_between_concurrent_jobs() -> None:
    repository = RecordingRepository()
    client = SidecarPubTatorClient(
        {
            "111": (
                {
                    "documents": [
                        {
                            "id": "111",
                            "pmid": "111",
                            "passages": [{"infons": {"type": "abstract"}, "text": "First."}],
                        }
                    ]
                },
                {"attempt_count": 1, "last_status_code": 200},
            ),
            "222": (
                {
                    "documents": [
                        {
                            "id": "222",
                            "pmid": "222",
                            "passages": [{"infons": {"type": "abstract"}, "text": "Second."}],
                        }
                    ]
                },
                {"attempt_count": 3, "last_status_code": 200, "retry_after_ms": 1000},
            ),
        }
    )
    service = FullTextPreparationService(
        config=_config(),
        repository=repository,
        pubtator_client=client,
    )

    await asyncio.gather(
        service.prepare_pmid("review-1", "111"),
        service.prepare_pmid("review-1", "222"),
    )

    attempts_by_source = {attempt["source_id"]: attempt for attempt in repository.attempts}
    assert attempts_by_source["PMID:111"]["attempt_count"] == 1
    assert attempts_by_source["PMID:222"]["attempt_count"] == 3
    assert attempts_by_source["PMID:222"]["retry_after_ms"] == 1000
```

Add `import asyncio` at the top of the file.

Run: `uv run pytest tests/unit/test_full_text_preparation.py::test_prepare_pmid_records_sidecar_retry_metadata tests/unit/test_full_text_preparation.py::test_prepare_pmid_sidecar_metadata_is_not_overwritten_between_concurrent_jobs -q`

Expected: FAIL because `FullTextPreparationService.prepare_pmid()` still calls `export_publications()` and `_last_retry_metadata()`.

- [ ] **Step 6: Consume sidecar metadata in full-text preparation**

In `pubtator_link/services/full_text_preparation.py`, add:

```python
def _retry_metadata_dict(self, metadata: Any) -> dict[str, Any]:
    if metadata is None:
        return {}
    if hasattr(metadata, "__dict__"):
        return dict(metadata.__dict__)
    return dict(metadata)

async def _export_publications_with_retry_metadata(
    self,
    pmids: list[str],
    *,
    format: str,
    full: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    export_with_metadata = getattr(
        self.pubtator_client,
        "export_publications_with_metadata",
        None,
    )
    if export_with_metadata is not None:
        payload, metadata = await export_with_metadata(pmids, format=format, full=full)
        return payload, self._retry_metadata_dict(metadata)

    payload = await self.pubtator_client.export_publications(pmids, format=format, full=full)
    return payload, self._last_retry_metadata()
```

Change the full-text export call in `prepare_pmid()` to:

```python
full_data, full_retry_metadata = await self._export_publications_with_retry_metadata(
    [pmid],
    format="biocjson",
    full=True,
)
```

Change the abstract export call to:

```python
abstract_data, abstract_retry_metadata = await self._export_publications_with_retry_metadata(
    [pmid],
    format="biocjson",
    full=False,
)
```

Update `_last_retry_metadata()` to delegate conversion:

```python
def _last_retry_metadata(self) -> dict[str, Any]:
    return self._retry_metadata_dict(getattr(self.pubtator_client, "last_retry_metadata", None))
```

Run: `uv run pytest tests/unit/test_pubtator_client_retry.py tests/unit/test_full_text_preparation.py -q`

Expected: PASS.

- [ ] **Step 7: Commit retry metadata work**

```bash
git add pubtator_link/api/client.py pubtator_link/services/full_text_preparation.py tests/unit/test_pubtator_client_retry.py tests/unit/test_full_text_preparation.py
git commit -m "fix: carry PubTator retry metadata with exports"
```

## Task 4: MCP Review Write Idempotency Annotation Fixes

**Files:**
- Modify: `pubtator_link/mcp/annotations.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add failing exact annotation test for all six review write tools**

In `tests/unit/mcp/test_mcp_facade.py`, replace `test_write_capable_mcp_tools_include_audit_export_annotations()` with:

```python
def test_write_capable_mcp_tools_have_precise_annotations() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp(profile="full")
    tools = mcp._tool_manager._tools

    annotation_submit = tools["pubtator_submit_text_annotation"].annotations
    assert annotation_submit.readOnlyHint is False
    assert annotation_submit.destructiveHint is False
    assert annotation_submit.idempotentHint is False
    assert annotation_submit.openWorldHint is True

    expected_review_writes = {
        "pubtator_add_evidence_certainty": False,
        "pubtator_stage_research_session": False,
        "pubtator_review_quickstart": False,
        "pubtator_record_review_context": False,
        "pubtator_index_review_evidence": True,
        "pubtator_ground_question": True,
    }
    for name, expected_idempotent in expected_review_writes.items():
        annotations = tools[name].annotations
        assert annotations.readOnlyHint is False, name
        assert annotations.destructiveHint is False, name
        assert annotations.idempotentHint is expected_idempotent, name
        assert annotations.openWorldHint is True, name

    audit_export = tools["pubtator_export_review_audit_bundle"].annotations
    assert audit_export.readOnlyHint is False
    assert audit_export.destructiveHint is False
    assert audit_export.idempotentHint is False
    assert audit_export.openWorldHint is True
```

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_write_capable_mcp_tools_have_precise_annotations -q`

Expected: FAIL because every review write currently uses `REVIEW_WRITE_ANNOTATIONS` with `idempotentHint=True`.

- [ ] **Step 2: Split review write annotation constants**

In `pubtator_link/mcp/annotations.py`, replace `REVIEW_WRITE_ANNOTATIONS` with:

```python
IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
```

- [ ] **Step 3: Apply precise annotations to review tools**

In `pubtator_link/mcp/tools/review.py`, change the import to:

```python
from pubtator_link.mcp.annotations import (
    FILE_EXPORT_ANNOTATIONS,
    IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
)
```

Use `NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS` for:

```python
pubtator_add_evidence_certainty
pubtator_stage_research_session
pubtator_review_quickstart
pubtator_record_review_context
```

Use `IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS` for:

```python
pubtator_index_review_evidence
pubtator_ground_question
```

Do not add dynamic per-argument annotations.

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_write_capable_mcp_tools_have_precise_annotations tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: PASS.

- [ ] **Step 4: Commit MCP annotation work**

```bash
git add pubtator_link/mcp/annotations.py pubtator_link/mcp/tools/review.py tests/unit/mcp/test_mcp_facade.py
git commit -m "fix: classify review write idempotency annotations"
```

## Task 5: Review Preparation Atomic Claim Model And Concurrency Tests

**Files:**
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/services/review_preparation_queue.py`
- Modify: `tests/unit/test_review_preparation_queue.py`
- Modify: `tests/unit/test_review_rerag_repository.py`
- Modify: `tests/integration/test_review_schema_postgres.py`

- [ ] **Step 1: Add failing worker claim-order and skip tests**

In `tests/unit/test_review_preparation_queue.py`, change `WorkerRepository` to the claim contract:

```python
class WorkerRepository(RecordingRepository):
    def __init__(self) -> None:
        super().__init__()
        self.claim_results: list[bool] = [True]
        self.claims: list[tuple[str, str]] = []
        self.finished: list[tuple[str, str, str, str | None]] = []
        self.attempts: list[tuple[str, str, str, str, str | None]] = []

    async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
        self.claims.append((review_id, source_id))
        return self.claim_results.pop(0) if self.claim_results else True

    async def mark_job_finished(
        self, *, review_id: str, source_id: str, status: str, error: str | None
    ) -> None:
        self.finished.append((review_id, source_id, status, error))

    async def record_retrieval_attempt(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        *,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.attempts.append((review_id, source_id, source_kind, status, reason))
```

Add these tests:

```python
@pytest.mark.asyncio
async def test_worker_skips_preparation_when_claim_returns_false() -> None:
    repository = WorkerRepository()
    repository.claim_results = [False]
    preparation = RecordingPreparation()
    preparation.calls = []

    async def recording_prepare_pmid(review_id: str, pmid: str) -> str:
        preparation.calls.append((review_id, pmid))
        return "complete"

    preparation.prepare_pmid = recording_prepare_pmid
    queue = ReviewPreparationQueue(config=_config(), repository=repository, preparation=preparation)

    await queue.start()
    try:
        assert await queue.enqueue_pmid("review-1", "40234174") == "newly_queued"
        await asyncio.wait_for(queue._queue.join(), timeout=2)
    finally:
        await queue.stop()

    assert repository.claims == [("review-1", "PMID:40234174")]
    assert preparation.calls == []
    assert repository.finished == []


@pytest.mark.asyncio
async def test_worker_starts_preparation_after_claim_completes() -> None:
    events: list[str] = []

    class ClaimTrackingRepository(WorkerRepository):
        transaction_open = False

        async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
            events.append("claim_begin")
            self.transaction_open = True
            await asyncio.sleep(0)
            self.transaction_open = False
            events.append("claim_committed")
            return True

    class AssertingPreparation(RecordingPreparation):
        async def prepare_pmid(self, review_id: str, pmid: str) -> str:
            assert repository.transaction_open is False
            events.append("prepare_started")
            return "complete"

    repository = ClaimTrackingRepository()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=AssertingPreparation(),
    )

    await queue.start()
    try:
        assert await queue.enqueue_pmid("review-1", "40234174") == "newly_queued"
        await asyncio.wait_for(queue._queue.join(), timeout=2)
    finally:
        await queue.stop()

    assert events == ["claim_begin", "claim_committed", "prepare_started"]
    assert repository.finished == [("review-1", "PMID:40234174", "complete", None)]
```

Run: `uv run pytest tests/unit/test_review_preparation_queue.py::test_worker_skips_preparation_when_claim_returns_false tests/unit/test_review_preparation_queue.py::test_worker_starts_preparation_after_claim_completes -q`

Expected: FAIL because the worker still calls `mark_job_running()` and `with_preparation_lock()`.

- [ ] **Step 2: Add failing worker concurrency test**

In `tests/unit/test_review_preparation_queue.py`, add:

```python
@pytest.mark.asyncio
async def test_two_slow_preparation_jobs_run_concurrently_with_two_workers() -> None:
    started: list[str] = []
    release = asyncio.Event()

    class BlockingPreparation(RecordingPreparation):
        async def prepare_pmid(self, review_id: str, pmid: str) -> str:
            started.append(pmid)
            if len(started) == 2:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=2)
            return "complete"

    repository = WorkerRepository()
    repository.claim_results = [True, True]
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=BlockingPreparation(),
    )

    await queue.start()
    try:
        assert await queue.enqueue_pmid("review-1", "111") == "newly_queued"
        assert await queue.enqueue_pmid("review-1", "222") == "newly_queued"
        await asyncio.wait_for(queue._queue.join(), timeout=2)
    finally:
        await queue.stop()

    assert set(started) == {"111", "222"}
    assert sorted(repository.finished) == [
        ("review-1", "PMID:111", "complete", None),
        ("review-1", "PMID:222", "complete", None),
    ]
```

Run: `uv run pytest tests/unit/test_review_preparation_queue.py::test_two_slow_preparation_jobs_run_concurrently_with_two_workers -q`

Expected: FAIL until the worker uses the claim model and the fake supports the new contract.

- [ ] **Step 3: Add failing repository tests for atomic claim SQL**

In `tests/unit/test_review_rerag_repository.py`, replace `test_job_status_methods_execute_expected_sql()` and `test_advisory_lock_wraps_preparation_callback()` with:

```python
@pytest.mark.asyncio
async def test_claim_preparation_job_claims_queued_job_with_short_advisory_lock() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [{"job_id": "job-1"}]
    repository = PostgresReviewReragRepository(FakePool(connection))

    claimed = await repository.claim_preparation_job(
        review_id="review-1",
        source_id="PMID:40234174",
    )

    assert claimed is True
    assert connection.transaction_calls == [{}]
    lock_sql, lock_args = connection.executed[0]
    assert "pg_advisory_xact_lock" in lock_sql
    assert lock_args == ("review-1:PMID:40234174",)
    claim_sql, claim_args = connection.executed[1]
    normalized_sql = " ".join(claim_sql.lower().split())
    assert "update review_preparation_jobs" in normalized_sql
    assert "set status = 'running'" in normalized_sql
    assert "error = null" in normalized_sql
    assert "where review_id = $1 and source_id = $2 and status = 'queued'" in normalized_sql
    assert "returning job_id" in normalized_sql
    assert claim_args == ("review-1", "PMID:40234174")


@pytest.mark.asyncio
async def test_claim_preparation_job_returns_false_when_job_is_not_queued() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [None]
    repository = PostgresReviewReragRepository(FakePool(connection))

    claimed = await repository.claim_preparation_job(
        review_id="review-1",
        source_id="PMID:40234174",
    )

    assert claimed is False
    assert connection.transaction_calls == [{}]
    assert len(connection.executed) == 2
```

Run: `uv run pytest tests/unit/test_review_rerag_repository.py::test_claim_preparation_job_claims_queued_job_with_short_advisory_lock tests/unit/test_review_rerag_repository.py::test_claim_preparation_job_returns_false_when_job_is_not_queued -q`

Expected: FAIL because `claim_preparation_job()` does not exist.

- [ ] **Step 4: Add opt-in PostgreSQL integration test for claim-once behavior**

In `tests/integration/test_review_schema_postgres.py`, add:

```python
@pytest.mark.asyncio
async def test_claim_preparation_job_claims_queued_job_once_in_postgres() -> None:
    database_url = os.getenv("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL is not set")

    schema = Path("pubtator_link/db/review_schema.sql").read_text()
    conn = await _connect_or_skip(database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        await conn.execute(schema)
        await conn.execute(
            """
            delete from review_passages;
            delete from full_text_retrieval_attempts;
            delete from review_preparation_jobs;
            delete from reviews;
            """
        )
        repository = PostgresReviewReragRepository(pool)
        await repository.enqueue_preparation_job(
            "review-claim",
            "PMID:40234174",
            "pubtator_full_bioc",
        )

        first_claim = await repository.claim_preparation_job(
            review_id="review-claim",
            source_id="PMID:40234174",
        )
        second_claim = await repository.claim_preparation_job(
            review_id="review-claim",
            source_id="PMID:40234174",
        )
        statuses = await repository.preparation_job_statuses(
            "review-claim",
            ["PMID:40234174"],
        )
    finally:
        await pool.close()
        await conn.close()

    assert first_claim is True
    assert second_claim is False
    assert statuses == {"PMID:40234174": "running"}
```

Run: `uv run pytest tests/integration/test_review_schema_postgres.py::test_claim_preparation_job_claims_queued_job_once_in_postgres -q`

Expected: SKIP when `PUBTATOR_LINK_TEST_DATABASE_URL` is unset. When the environment variable points at a reachable test PostgreSQL database before implementation, FAIL because `claim_preparation_job()` does not exist.

- [ ] **Step 5: Add claim method to repository protocol and concrete class**

In `pubtator_link/repositories/review_rerag.py`, remove these imports:

```python
Awaitable
Callable
```

In `ReviewReragRepository`, add:

```python
async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
    """Atomically claim one queued preparation job for this worker."""
```

Remove these protocol methods:

```python
async def mark_job_running(...)
async def with_preparation_lock(...)
```

In `PostgresReviewReragRepository`, delete `mark_job_running()` and `with_preparation_lock()`.

Add:

```python
async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
    async with self._acquire() as connection, connection.transaction():
        await connection.execute(
            "select pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"{review_id}:{source_id}",
        )
        row = await connection.fetchrow(
            """
            update review_preparation_jobs
            set status = 'running',
                started_at = now(),
                error = null,
                updated_at = now()
            where review_id = $1
              and source_id = $2
              and status = 'queued'
            returning job_id
            """,
            review_id,
            source_id,
        )
        if row is None:
            return False
        await self._touch_review_on_connection(connection, review_id)
        return True
```

Run: `uv run pytest tests/unit/test_review_rerag_repository.py::test_claim_preparation_job_claims_queued_job_with_short_advisory_lock tests/unit/test_review_rerag_repository.py::test_claim_preparation_job_returns_false_when_job_is_not_queued -q`

Expected: PASS.

- [ ] **Step 6: Move queue worker to claim model**

In `pubtator_link/services/review_preparation_queue.py`, inside `_worker()`, replace `mark_job_running()` and `with_preparation_lock()` with:

```python
claimed = False
try:
    self.logger.info(...)
    claimed = await self.repository.claim_preparation_job(
        review_id=review_id,
        source_id=source_id,
    )
    if not claimed:
        self.logger.info(
            "Review preparation job skipped because it was not claimable",
            extra={
                "review_id": review_id,
                "source_id": source_id,
                "source_kind": source_kind,
            },
        )
        continue

    if source_kind == "pubtator_full_bioc":
        result = await asyncio.wait_for(
            self.preparation.prepare_pmid(review_id, source_value),
            timeout=self.config.document_timeout_seconds,
        )
    elif source_kind == "curated_pdf":
        result = await asyncio.wait_for(
            self.preparation.prepare_curated_url(review_id, source_value),
            timeout=self.config.document_timeout_seconds,
        )
    else:
        self.logger.warning(...)
        result = "failed"

    await self.repository.mark_job_finished(
        review_id=review_id,
        source_id=source_id,
        status=result,
        error=None,
    )
```

In the `TimeoutError` and generic `Exception` handlers, call `mark_job_finished()` only after the job was claimed:

```python
if claimed:
    await self.repository.mark_job_finished(...)
```

Keep `record_retrieval_attempt()` for timeout only when `claimed` is true.

Run: `uv run pytest tests/unit/test_review_preparation_queue.py -q`

Expected: PASS.

- [ ] **Step 7: Remove stale references to old lock contract**

Run: `rg -n "with_preparation_lock|mark_job_running" pubtator_link tests`

Expected after implementation: no matches.

Run: `uv run pytest tests/unit/test_review_preparation_queue.py tests/unit/test_review_rerag_repository.py -q`

Expected: PASS.

- [ ] **Step 8: Run opt-in PostgreSQL claim verification when configured**

Run: `uv run pytest tests/integration/test_review_schema_postgres.py::test_claim_preparation_job_claims_queued_job_once_in_postgres -q`

Expected: SKIP when `PUBTATOR_LINK_TEST_DATABASE_URL` is unset. PASS when the environment variable points at a reachable test PostgreSQL database.

- [ ] **Step 9: Commit review preparation claim model**

```bash
git add pubtator_link/repositories/review_rerag.py pubtator_link/services/review_preparation_queue.py tests/unit/test_review_preparation_queue.py tests/unit/test_review_rerag_repository.py tests/integration/test_review_schema_postgres.py
git commit -m "fix: claim review preparation jobs atomically"
```

## Task 6: Focused Verification And Docs/Changelog Updates

**Files:**
- Modify: `README.md`
- Modify: `docs/development/operations-runbook.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update README cache endpoint documentation**

In `README.md`, change the Core Endpoints cache bullets to:

```markdown
- `GET /api/cache/stats` - Cache statistics when `PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=true`
- `DELETE /api/cache/clear` - Clear all publication-service caches when cache endpoints are explicitly enabled
```

In the Environment Variables table, add:

```markdown
| `PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS` | `false` | Enable opt-in cache management REST endpoints |
```

In the Cache Configuration section, add:

```markdown
Cache management endpoints are disabled by default. Set
`PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=true` to expose `/api/cache/stats` and
`/api/cache/clear`. The clear endpoint clears all publication-service async-lru
caches; pattern-based clearing is rejected until scoped invalidation exists.
```

In Health Monitoring, change the cache example to:

```bash
# Monitor cache performance only when cache endpoints are enabled
PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=true make dev
curl http://localhost:8000/api/cache/stats
```

- [ ] **Step 2: Update operations runbook**

In `docs/development/operations-runbook.md`, under Review Auditability And Upstream Resilience, add:

```markdown
Full-text review preparation records retry attempt metadata from the exact
PubTator export call being audited. Concurrent preparation jobs must use the
sidecar metadata returned by `export_publications_with_metadata()` rather than
shared mutable client state.
```

Add a new section before Logs:

```markdown
## Cache Management Endpoints

`/api/cache/stats` and `/api/cache/clear` are disabled unless
`PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=true`. Hosted deployments should leave
this flag off unless an operator explicitly needs local cache inspection.

`DELETE /api/cache/clear` clears all publication-service async-lru caches and
returns the number of entries present before clearing. Supplying any `pattern`
query parameter returns HTTP 400 because scoped cache invalidation is not
implemented.
```

- [ ] **Step 3: Update changelog**

In `CHANGELOG.md`, add these bullets under `## Unreleased`:

```markdown
- Disabled cache management endpoints by default and made cache clear semantics
  honest: full clears report actual entries cleared, while scoped pattern clears
  now return HTTP 400.
- Removed the unused broken `PublicationService.batch_export_publications()`
  helper.
- Added PubTator export retry metadata sidecars for review preparation audit
  rows without shared mutable client state.
- Corrected MCP review write annotations so append/create tools are marked
  non-idempotent and deduplicated indexing tools remain idempotent.
- Changed review preparation workers to atomically claim queued jobs in a short
  database transaction before running upstream fetch, parser, and embedding work.
```

- [ ] **Step 4: Run focused verification commands**

Run:

```bash
uv run pytest tests/test_routes/test_cache.py -q
uv run pytest tests/test_services.py -q
uv run pytest tests/unit/test_pubtator_client_retry.py -q
uv run pytest tests/unit/test_full_text_preparation.py -q
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
uv run pytest tests/unit/mcp/test_review_rerag_mcp.py -q
uv run pytest tests/unit/test_review_preparation_queue.py -q
uv run pytest tests/unit/test_review_rerag_repository.py -q
uv run pytest tests/integration/test_review_schema_postgres.py::test_claim_preparation_job_claims_queued_job_once_in_postgres -q
rg -n "batch_export_publications\\(" pubtator_link tests
rg -n "with_preparation_lock|mark_job_running" pubtator_link tests
```

Expected:

- Every `uv run pytest ...` command passes.
- The integration command reports SKIP when `PUBTATOR_LINK_TEST_DATABASE_URL` is unset and PASS when a reachable test database is configured.
- `rg -n "batch_export_publications\\(" pubtator_link tests` returns no matches.
- `rg -n "with_preparation_lock|mark_job_running" pubtator_link tests` returns no matches.

- [ ] **Step 5: Run required full verification**

Run:

```bash
make ci-local
make test-cov
```

Expected:

- `make ci-local` passes.
- `make test-cov` passes and stays at or above the existing 80% threshold.

- [ ] **Step 6: Commit verification docs**

```bash
git add README.md docs/development/operations-runbook.md CHANGELOG.md
git commit -m "docs: document correctness sprint behavior changes"
```

## Acceptance Criteria

- `PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS` defaults to disabled, and `UnifiedServerManager.create_app()` does not mount cache routes while disabled.
- `/api/cache/stats` and `/api/cache/clear` return FastAPI 404 responses when cache endpoints are disabled.
- `DELETE /api/cache/clear` with any supplied `pattern` returns HTTP 400 with `Pattern-based cache clearing is not supported.`
- Full cache clear returns the number of current async-lru entries present before clearing.
- `PublicationService.batch_export_publications()` has been removed, and `rg -n "batch_export_publications\\(" pubtator_link tests` returns no matches.
- `PubTator3Client.export_publications_with_metadata()` returns the payload and the retry metadata for the same request.
- Retry-exhausted PubTator export errors attach `response_data["retry_metadata"]["terminal_reason"] == "retry_exhausted"`.
- `FullTextPreparationService.prepare_pmid()` records retry metadata from the sidecar path when available and still supports older fake clients through `_last_retry_metadata()`.
- MCP annotations are exact for all six review write tools: four append/create tools are non-idempotent, and `pubtator_index_review_evidence` plus `pubtator_ground_question` remain idempotent.
- Review preparation workers call `claim_preparation_job()` once per dequeued item and skip upstream work if the claim returns false.
- PostgreSQL job claim uses a short transaction, transaction-scoped advisory lock, and an atomic `status = 'queued'` update returning `job_id`.
- Slow fake preparation jobs run concurrently when `prep_concurrency=2`.
- Documentation and changelog mention the cache endpoint default change, clear semantics, retry metadata sidecar, MCP annotation correction, and review preparation claim model.
- `make ci-local` and `make test-cov` pass.

## Self-Review

- Spec coverage: Tasks 1 through 6 map directly to the six approved workstreams. Cache gating, dead batch removal, retry metadata sidecars, MCP idempotency classification, atomic preparation claiming, concurrency tests, focused verification, and docs updates all have concrete steps.
- Unresolved-marker scan: no deferred implementation markers are intentionally left in this plan.
- Type and signature consistency: `claim_preparation_job(*, review_id: str, source_id: str) -> bool` is used consistently in the repository protocol, concrete repository, queue, and tests. `export_publications_with_metadata(...) -> tuple[dict[str, Any], RetryAttemptMetadata]` is used consistently by the client tests, while `FullTextPreparationService` converts metadata objects or mappings into `dict[str, Any]` for existing audit recording.
- Acceptance criteria: every success criterion from the spec is represented by a focused test command, grep verification, documentation update, or final Makefile check.
