# MCP Payload Safety Grounding Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the high-priority MCP remediation slice: compact payloads, hosted HTTP/MCP safety controls, typed MCP error mapping, and the additive `pubtator.ground_question` workflow.

**Architecture:** Keep response shaping in existing Pydantic/service boundaries, add small HTTP middleware for hosted safety, introduce typed service exceptions without changing public payload contracts, and reuse the existing search/index/inspect/retrieve services for `ground_question`. This plan deliberately avoids tool renaming and broad retrieval refactors.

**Tech Stack:** Python 3.11/3.12, FastAPI, Starlette middleware, FastMCP, Pydantic v2, pytest, Ruff, mypy, Makefile targets.

---

## Working Rules

- Work in the existing `pubtator-link-mcp-modernization` worktree unless the user asks for a fresh worktree.
- Do not revert unrelated changes.
- Do not edit files under `benchmarks/`.
- Use TDD for every task: failing focused test, minimal implementation, passing focused test, commit.
- Prefer `uv run pytest ... -q` for focused checks and `make ci-local` for final verification.
- Keep commits per completed task.

## Source Specs

- Primary spec: `docs/superpowers/specs/2026-05-03-mcp-payload-safety-grounding-design.md`
- Existing one-call workflow spec: `docs/superpowers/specs/2026-05-03-mcp-ground-question-and-guideline-budget-design.md`
- Existing one-call workflow plan for detailed snippets:
  `docs/superpowers/plans/2026-05-03-mcp-ground-question-and-guideline-budget-implementation.md`

If the two specs differ, follow the payload-safety-grounding spec for profile
visibility and compact output behavior.

## Files

- Modify: `pubtator_link/models/responses.py`
  - Add `first_author_et_al` to `SearchResult`.
- Modify: `pubtator_link/services/search_shaping.py`
  - Populate author summary and stop merging full author arrays into compact/basic metadata.
- Modify: `tests/unit/test_search_shaping.py`
  - Cover compact author summary and full-author opt-in.
- Modify: `pubtator_link/mcp/service_adapters.py`
  - Slim `_meta` for search and add `ground_question_impl`.
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
  - Cover slim search `_meta` and `ground_question_impl`.
- Modify: `pubtator_link/models/responses.py`
  - Add diagnostics workflow fields to `DiagnosticsResponse`.
- Modify: `pubtator_link/services/diagnostics.py`
  - Return minimum viable workflow guidance.
- Modify: `tests/unit/mcp/test_mcp_facade.py`
  - Cover diagnostics schema and `ground_question` registration.
- Modify: `pubtator_link/config.py`
  - Add CORS method/header, request-size, and inbound rate-limit settings.
- Modify: `pubtator_link/server_manager.py`
  - Use explicit CORS config and add request-size/rate-limit middleware.
- Modify: `tests/unit/test_server_manager.py`
  - Cover CORS config, 413 request-size response, and 429 rate-limit response.
- Create: `pubtator_link/services/errors.py`
  - Define typed service errors.
- Modify: `pubtator_link/mcp/errors.py`
  - Map typed errors with `isinstance`.
- Modify: `tests/unit/mcp/test_mcp_errors.py`
  - Cover typed error-code mapping and backward-compatible fallback.
- Modify: `pubtator_link/models/review_rerag.py`
  - Add `GroundQuestionResponse` and any missing verbosity/budget types if not already implemented.
- Modify: `pubtator_link/mcp/tools/review.py`
  - Register `pubtator.ground_question` in lean/full profiles only.
- Modify: `pubtator_link/mcp/profiles.py`
  - Add `pubtator.ground_question` to lean/full and exclude it from readonly.
- Modify: `pubtator_link/mcp/catalog.py`
  - Add catalog metadata for `pubtator.ground_question`.
- Modify: `pubtator_link/mcp/resources.py`
  - Add one-call workflow guidance to existing core review workflow lists.
- Modify: `pubtator_link/mcp/facade.py`
  - Mention `ground_question` as the one-call path while keeping the explicit chain.
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
  - Document payload and one-call workflow updates.
- Regenerate: `docs/mcp-tool-catalog.md`
  - Run `uv run python scripts/generate_mcp_tool_catalog.py`.

## Task 1: Slim Compact Search Payloads And Search `_meta`

