# Typed MCP Output Schemas And Review Index Lifecycle Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add concrete MCP output schemas for high-use tools and add review index inventory plus TTL cleanup without changing existing evidence retrieval semantics.

**Architecture:** Reuse existing Pydantic REST/review models for MCP tool return annotations, add MCP-only wrapper models only where MCP JSON intentionally differs from REST, then add repository/service/route/tool lifecycle surfaces for review index inventory. Keep destructive cleanup gated by configuration and off by default.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic, asyncpg/PostgreSQL, pytest, pytest-asyncio, Ruff, mypy, Makefile targets.

---

## File Structure

- Modify `pubtator_link/models/review_rerag.py` for MCP wrapper models and review index inventory models.
- Create or modify `pubtator_link/models/literature.py` if no typed literature search response model already exists.
- Modify `pubtator_link/mcp/tools/literature.py` and `pubtator_link/mcp/tools/review.py` to return typed models or explicit output schemas.
- Modify `pubtator_link/mcp/service_adapters.py` to return Pydantic models before FastMCP serialization where practical.
- Modify `pubtator_link/db/review_schema.sql` for `reviews.updated_at` and inventory indexes.
- Modify `pubtator_link/repositories/review_rerag.py` and `pubtator_link/repositories/review_rerag_mappers.py` for inventory, summary, deletion, and cleanup methods.
- Modify `pubtator_link/services/review_context_service.py` or create `pubtator_link/services/review_index_lifecycle.py` for lifecycle orchestration. Prefer a new service if the implementation needs delete/cleanup policy.
- Modify `pubtator_link/api/routes/reviews.py` for inventory and gated lifecycle routes.
- Modify `pubtator_link/api/routes/dependencies.py` for lifecycle service/config dependencies.
- Modify `pubtator_link/config.py` for lifecycle TTL and destructive-operation settings.
- Modify `pubtator_link/mcp/facade.py`, `pubtator_link/mcp/resources.py`, and `tests/unit/mcp/test_mcp_facade.py` for new public tools and capability documentation.
- Add or extend tests under `tests/unit/`, `tests/unit/mcp/`, and `tests/test_routes/`.

## Task 1: Characterize FastMCP Output Schema Behavior

**Files:**
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Add failing output-schema tests for current high-use tools**

Add helper assertions to `tests/unit/mcp/test_mcp_facade.py`:

```python
def _tool_output_schema(tool: object) -> dict[str, object]:
    schema = getattr(tool, "output_schema", None) or getattr(tool, "outputSchema", None)
    if schema is None:
        schema = getattr(tool, "fn_metadata", None)
        schema = getattr(schema, "output_schema", None) if schema is not None else None
    assert isinstance(schema, dict), f"{tool!r} did not expose an output schema"
    return schema


def _assert_specific_object_schema(schema: dict[str, object], required: set[str]) -> None:
    assert schema.get("type") == "object"
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    assert required.issubset(properties)
    assert properties != {}
```

Then add:

```python
def test_high_use_mcp_tools_expose_specific_output_schemas() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    expected = {
        "pubtator.search_literature": {"success", "results"},
        "pubtator.preflight_review_sources": {"success", "coverage_hints"},
        "pubtator.index_review_evidence": {"success", "review_id", "preparation_status"},
        "pubtator.inspect_review_index": {"success", "review_id", "sources", "totals"},
        "pubtator.retrieve_review_context": {"success", "review_id", "context_pack"},
        "pubtator.retrieve_review_context_batch": {
            "success",
            "review_id",
            "merged_context_pack",
            "query_summaries",
        },
        "pubtator.get_review_passages_by_id": {"success", "review_id", "passages"},
        "pubtator.get_neighboring_review_passages": {"success", "review_id", "passages"},
        "pubtator.export_review_audit_bundle": {"success", "audit_bundle"},
    }

    for name, required in expected.items():
        _assert_specific_object_schema(_tool_output_schema(tools[name]), required)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: FAIL because one or more high-use tools expose no output schema or generic object schemas.

- [ ] **Step 3: Inspect FastMCP metadata shape**

Run: `uv run python - <<'PY'
from pubtator_link.mcp.facade import create_pubtator_mcp
mcp = create_pubtator_mcp()
for name in ("pubtator.search_literature", "pubtator.retrieve_review_context_batch"):
    tool = mcp._tool_manager._tools[name]
    print(name)
    for attr in ("output_schema", "outputSchema", "fn_metadata"):
        print(attr, type(getattr(tool, attr, None)), getattr(tool, attr, None))