**Files:**
- Modify: `tests/unit/test_search_shaping.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `pubtator_link/models/responses.py`
- Modify: `pubtator_link/services/search_shaping.py`
- Modify: `pubtator_link/mcp/service_adapters.py`

- [ ] **Step 1: Write failing tests for compact author summary**

In `tests/unit/test_search_shaping.py`, update
`test_shaped_search_response_can_merge_basic_metadata` so compact/basic metadata
does not expose full authors and does expose the summary:

```python
    result = shaped.results[0]
    assert result.authors == []
    assert result.first_author_et_al == "Kavrul Kayaalp GK"
    assert result.journal == "Rheumatology International"
    assert result.pub_year == 2022
    assert result.pub_date == "2022 Jan"
    assert result.volume is None
```

Append this second test:

```python
def test_shaped_search_response_full_metadata_keeps_author_array() -> None:
    shaped = shaped_search_response(
        raw={"total": 1, "results": [{"pmid": "33454820", "title": "Title"}]},
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="compact",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
        metadata="full",
        metadata_by_pmid={
            "33454820": {
                "authors": [
                    {"display_name": "Kavrul Kayaalp GK"},
                    {"display_name": "Ozen S"},
                ],
            }
        },
    )

    result = shaped.results[0]
    assert [author.display_name for author in result.authors] == [
        "Kavrul Kayaalp GK",
        "Ozen S",
    ]
    assert result.first_author_et_al == "Kavrul Kayaalp GK et al."
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py::test_shaped_search_response_can_merge_basic_metadata tests/unit/test_search_shaping.py::test_shaped_search_response_full_metadata_keeps_author_array -q
```

Expected: FAIL because `first_author_et_al` does not exist and compact/basic
still merges `authors`.

- [ ] **Step 3: Add `first_author_et_al` to `SearchResult`**

In `pubtator_link/models/responses.py`, add this field immediately after
`authors`:

```python
    first_author_et_al: str | None = Field(
        default=None,
        description="Compact first-author citation label",
    )
```

- [ ] **Step 4: Add author-summary helpers and compact merge rules**

In `pubtator_link/services/search_shaping.py`, add this helper after
`_shape_authors`:

```python
def _author_summary(authors: list[PublicationAuthor]) -> str | None:
    if not authors:
        return None
    first = authors[0].display_name
    if not first:
        first = authors[0].collective_name
    if not first:
        return None
    return f"{first} et al." if len(authors) > 1 else first
```

In `shaped_search_result`, compute authors once before building `SearchResult`:

```python
    raw_authors = _shape_authors(item.get("authors", []))
    include_author_array = response_mode in {"standard", "full"}
```

Then set:

```python
        authors=raw_authors if include_author_array else [],
        first_author_et_al=_author_summary(raw_authors),
```

Replace the start of `_merge_metadata_fields` with:

```python
    metadata_authors = _shape_authors(metadata_item.get("authors", []))
    if shaped.first_author_et_al is None:
        shaped.first_author_et_al = _author_summary(metadata_authors)

    basic_fields = (
        "journal",
        "pub_year",
        "pub_date",
        "volume",
        "issue",
        "pages",
        "doi",
        "pmcid",
        "publication_types",
    )
    full_fields = ("authors", *basic_fields, "mesh_headings", "nlm_citation", "bibtex")
```

Keep the existing `for field_name in ...` loop, including the existing
`if field_name == "authors": value = _shape_authors(value)` branch.

- [ ] **Step 5: Verify search shaping tests pass**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py::test_shaped_search_response_can_merge_basic_metadata tests/unit/test_search_shaping.py::test_shaped_search_response_full_metadata_keeps_author_array -q
```

Expected: PASS.

- [ ] **Step 6: Write failing slim `_meta` test**

Append to `tests/unit/mcp/test_mcp_service_adapters.py` near existing search
adapter tests:

```python
@pytest.mark.asyncio
async def test_search_literature_meta_uses_short_next_tool_hints() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "1", "title": "FMF guideline"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(client=FakeClient(), text="FMF")

    meta = result["_meta"]
    assert meta["next_tools"] == [
        "pubtator.preflight_review_sources",
        "pubtator.index_review_evidence",
    ]
    assert meta["workflow"] == "search -> preflight -> index -> inspect -> retrieve"
    assert meta["details_resource"] == "pubtator://workflow-help"
    assert "next_commands" not in meta
```

- [ ] **Step 7: Run slim `_meta` test and verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_search_literature_meta_uses_short_next_tool_hints -q
```

Expected: FAIL because search metadata still uses full `next_commands`.

- [ ] **Step 8: Replace default search `_meta`**

In `pubtator_link/mcp/service_adapters.py`, replace the `response_meta = {...}`
block inside `search_literature_impl` with:

```python
    response_meta = {
        "coverage_note": (
            "Search is read-only metadata discovery. Use coverage='preflight' or "
            "pubtator.preflight_review_sources before indexing if source coverage matters."
        ),
        "next_tools": [
            "pubtator.preflight_review_sources",
            "pubtator.index_review_evidence",
        ],
        "workflow": "search -> preflight -> index -> inspect -> retrieve",
        "details_resource": "pubtator://workflow-help",
    }
```

Keep `candidate_pmids` if another caller still uses it nearby; remove it if it
only existed to build `next_commands`.

- [ ] **Step 9: Run focused payload tests**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py tests/unit/mcp/test_mcp_service_adapters.py::test_search_literature_meta_uses_short_next_tool_hints -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add pubtator_link/models/responses.py pubtator_link/services/search_shaping.py pubtator_link/mcp/service_adapters.py tests/unit/test_search_shaping.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "fix: slim compact search payloads"
```

Expected: commit succeeds.

## Task 2: Add Diagnostics Minimum Workflow

**Files:**
- Modify: `pubtator_link/models/responses.py`
- Modify: `pubtator_link/services/diagnostics.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing diagnostics schema/output test**

Append to `tests/unit/mcp/test_mcp_facade.py` near diagnostics tests:

```python
def test_diagnostics_schema_exposes_minimum_workflow() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.diagnostics"]
    schema = tool.output_schema

    assert "minimum_workflow" in schema["properties"]
```

Append this service-level test to `tests/unit/mcp/test_mcp_facade.py`:

```python
@pytest.mark.asyncio
async def test_diagnostics_response_includes_minimum_workflow() -> None:
    from pubtator_link.db.migrate import ReviewSchemaDiagnostics
    from pubtator_link.services.diagnostics import DiagnosticsService

    async def inspect_schema() -> ReviewSchemaDiagnostics:
        return ReviewSchemaDiagnostics(
            connected=True,
            current=True,
            applied_versions=[],
            missing_tables=[],
            missing_columns=[],
            error=None,
        )

    service = DiagnosticsService(
        inspect_schema=inspect_schema,
        review_queue_available=lambda: True,
        europe_pmc_enabled=lambda: False,
    )

    result = await service.get_diagnostics()

    assert result.minimum_workflow["grounded_review"] == [
        "pubtator.search_literature",
        "pubtator.preflight_review_sources",
        "pubtator.index_review_evidence",
        "pubtator.inspect_review_index",
        "pubtator.retrieve_review_context_batch",
    ]
    assert result.minimum_workflow["workflow_resource"] == "pubtator://workflow-help"
```

- [ ] **Step 2: Run diagnostics tests and verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py::test_diagnostics_schema_exposes_minimum_workflow tests/unit/mcp/test_mcp_facade.py::test_diagnostics_response_includes_minimum_workflow -q
```

Expected: FAIL because `minimum_workflow` does not exist.

- [ ] **Step 3: Add field to `DiagnosticsResponse`**

In `pubtator_link/models/responses.py`, add this field to `DiagnosticsResponse`:

```python
    minimum_workflow: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Populate workflow in diagnostics service**

In `pubtator_link/services/diagnostics.py`, before returning
`DiagnosticsResponse`, add:

```python
        minimum_workflow: dict[str, Any] = {
            "grounded_review": [
                "pubtator.search_literature",
                "pubtator.preflight_review_sources",
                "pubtator.index_review_evidence",
                "pubtator.inspect_review_index",
                "pubtator.retrieve_review_context_batch",
            ],
            "workflow_resource": "pubtator://workflow-help",
        }
```

Then pass it into the response:

```python
            minimum_workflow=minimum_workflow,
```

After Task 4 adds `pubtator.ground_question`, update this block to include:

```python
            "one_call": "pubtator.ground_question",
```

- [ ] **Step 5: Run diagnostics tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py::test_diagnostics_schema_exposes_minimum_workflow tests/unit/mcp/test_mcp_facade.py::test_diagnostics_response_includes_minimum_workflow -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/models/responses.py pubtator_link/services/diagnostics.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: expose minimum MCP workflow in diagnostics"
```

Expected: commit succeeds.

## Task 3: Add Hosted HTTP And MCP Safety Controls

**Files:**
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/server_manager.py`
- Modify: `tests/unit/test_server_manager.py`

- [ ] **Step 1: Write failing CORS configuration test**

Append to `tests/unit/test_server_manager.py`:

```python
def test_create_app_uses_explicit_cors_methods_and_headers() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app()

    cors_middleware = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]
    assert cors_middleware.kwargs["allow_headers"] == [
        "Authorization",
        "Content-Type",
        "Mcp-Session-Id",
        "Last-Event-ID",
        "X-Request-ID",
    ]