PY`

Expected: output identifies whether FastMCP uses return annotations or explicit `output_schema` metadata in this installed version.

- [ ] **Step 4: Commit characterization tests**

```bash
git add tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "test: characterize mcp output schemas"
```

## Task 2: Add Typed MCP Output Models

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Create or modify: `pubtator_link/models/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_review_rerag_models.py`

- [ ] **Step 1: Add model tests for MCP wrapper shapes**

In `tests/unit/test_review_rerag_models.py`, add:

```python
from pubtator_link.models.review_rerag import (
    McpReviewAuditBundleResponse,
    PreparationStatus,
    ReviewAuditBundle,
    ReviewIndexTotals,
)


def test_mcp_review_audit_bundle_response_preserves_existing_wrapper_shape() -> None:
    bundle = ReviewAuditBundle(
        review_id="review-1",
        generated_at="2026-05-01T00:00:00Z",
        preparation_status=PreparationStatus(complete=1),
        totals=ReviewIndexTotals(pmid_count=1, source_count=1, passage_count=0),
        sources=[],
        failed_sources=[],
        coverage_distribution={"full_text": 1},
        resolver_attempts=[],
        passage_ids=[],
        stable_citation_keys={},
    )

    dumped = McpReviewAuditBundleResponse(audit_bundle=bundle).model_dump(mode="json")

    assert dumped["success"] is True
    assert dumped["audit_bundle"]["review_id"] == "review-1"
```

- [ ] **Step 2: Add adapter tests for typed returns**

In `tests/unit/mcp/test_mcp_service_adapters.py`, add or update assertions so review adapter functions return models or model-compatible dictionaries with the same keys. Use the existing fake services in that file and assert:

```python
assert set(response) >= {"success", "review_id", "preparation_status"}
assert set(batch_response) >= {"success", "review_id", "merged_context_pack"}
assert set(audit_response) == {"success", "audit_bundle"}
```

- [ ] **Step 3: Run focused tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: FAIL because `McpReviewAuditBundleResponse` and literature response models do not exist yet.

- [ ] **Step 4: Add MCP review wrapper model**

In `pubtator_link/models/review_rerag.py`, add near `ReviewAuditBundle`:

```python
class McpReviewAuditBundleResponse(BaseModel):
    """MCP wrapper preserving the existing audit bundle tool JSON shape."""

    success: bool = True
    audit_bundle: ReviewAuditBundle