```

- [ ] **Step 2: Write failing request-size and rate-limit tests**

Append to `tests/unit/test_server_manager.py`:

```python
def test_post_request_size_limit_returns_stable_413(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.http_max_request_bytes", 8)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.post("/echo")
    async def echo() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).post("/echo", content=b"0123456789")

    assert response.status_code == 413
    assert response.json() == {
        "success": False,
        "error_code": "request_too_large",
        "message": "Request body exceeds configured maximum size.",
        "retryable": False,
    }


def test_inbound_rate_limit_returns_stable_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pubtator_link.server_manager.settings.enable_inbound_rate_limit", True)
    monkeypatch.setattr("pubtator_link.server_manager.settings.inbound_rate_limit_per_minute", 1)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=False)

    @app.get("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/limited").status_code == 200
    response = client.get("/limited")

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert response.json()["retryable"] is True
```

- [ ] **Step 3: Run safety tests and verify failure**

Run:

```bash
uv run pytest tests/unit/test_server_manager.py::test_create_app_uses_explicit_cors_methods_and_headers tests/unit/test_server_manager.py::test_post_request_size_limit_returns_stable_413 tests/unit/test_server_manager.py::test_inbound_rate_limit_returns_stable_429 -q
```

Expected: FAIL because settings and middleware do not exist yet.

- [ ] **Step 4: Add settings**

In `pubtator_link/config.py`, after `cors_origins`, add:

```python
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "OPTIONS"],
        description="CORS allowed HTTP methods",
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: [
            "Authorization",
            "Content-Type",
            "Mcp-Session-Id",
            "Last-Event-ID",
            "X-Request-ID",
        ],
        description="CORS allowed request headers",
    )
    http_max_request_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        description="Maximum inbound HTTP request body size in bytes",
    )
    enable_inbound_rate_limit: bool = Field(
        default=False,
        description="Enable simple per-client inbound HTTP rate limiting",
    )
    inbound_rate_limit_per_minute: int = Field(
        default=120,
        ge=1,
        description="Maximum requests per client per minute when inbound rate limiting is enabled",
    )
```

Add validators after `parse_cors_origins`:

```python
    @field_validator("cors_allow_methods", "cors_allow_headers", mode="before")
    @classmethod
    def parse_csv_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v  # type: ignore[no-any-return]
```

- [ ] **Step 5: Add middleware classes**

In `pubtator_link/server_manager.py`, import:

```python
import time
from collections import defaultdict, deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send
```

Add these classes near `PubTatorResourcesMiddleware`:

```python
class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    await _json_error_response(
                        send,
                        status_code=413,
                        payload={
                            "success": False,
                            "error_code": "request_too_large",
                            "message": "Request body exceeds configured maximum size.",
                            "retryable": False,
                        },
                    )
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, limited_receive, send)


class InboundRateLimitMiddleware:
    def __init__(self, app: ASGIApp, *, requests_per_minute: int) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_key = client[0] if client else "unknown"
        now = time.monotonic()
        hits = self._hits[client_key]
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()
        if len(hits) >= self.requests_per_minute:
            await _json_error_response(
                send,
                status_code=429,
                payload={
                    "success": False,
                    "error_code": "rate_limited",
                    "message": "Inbound request rate limit exceeded.",
                    "retryable": True,
                    "retry_after_seconds": max(1, int(self.window_seconds - (now - hits[0]))),
                },
            )
            return
        hits.append(now)
        await self.app(scope, receive, send)


async def _json_error_response(send: Send, *, status_code: int, payload: dict[str, object]) -> None:
    import json

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
```

- [ ] **Step 6: Wire middleware and explicit CORS**

In `UnifiedServerManager.create_app`, update the CORS middleware kwargs:

```python
            allow_methods=settings.cors_allow_methods,
            allow_headers=settings.cors_allow_headers,
```

Add request-size middleware after CORS:

```python
        app.add_middleware(
            RequestSizeLimitMiddleware,
            max_bytes=settings.http_max_request_bytes,
        )
```

Add inbound rate limiting only when enabled:

```python
        if settings.enable_inbound_rate_limit:
            app.add_middleware(
                InboundRateLimitMiddleware,
                requests_per_minute=settings.inbound_rate_limit_per_minute,
            )