```

- [ ] **Step 5: Add typed literature search models**

If no search model exists, create `pubtator_link/models/literature.py`:

```python
"""Typed literature search response models for REST and MCP surfaces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchLiteratureResult(BaseModel):
    pmid: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    publication_date: str | None = None
    authors: list[str] = Field(default_factory=list)
    snippets: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class SearchLiteratureResponse(BaseModel):
    success: bool = True
    query: str
    page: int = 1
    results: list[SearchLiteratureResult] = Field(default_factory=list)
    total: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 6: Update service adapters to construct typed models internally**

In `pubtator_link/mcp/service_adapters.py`, import the new models and change `export_review_audit_bundle_impl` to:

```python
async def export_review_audit_bundle_impl(
    *,
    service: ReviewAuditService,
    review_id: str,
) -> dict[str, Any]:
    bundle = await service.export_bundle(review_id)
    return McpReviewAuditBundleResponse(audit_bundle=bundle).model_dump(mode="json")
```

For `search_literature_impl`, preserve existing raw keys while returning a `SearchLiteratureResponse.model_dump(mode="json")`. Map unknown upstream fields into `raw` rather than dropping them.

- [ ] **Step 7: Run model and adapter tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: PASS.

- [ ] **Step 8: Commit typed models and adapters**

```bash
git add pubtator_link/models pubtator_link/mcp/service_adapters.py tests/unit/test_review_rerag_models.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: add typed mcp response models"
```

## Task 3: Wire FastMCP Output Schemas

**Files:**
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Return-annotate MCP tools with concrete models**

In `pubtator_link/mcp/tools/review.py`, import response models and change return annotations:

```python
from pubtator_link.models.review_rerag import (
    IndexReviewEvidenceResponse,
    InspectReviewIndexResponse,
    McpReviewAuditBundleResponse,
    PreflightReviewSourcesResponse,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
    ReviewPassageLookupResponse,
)
```

Use these return annotations on tool functions while keeping existing flat input arguments:

```python
async def inspect_review_index(...) -> InspectReviewIndexResponse:
    ...
```

If FastMCP requires actual model instances for schema inference, return model instances from adapters and let FastMCP serialize them. If it accepts explicit `output_schema`, keep adapter dictionaries and pass `output_schema=Model.model_json_schema()` to `@mcp.tool`.

- [ ] **Step 2: Return-annotate literature search**

In `pubtator_link/mcp/tools/literature.py`, import and use:

```python
from pubtator_link.models.literature import SearchLiteratureResponse
```

Annotate:

```python
async def search_literature(...) -> SearchLiteratureResponse:
    ...
```

If the adapter returns a dictionary, wrap it before return:

```python
return SearchLiteratureResponse.model_validate(response)
```

- [ ] **Step 3: Preserve flat input schema tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_common_mcp_tools_are_flat_and_unversioned tests/unit/mcp/test_mcp_facade.py::test_public_mcp_tools_use_flat_arguments_consistently -q`

Expected: PASS. If these fail, restore flat tool signatures and use explicit output-schema metadata instead of request-envelope models.

- [ ] **Step 4: Run output schema tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_high_use_mcp_tools_expose_specific_output_schemas -q`

Expected: PASS with concrete object schemas and required properties.

- [ ] **Step 5: Run MCP focused tests**

Run: `uv run pytest tests/unit/mcp -q`

Expected: PASS.

- [ ] **Step 6: Commit MCP schema wiring**

```bash
git add pubtator_link/mcp/tools pubtator_link/models tests/unit/mcp
git commit -m "feat: expose typed mcp output schemas"
```

## Task 4: Add Review Index Inventory Models And Config

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/config.py`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/test_review_rerag_config.py`

- [ ] **Step 1: Add failing model and config tests**

In `tests/unit/test_review_rerag_models.py`, add:

```python
from pubtator_link.models.review_rerag import (
    ListReviewIndexesResponse,
    PreparationStatus,
    ReviewIndexInventoryItem,
)


def test_review_index_inventory_item_defaults_are_safe() -> None:
    item = ReviewIndexInventoryItem(
        review_id="review-1",
        created_at="2026-05-01T00:00:00Z",
        updated_at="2026-05-01T00:00:00Z",
        preparation_status=PreparationStatus(complete=1),
    )

    assert item.pmid_count == 0
    assert item.source_count == 0
    assert item.passage_count == 0
    assert item.approximate_bytes == 0
    assert item.expires_at is None


def test_list_review_indexes_response_wraps_inventory_items() -> None:
    response = ListReviewIndexesResponse(indexes=[])

    assert response.success is True
    assert response.indexes == []
```

In `tests/unit/test_review_rerag_config.py`, add:

```python
from pubtator_link.config import ReviewReragConfig, ServerSettings


def test_review_index_lifecycle_config_defaults_are_hosted_safe() -> None:
    config = ReviewReragConfig.from_settings(ServerSettings())

    assert config.index_ttl_seconds is None
    assert config.enable_index_delete is False
    assert config.enable_index_cleanup_endpoint is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_rerag_config.py -q`

Expected: FAIL because lifecycle models and config fields do not exist.

- [ ] **Step 3: Add lifecycle models**

In `pubtator_link/models/review_rerag.py`, add:

```python
class ReviewIndexInventoryItem(BaseModel):
    """Inventory summary for one persisted review index."""

    review_id: str
    created_at: str
    updated_at: str
    expires_at: str | None = None
    preparation_status: PreparationStatus
    pmid_count: int = Field(default=0, ge=0)
    source_count: int = Field(default=0, ge=0)
    passage_count: int = Field(default=0, ge=0)
    failed_source_count: int = Field(default=0, ge=0)
    approximate_bytes: int = Field(default=0, ge=0)


class ListReviewIndexesResponse(BaseModel):
    success: bool = True
    indexes: list[ReviewIndexInventoryItem] = Field(default_factory=list)


class ReviewIndexSummaryResponse(BaseModel):
    success: bool = True
    index: ReviewIndexInventoryItem | None = None


class DeleteReviewIndexResponse(BaseModel):
    success: bool = True
    review_id: str
    deleted: bool


class CleanupExpiredReviewIndexesResponse(BaseModel):
    success: bool = True
    deleted_review_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add lifecycle config**

In `ServerSettings`, add:

```python
review_index_ttl_seconds: int | None = Field(
    default=None,
    ge=60,
    description="Optional TTL for stale review indexes; disabled when unset",
)
enable_review_index_delete: bool = Field(
    default=False,
    description="Enable destructive review index deletion routes/tools for private deployments",
)
enable_review_index_cleanup_endpoint: bool = Field(
    default=False,
    description="Enable manual review index cleanup endpoint for private deployments",
)
```

In `ReviewReragConfig`, add fields and map them in `from_settings`:

```python
index_ttl_seconds: int | None = None
enable_index_delete: bool = False
enable_index_cleanup_endpoint: bool = False
```

- [ ] **Step 5: Run model and config tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_rerag_config.py -q`

Expected: PASS.

- [ ] **Step 6: Commit lifecycle models and config**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/config.py tests/unit/test_review_rerag_models.py tests/unit/test_review_rerag_config.py
git commit -m "feat: add review index lifecycle models"
```

## Task 5: Add Inventory Schema And Repository Methods

**Files:**
- Modify: `pubtator_link/db/review_schema.sql`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag_mappers.py`
- Test: `tests/unit/test_review_schema_sql.py`
- Test: `tests/unit/test_review_rerag_repository.py`
- Test: `tests/unit/test_review_rerag_mappers.py`

- [ ] **Step 1: Add failing schema tests**

In `tests/unit/test_review_schema_sql.py`, add:

```python
def test_schema_tracks_review_inventory_timestamps() -> None:
    assert "updated_at timestamptz not null default now()" in SCHEMA
    assert "reviews_updated_at_idx" in SCHEMA
```

- [ ] **Step 2: Add failing repository protocol tests using fake rows**

In `tests/unit/test_review_rerag_mappers.py`, add a row-mapper test:

```python
from pubtator_link.repositories.review_rerag_mappers import _review_inventory_item_from_row


def test_review_inventory_mapper_builds_item_from_aggregate_row() -> None:
    row = {
        "review_id": "review-1",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T01:00:00Z",
        "queued": 0,
        "running": 0,
        "complete": 1,
        "partial": 0,
        "failed": 0,
        "pmid_count": 1,
        "source_count": 1,
        "passage_count": 2,
        "failed_source_count": 0,
        "approximate_bytes": 1234,
    }

    item = _review_inventory_item_from_row(row, ttl_seconds=3600)

    assert item.review_id == "review-1"
    assert item.preparation_status.complete == 1
    assert item.approximate_bytes == 1234
    assert item.expires_at is not None
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_mappers.py -q`

Expected: FAIL because schema and mapper are missing.

- [ ] **Step 4: Update schema**

In `pubtator_link/db/review_schema.sql`, change `reviews` to include:

```sql
create table if not exists reviews (
    review_id text primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists reviews_updated_at_idx
    on reviews(updated_at);
```

Update write queries in `PostgresReviewReragRepository` so `reviews.updated_at` changes when jobs, attempts, passages, or audit events change. Use:

```sql
update reviews
set updated_at = now()
where review_id = $1
```

after successful child-table writes.

- [ ] **Step 5: Add inventory mapper**

In `pubtator_link/repositories/review_rerag_mappers.py`, add:

```python
from datetime import timedelta

from pubtator_link.models.review_rerag import ReviewIndexInventoryItem


def _review_inventory_item_from_row(
    row: Mapping[str, object],
    *,
    ttl_seconds: int | None,
) -> ReviewIndexInventoryItem:
    updated_at = row["updated_at"]
    expires_at = None
    if ttl_seconds is not None and hasattr(updated_at, "__add__"):
        expires_at = updated_at + timedelta(seconds=ttl_seconds)  # type: ignore[operator]
    return ReviewIndexInventoryItem(
        review_id=str(row["review_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(updated_at),
        expires_at=str(expires_at) if expires_at is not None else None,
        preparation_status=_preparation_status_from_row(row),
        pmid_count=int(row.get("pmid_count") or 0),
        source_count=int(row.get("source_count") or 0),
        passage_count=int(row.get("passage_count") or 0),
        failed_source_count=int(row.get("failed_source_count") or 0),
        approximate_bytes=int(row.get("approximate_bytes") or 0),
    )
```

- [ ] **Step 6: Add repository methods**

Extend `ReviewReragRepository` and `PostgresReviewReragRepository` with:

```python
async def list_review_indexes(
    self,
    *,
    limit: int = 50,
    offset: int = 0,
    ttl_seconds: int | None = None,
) -> list[ReviewIndexInventoryItem]:
    ...

async def get_review_index_summary(
    self,
    review_id: str,
    *,
    ttl_seconds: int | None = None,
) -> ReviewIndexInventoryItem | None:
    ...

async def delete_review_index(self, review_id: str) -> bool:
    ...

async def cleanup_expired_review_indexes(self, *, ttl_seconds: int) -> list[str]:
    ...
```

Use aggregate SQL over `reviews`, `review_preparation_jobs`, `review_passages`,
and `full_text_retrieval_attempts`. Delete child tables in this order:
`review_audit_events`, `full_text_retrieval_attempts`, `review_passages`,
`review_preparation_jobs`, `reviews`.

- [ ] **Step 7: Run repository tests**

Run: `uv run pytest tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_mappers.py tests/unit/test_review_rerag_repository.py -q`

Expected: PASS.

- [ ] **Step 8: Commit repository lifecycle support**

```bash
git add pubtator_link/db/review_schema.sql pubtator_link/repositories tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_mappers.py tests/unit/test_review_rerag_repository.py
git commit -m "feat: add review index inventory repository"
```

## Task 6: Add Lifecycle Service, REST Routes, And MCP Tools

**Files:**
- Create: `pubtator_link/services/review_index_lifecycle.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Test: `tests/test_routes/test_reviews.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Add failing route and facade tests**

In `tests/unit/mcp/test_mcp_facade.py`, add the new non-destructive tools to `EXPECTED_PUBLIC_TOOL_NAMES`:

```python
"pubtator.list_review_indexes",
"pubtator.get_review_index_summary",
```

Add assertions that `pubtator.delete_review_index` is absent by default.

In `tests/test_routes/test_reviews.py`, add route tests that call:

```python
client.get("/api/reviews")
client.get("/api/reviews/review-1/summary")
client.delete("/api/reviews/review-1")
client.post("/api/reviews/cleanup-expired")
```

Expected defaults: inventory routes return `200`, destructive routes return `403`.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_facade.py -q`

Expected: FAIL because routes and tools are missing.

- [ ] **Step 3: Add lifecycle service**

Create `pubtator_link/services/review_index_lifecycle.py`:

```python
from __future__ import annotations

from pubtator_link.config import ReviewReragConfig
from pubtator_link.models.review_rerag import (
    CleanupExpiredReviewIndexesResponse,
    DeleteReviewIndexResponse,
    ListReviewIndexesResponse,
    ReviewIndexSummaryResponse,
)
from pubtator_link.repositories.review_rerag import ReviewReragRepository


class ReviewIndexLifecycleService:
    def __init__(self, repository: ReviewReragRepository, config: ReviewReragConfig) -> None:
        self.repository = repository
        self.config = config

    async def list_indexes(self, *, limit: int = 50, offset: int = 0) -> ListReviewIndexesResponse:
        indexes = await self.repository.list_review_indexes(
            limit=limit,
            offset=offset,
            ttl_seconds=self.config.index_ttl_seconds,
        )
        return ListReviewIndexesResponse(indexes=indexes)

    async def get_summary(self, review_id: str) -> ReviewIndexSummaryResponse:
        index = await self.repository.get_review_index_summary(
            review_id,
            ttl_seconds=self.config.index_ttl_seconds,
        )
        return ReviewIndexSummaryResponse(index=index)

    async def delete_index(self, review_id: str) -> DeleteReviewIndexResponse:
        if not self.config.enable_index_delete:
            raise PermissionError("Review index deletion is disabled")
        deleted = await self.repository.delete_review_index(review_id)
        return DeleteReviewIndexResponse(review_id=review_id, deleted=deleted)

    async def cleanup_expired(self) -> CleanupExpiredReviewIndexesResponse:
        if not self.config.enable_index_cleanup_endpoint:
            raise PermissionError("Review index cleanup endpoint is disabled")
        if self.config.index_ttl_seconds is None:
            return CleanupExpiredReviewIndexesResponse(deleted_review_ids=[])
        deleted = await self.repository.cleanup_expired_review_indexes(
            ttl_seconds=self.config.index_ttl_seconds
        )
        return CleanupExpiredReviewIndexesResponse(deleted_review_ids=deleted)
```

- [ ] **Step 4: Add dependencies and REST routes**

Add a dependency for `ReviewIndexLifecycleService`. In route handlers, translate
`PermissionError` to `403` using the existing error-handling pattern or explicit
`HTTPException(status_code=403, detail=str(exc))`.

Add:

```python
@router.get("", response_model=ListReviewIndexesResponse, operation_id="list_review_indexes")
async def list_review_indexes(...): ...

@router.get("/{review_id}/summary", response_model=ReviewIndexSummaryResponse, operation_id="get_review_index_summary")
async def get_review_index_summary(...): ...
```

and gated destructive routes.

- [ ] **Step 5: Add MCP tools**

Register:

```python
@mcp.tool(name="pubtator.list_review_indexes", title="List Review Indexes", annotations=READ_ONLY_OPEN_WORLD)
async def list_review_indexes(limit: int = 50, offset: int = 0) -> ListReviewIndexesResponse:
    service = await get_review_index_lifecycle_service()
    return await list_review_indexes_impl(service=service, limit=limit, offset=offset)


@mcp.tool(name="pubtator.get_review_index_summary", title="Get Review Index Summary", annotations=READ_ONLY_OPEN_WORLD)
async def get_review_index_summary(review_id: str) -> ReviewIndexSummaryResponse:
    service = await get_review_index_lifecycle_service()
    return await get_review_index_summary_impl(service=service, review_id=review_id)
```

Do not register `delete_review_index` in the public facade by default.

- [ ] **Step 6: Run focused route and MCP tests**

Run: `uv run pytest tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: PASS.

- [ ] **Step 7: Commit lifecycle public surfaces**

```bash
git add pubtator_link/services/review_index_lifecycle.py pubtator_link/api/routes pubtator_link/mcp tests/test_routes/test_reviews.py tests/unit/mcp
git commit -m "feat: add review index lifecycle surfaces"
```

## Task 7: Final Verification And Review Memo Update

**Files:**
- Modify: `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`

- [ ] **Step 1: Update review memo implementation status**

Only after code and tests above pass, update the review memo checklist so the
typed MCP output schemas item and the review index inventory/TTL cleanup item
are marked complete. Leave the GRADE, Europe PMC, and `candidate_fast` items
unchecked in this plan.

Add a short note that Phase 2 remains GRADE-style evidence certainty storage and
Phase 3 remains Europe PMC fallback plus public `candidate_fast` removal.

- [ ] **Step 2: Run focused verification**

Run: `uv run pytest tests/unit/mcp tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 3: Run required repo verification**

Run: `make ci-local`

Expected: PASS.

- [ ] **Step 4: Commit docs update**

```bash
git add docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md
git commit -m "docs: mark review schema lifecycle roadmap items complete"
```