```

- [ ] **Step 7: Run focused safety tests**

Run:

```bash
uv run pytest tests/unit/test_server_manager.py::test_create_app_uses_explicit_cors_methods_and_headers tests/unit/test_server_manager.py::test_post_request_size_limit_returns_stable_413 tests/unit/test_server_manager.py::test_inbound_rate_limit_returns_stable_429 -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add pubtator_link/config.py pubtator_link/server_manager.py tests/unit/test_server_manager.py
git commit -m "feat: add hosted HTTP safety controls"
```

Expected: commit succeeds.

## Task 4: Add Typed Service Errors And MCP Mapping

**Files:**
- Create: `pubtator_link/services/errors.py`
- Modify: `pubtator_link/mcp/errors.py`
- Create or modify: `tests/unit/mcp/test_mcp_errors.py`

- [ ] **Step 1: Write failing error mapping tests**

Create `tests/unit/mcp/test_mcp_errors.py` if it does not exist, with:

```python
from pubtator_link.mcp.errors import error_code_for_exception
from pubtator_link.services.errors import (
    ReviewIndexUnavailableError,
    ReviewSchemaStaleError,
    UpstreamUnavailableError,
    ValidationFailureError,
)


def test_error_code_for_typed_review_errors() -> None:
    assert error_code_for_exception(ReviewSchemaStaleError("schema stale")) == (
        "review_schema_not_current"
    )
    assert error_code_for_exception(ReviewIndexUnavailableError("db unavailable")) == (
        "review_index_unavailable"
    )
    assert error_code_for_exception(UpstreamUnavailableError("timeout")) == (
        "upstream_unavailable"
    )
    assert error_code_for_exception(ValidationFailureError("bad input")) == (
        "validation_failed"
    )


def test_error_code_legacy_schema_text_fallback_still_works() -> None:
    assert error_code_for_exception(RuntimeError("column updated_at missing from reviews")) == (
        "review_schema_not_current"
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_errors.py -q
```

Expected: FAIL because `pubtator_link.services.errors` does not exist.

- [ ] **Step 3: Add typed error module**

Create `pubtator_link/services/errors.py`:

```python
from __future__ import annotations


class PubTatorLinkError(Exception):
    """Base class for PubTator-Link service errors with stable MCP mapping."""


class ReviewSchemaStaleError(PubTatorLinkError):
    """Review database schema is missing required tables or columns."""


class ReviewIndexUnavailableError(PubTatorLinkError):
    """Review database or index storage is unavailable."""


class UpstreamUnavailableError(PubTatorLinkError):
    """External upstream service timed out or is unavailable."""


class ValidationFailureError(PubTatorLinkError):
    """User-correctable validation failure."""
```

- [ ] **Step 4: Map typed errors before legacy string checks**

In `pubtator_link/mcp/errors.py`, import:

```python
from pubtator_link.services.errors import (
    ReviewIndexUnavailableError,
    ReviewSchemaStaleError,
    UpstreamUnavailableError,
    ValidationFailureError,
)
```

At the start of `error_code_for_exception`, add:

```python
    if isinstance(exc, ReviewSchemaStaleError):
        return "review_schema_not_current"
    if isinstance(exc, ReviewIndexUnavailableError):
        return "review_index_unavailable"
    if isinstance(exc, UpstreamUnavailableError):
        return "upstream_unavailable"
    if isinstance(exc, ValidationFailureError):
        return "validation_failed"
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_errors.py -q
```

Expected: PASS.

- [ ] **Step 6: Convert the startup schema boundary to typed errors**

In `pubtator_link/api/routes/dependencies.py`, import:

```python
from ...services.errors import ReviewSchemaStaleError
```

Replace the schema-current startup failure:

```python
                raise RuntimeError(f"Review database schema is not current: {missing}")
```

with:

```python
                raise ReviewSchemaStaleError(
                    f"Review database schema is not current: {missing}"
                )
```

- [ ] **Step 7: Run MCP and review error tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_errors.py tests/unit/mcp/test_mcp_service_adapters.py -q -k "error or schema or diagnostics"
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add pubtator_link/services/errors.py pubtator_link/mcp/errors.py tests/unit/mcp/test_mcp_errors.py
git add pubtator_link/api/routes/dependencies.py
git commit -m "feat: add typed MCP service error mapping"
```

Expected: commit succeeds and includes only relevant typed-error changes.

## Task 5: Add `pubtator.ground_question`

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/profiles.py`
- Modify: `pubtator_link/mcp/catalog.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_mcp_profiles.py`

- [ ] **Step 1: Reuse the existing detailed plan for model and adapter code**

Open:

```bash
sed -n '516,970p' docs/superpowers/plans/2026-05-03-mcp-ground-question-and-guideline-budget-implementation.md
```

Apply only the `ground_question` model, adapter, and registration portions.
Do not implement unrelated guideline ranking or auto-budget changes from that
plan unless they are already required by the copied snippets.

- [ ] **Step 2: Write failing profile visibility test**

In `tests/unit/mcp/test_mcp_profiles.py`, add:

```python
def test_ground_question_is_lean_and_full_but_not_readonly() -> None:
    assert "pubtator.ground_question" in tool_names_for_profile("lean")
    assert "pubtator.ground_question" in tool_names_for_profile("full")
    assert "pubtator.ground_question" not in tool_names_for_profile("readonly")
```

- [ ] **Step 3: Write failing facade schema test**

In `tests/unit/mcp/test_mcp_facade.py`, add:

```python
def test_ground_question_schema_exposes_one_call_arguments() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.ground_question"]
    properties = tool.parameters["properties"]

    assert properties["question"]["type"] == "string"
    assert properties["max_pmids"]["minimum"] == 1
    assert properties["max_pmids"]["maximum"] == 20
    assert properties["wait_until_ready"]["default"] is True
    assert tool.output_schema["title"] == "GroundQuestionResponse"
```

- [ ] **Step 4: Write failing adapter happy-path and no-PMID tests**

Use the tests from the existing ground-question plan:

```bash
sed -n '516,640p' docs/superpowers/plans/2026-05-03-mcp-ground-question-and-guideline-budget-implementation.md
```

Copy both tests into `tests/unit/mcp/test_mcp_service_adapters.py`, but assert
the final result also includes compact metadata:

```python
    assert result["next_tools"]
    assert "next_commands" not in result.get("_meta", {})
```

- [ ] **Step 5: Run failing ground-question tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_profiles.py::test_ground_question_is_lean_and_full_but_not_readonly tests/unit/mcp/test_mcp_facade.py::test_ground_question_schema_exposes_one_call_arguments tests/unit/mcp/test_mcp_service_adapters.py -q -k "ground_question"
```

Expected: FAIL because `pubtator.ground_question` is not registered.

- [ ] **Step 6: Add model**

In `pubtator_link/models/review_rerag.py`, add a compact response model near
`ReviewQuickstartResponse`:

```python
class GroundQuestionResponse(BaseModel):
    """Composite one-call grounded question workflow response."""

    success: bool = True
    question: str
    review_id: str
    selected_pmids: list[str] = Field(default_factory=list)
    search_total_results: int = 0
    preparation_status: PreparationStatus | None = None
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    ready_to_retrieve: bool = False
    context: RetrieveReviewContextBatchResponse | None = None
    next_tools: list[str] = Field(default_factory=list)
    recovery: list[str] = Field(default_factory=list)
```

- [ ] **Step 7: Add profile entry**

In `pubtator_link/mcp/profiles.py`, add `"pubtator.ground_question"` to
`LEAN_TOOLS` near `pubtator.review_quickstart` workflow neighbors. Do not add it
to `FULL_ONLY_TOOLS`; `full` includes lean tools automatically. Add it to the
`READONLY_TOOLS` exclusion set.

- [ ] **Step 8: Add adapter implementation**

In `pubtator_link/mcp/service_adapters.py`, add `ground_question_impl` near
`review_quickstart_impl`. Use this structure:

```python
async def ground_question_impl(
    *,
    client: PubTator3Client,
    index_service: Any,
    context_service: ReviewContextService,
    question: str,
    max_pmids: int = 8,
    review_id: str | None = None,
    entity_ids: list[str] | None = None,
    guideline_boost: bool = True,
    wait_until_ready: bool = True,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    normalized_question = question.strip()
    selected_review_id = review_id or _quickstart_review_id(normalized_question)
    search = await search_literature_impl(
        client=client,
        text=normalized_question,
        limit=max_pmids,
        entity_ids=entity_ids,
        guideline_boost=guideline_boost,
        response_mode="compact",
        include_citations="none",
        metadata="basic",
    )
    selected_pmids = []
    for item in search.get("results", []):
        pmid = str(item.get("pmid", "")).strip()
        if pmid and pmid not in selected_pmids:
            selected_pmids.append(pmid)
    if not selected_pmids:
        return GroundQuestionResponse(
            question=normalized_question,
            review_id=selected_review_id,
            search_total_results=int(search.get("total_results", 0)),
            next_tools=["pubtator.search_literature"],
            recovery=["Refine the search query or provide candidate PMIDs explicitly."],
        ).model_dump(mode="json")

    index_response = await index_review_evidence_impl(
        service=index_service,
        review_id=selected_review_id,
        pmids=selected_pmids,
        wait_until_ready=wait_until_ready,
        timeout_ms=timeout_ms,
    )
    inspect_response = await context_service.inspect_review_index(
        selected_review_id,
        InspectReviewIndexRequest(),
    )
    ready_to_retrieve = inspect_response.totals.passage_count > 0
    context = None
    next_tools = ["pubtator.inspect_review_index"]
    recovery: list[str] = []
    if ready_to_retrieve:
        context = await retrieve_review_context_batch_impl(
            service=context_service,
            review_id=selected_review_id,
            queries=[normalized_question],
            pmids=None,
            entity_ids=entity_ids,
            max_total_passages=8,
            max_response_chars=12_000,
            response_mode="compact",
            include_diagnostics=False,
        )
        next_tools = ["pubtator.retrieve_review_context_batch", "pubtator.record_review_context"]
    else:
        recovery.append("Indexing has not produced passages yet; inspect the review index and retry retrieval.")

    return GroundQuestionResponse(
        question=normalized_question,
        review_id=selected_review_id,
        selected_pmids=selected_pmids,
        search_total_results=int(search.get("total_results", 0)),
        preparation_status=inspect_response.preparation_status,
        coverage_summary=inspect_response.coverage_summary,
        ready_to_retrieve=ready_to_retrieve,
        context=context,
        next_tools=next_tools,
        recovery=recovery,
    ).model_dump(mode="json")
```

Use the current local signatures of `index_review_evidence_impl` and
`retrieve_review_context_batch_impl`; keep argument names identical to those
functions.

- [ ] **Step 9: Register MCP tool**

In `pubtator_link/mcp/tools/review.py`, import `GroundQuestionResponse` and
`ground_question_impl`. Register near `review_quickstart`:

```python
    @mcp_tool_for(
        "lean",
        "full",
        name="pubtator.ground_question",
        title="Ground Question",
        output_schema=GroundQuestionResponse.model_json_schema(),
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def ground_question(
        question: Annotated[str, Field(min_length=1)],
        max_pmids: Annotated[int, Field(ge=1, le=20)] = 8,
        review_id: Annotated[str | None, Field(min_length=1)] = None,
        entity_ids: list[str] | None = None,
        guideline_boost: bool = True,
        wait_until_ready: bool = True,
        timeout_ms: Annotated[int, Field(ge=0, le=120_000)] = 30_000,
    ) -> dict[str, Any]:
        """Use this when a user wants one-call grounded biomedical evidence: search candidate PMIDs, index review evidence, inspect readiness, and retrieve compact citable context. Do not use for clinical decision support."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            index_service = await get_review_index_lifecycle_service()
            context_service = await get_review_context_service()
            return await ground_question_impl(
                client=client,
                index_service=index_service,
                context_service=context_service,
                question=question,
                max_pmids=max_pmids,
                review_id=review_id,
                entity_ids=entity_ids,
                guideline_boost=guideline_boost,
                wait_until_ready=wait_until_ready,
                timeout_ms=timeout_ms,
            )

        return await run_mcp_tool("pubtator.ground_question", call)
```

If `get_api_client` is not imported in `review.py`, import it from
`pubtator_link.api.routes.dependencies`.

- [ ] **Step 10: Add catalog and workflow guidance**

In `pubtator_link/mcp/catalog.py`, add a `ToolCatalogSupplement` for
`pubtator.ground_question`:

```python
    "pubtator.ground_question": ToolCatalogSupplement(
        category="review",
        stability="lean",
        purpose=(
            "One-call grounded research workflow that searches literature, indexes "
            "candidate PMIDs, inspects readiness, and retrieves compact citable context."
        ),
        do_not_use_for=("clinical decision support", "uncited answer generation"),
        example='{"question":"Does colchicine prevent FMF flares?","max_pmids":8}',
        next_tools=("pubtator.record_review_context", "pubtator.get_review_audit_trail"),
        resource_links=("pubtator://workflow-help",),
    ),
```

In `pubtator_link/mcp/facade.py`, update instructions to include:

```python
"For one-call grounded evidence use pubtator.ground_question; for explicit control use "
"search -> preflight -> index -> inspect -> retrieve. "
```

In `pubtator_link/mcp/resources.py`, add `pubtator.ground_question` anywhere
the core review workflow tools are listed for lean clients.

In `pubtator_link/services/diagnostics.py`, update `minimum_workflow` to include:

```python
            "one_call": "pubtator.ground_question",
```

- [ ] **Step 11: Run focused ground-question tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_profiles.py::test_ground_question_is_lean_and_full_but_not_readonly tests/unit/mcp/test_mcp_facade.py::test_ground_question_schema_exposes_one_call_arguments tests/unit/mcp/test_mcp_service_adapters.py -q -k "ground_question"
```

Expected: PASS.

- [ ] **Step 12: Regenerate catalog and commit**

Run:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
git add pubtator_link/models/review_rerag.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/profiles.py pubtator_link/mcp/catalog.py pubtator_link/mcp/resources.py pubtator_link/mcp/facade.py pubtator_link/services/diagnostics.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_profiles.py docs/mcp-tool-catalog.md
git commit -m "feat: add ground question MCP workflow"
```

Expected: commit succeeds.

## Task 6: Documentation Status And Final Verification

**Files:**
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `docs/2026-05-02-pubtator-link-consolidated-roadmap.md`
- Modify: `docs/2026-05-03-mcp-llm-lean-speed-accuracy-report.md`

- [ ] **Step 1: Update MCP connection guide**

Add a short one-call path near the review workflow section:

```markdown
For standard grounded research questions, prefer `pubtator.ground_question`
when the server is allowed to index review evidence. It returns selected PMIDs,
preparation state, coverage summary, and compact retrieved context in one call.
Use the explicit chain (`search_literature` -> `preflight_review_sources` ->
`index_review_evidence` -> `inspect_review_index` ->
`retrieve_review_context_batch`) when you need manual corpus control.
```

Add a compact payload note:

```markdown
Compact search results return `first_author_et_al` by default. Request
`metadata="full"` or `response_mode="standard"`/`"full"` only when full author
arrays or full citation metadata are needed.
```

- [ ] **Step 2: Update roadmap/report status notes**

In both roadmap/report docs, add a dated status note near the top:

```markdown
> Status note, 2026-05-03: The MCP modernization branch now includes lean/full/
> readonly profiles, generated tool catalog, review resource templates, durable
> LLM context, compact search author summaries, minimum diagnostics workflow,
> hosted HTTP safety controls, typed MCP error mapping, and
> `pubtator.ground_question`. Remaining larger work is OAuth/public auth,
> OpenTelemetry, cursor pagination, optional elicitation, and hybrid retrieval
> quality upgrades.
```

Keep the original historical recommendations below the note.

- [ ] **Step 3: Run focused MCP and server suites**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py tests/unit/test_server_manager.py tests/unit/mcp/test_mcp_errors.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: PASS.

- [ ] **Step 4: Run formatting/linting/typecheck**

Run:

```bash
make format
make lint
make typecheck-fast
```

Expected: all pass.

- [ ] **Step 5: Run full local CI**

Run:

```bash
make ci-local
```

Expected: PASS.

- [ ] **Step 6: Commit docs and any generated catalog updates**

Run:

```bash
git add docs/MCP_CONNECTION_GUIDE.md docs/2026-05-02-pubtator-link-consolidated-roadmap.md docs/2026-05-03-mcp-llm-lean-speed-accuracy-report.md docs/mcp-tool-catalog.md
git commit -m "docs: update MCP remediation status"
```

Expected: commit succeeds if documentation changed. If no docs changed because
the status note was already present, do not create an empty commit.

## Final Verification

- [ ] **Step 1: Confirm clean worktree**

Run:

```bash
git status --short
```

Expected: no uncommitted source changes.

- [ ] **Step 2: Rebuild and restart Docker on existing ports if requested**

Run with the ports already used in this branch:

```bash
PUBTATOR_LINK_PORT=8011 PUBTATOR_LINK_POSTGRES_PORT=55432 docker compose -f docker/docker-compose.yml up -d --build --force-recreate
```

Expected: `pubtator_link_server` and `pubtator_link_postgres` recreate and
become healthy on the same host ports.

- [ ] **Step 3: Smoke MCP tool list if Docker was restarted**

Run:

```bash
curl -sS http://127.0.0.1:8011/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Expected: response includes `pubtator.ground_question`,
`pubtator.search_literature`, and `pubtator.diagnostics`.

## Plan Self-Review Checklist

- Spec coverage:
  - Task 1 covers compact search author summaries and slim search `_meta`.
  - Task 2 covers diagnostics minimum workflow.
  - Task 3 covers hosted CORS, request-size, and rate-limit controls.
  - Task 4 covers typed service errors and MCP mapping.
  - Task 5 covers `pubtator.ground_question`.
  - Task 6 covers roadmap/report/doc status and full verification.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation steps.
- Type consistency:
  - `first_author_et_al`, `minimum_workflow`, `GroundQuestionResponse`,
    `next_tools`, and typed error class names are consistent across tasks.
