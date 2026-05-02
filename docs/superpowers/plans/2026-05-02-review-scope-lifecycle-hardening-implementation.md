# Review Scope And Lifecycle Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add session-scoped review retrieval, durable queue deduplication, dry-run/wait indexing ergonomics, and lifecycle documentation without exposing destructive hosted MCP operations.

**Architecture:** Add `review_session_sources` as a link table between research sessions and prepared sources, then thread optional `session_id` through repository queries, services, REST routes, and MCP tools. Centralize index enqueue planning so REST and MCP share dry-run, durable dedup counters, and bounded wait behavior.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, asyncpg, MCP FastMCP, pytest, Ruff, mypy, uv, Makefile.

---

## File Structure

- Modify `pubtator_link/db/review_schema.sql` and `pubtator_link/db/migrations/0002_review_schema_drift_repair.sql`: add `review_session_sources`.
- Modify `pubtator_link/models/review_rerag.py`: request/response fields, enqueue status literals, scoped status lists, section normalization docs.
- Modify `pubtator_link/repositories/review_rerag.py`: durable enqueue result, session source links, session-aware SQL filters.
- Modify `pubtator_link/services/review_preparation_queue.py`: return durable enum-like enqueue results and keep in-memory dedup as a fast path.
- Create `pubtator_link/services/review_indexing.py`: shared dry-run/enqueue/wait orchestration.
- Modify `pubtator_link/services/research_session.py`: link staged queued candidates to session sources.
- Modify `pubtator_link/services/review_context_service.py`: session validation and scoped retrieval/status responses.
- Modify `pubtator_link/services/review_audit.py`: optional session-scoped bundle export.
- Modify `pubtator_link/api/routes/reviews.py`: expose session/dry-run/wait fields via REST.
- Modify `pubtator_link/mcp/tools/review.py` and `pubtator_link/mcp/service_adapters.py`: expose flat MCP args, stop advertising `prepare_mode`, preserve compatibility in models.
- Modify `pubtator_link/mcp/resources.py` and `pubtator_link/services/workflow_help.py`: document session workflow, relation discovery, deprecated fields, and lowercase section taxonomy.
- Test files: `tests/unit/test_review_schema_sql.py`, `tests/unit/test_review_rerag_repository.py`, `tests/unit/test_review_preparation_queue.py`, `tests/unit/test_review_context_service.py`, `tests/unit/test_review_audit.py`, `tests/test_routes/test_reviews.py`, `tests/unit/mcp/test_review_rerag_mcp.py`, `tests/unit/mcp/test_mcp_service_adapters.py`, `tests/unit/test_workflow_help.py`.

### Task 1: Session Source Schema

**Files:**
- Modify: `pubtator_link/db/review_schema.sql`
- Modify: `pubtator_link/db/migrations/0002_review_schema_drift_repair.sql`
- Test: `tests/unit/test_review_schema_sql.py`

- [ ] **Step 1: Write failing schema tests**

Add:

```python
def test_review_schema_defines_session_source_links() -> None:
    schema = REVIEW_SCHEMA_SQL.lower()

    assert "create table if not exists review_session_sources" in schema
    assert "primary key(review_id, session_id, source_id)" in schema
    assert "references review_research_sessions(review_id, session_id)" in schema
    assert "references review_preparation_jobs(review_id, source_id)" in schema


def test_drift_repair_migration_defines_session_source_links() -> None:
    migration = DRIFT_REPAIR_SQL.lower()

    assert "create table if not exists review_session_sources" in migration
    assert "primary key(review_id, session_id, source_id)" in migration
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_schema_sql.py -q`
Expected: FAIL because `review_session_sources` is absent.

- [ ] **Step 3: Add schema table**

Add the same table to schema and drift repair migration:

```sql
create table if not exists review_session_sources (
    review_id text not null,
    session_id text not null,
    source_id text not null,
    created_at timestamptz not null default now(),
    primary key(review_id, session_id, source_id),
    foreign key(review_id, session_id)
        references review_research_sessions(review_id, session_id)
        on delete cascade,
    foreign key(review_id, source_id)
        references review_preparation_jobs(review_id, source_id)
        on delete cascade
);

create index if not exists review_session_sources_source_idx
    on review_session_sources(review_id, source_id);
```

- [ ] **Step 4: Run tests to verify green**

Run: `uv run pytest tests/unit/test_review_schema_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/db/review_schema.sql pubtator_link/db/migrations/0002_review_schema_drift_repair.sql tests/unit/test_review_schema_sql.py
git commit -m "feat: add review session source links"
```

### Task 2: Durable Queue Dedup Results

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/services/review_preparation_queue.py`
- Test: `tests/unit/test_review_preparation_queue.py`
- Test: `tests/unit/test_review_rerag_repository.py`

- [ ] **Step 1: Write failing queue tests**

Add tests that expect `enqueue_pmid()` to return strings:

```python
@pytest.mark.asyncio
async def test_enqueue_pmid_returns_already_indexed_without_queueing() -> None:
    repository = RecordingRepository()
    repository.next_enqueue_result = "already_indexed"
    queue = ReviewPreparationQueue(_config(), repository, RecordingPreparation())

    result = await queue.enqueue_pmid("review-1", "40234174")

    assert result == "already_indexed"
    assert queue._queue.empty()


@pytest.mark.asyncio
async def test_enqueue_pmid_returns_already_queued_for_memory_duplicate() -> None:
    repository = SlowRecordingRepository()
    queue = ReviewPreparationQueue(_config(), repository, RecordingPreparation())

    results = await asyncio.gather(
        queue.enqueue_pmid("review-1", "40234174"),
        queue.enqueue_pmid("review-1", "40234174"),
    )

    assert sorted(results) == ["already_queued", "newly_queued"]
```

Update `RecordingRepository.enqueue_preparation_job()` in the test to return `self.next_enqueue_result`.

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_preparation_queue.py -q`
Expected: FAIL because queue methods return booleans.

- [ ] **Step 3: Add model literals and queue return handling**

In `models/review_rerag.py` add:

```python
PreparationEnqueueResult = Literal[
    "newly_queued",
    "already_queued",
    "already_running",
    "already_indexed",
    "previously_failed_requeued",
]
```

In `review_preparation_queue.py`, return `PreparationEnqueueResult`; only put work on the in-memory queue for `"newly_queued"` and `"previously_failed_requeued"`.

- [ ] **Step 4: Add repository durable status classification test**

Add:

```python
@pytest.mark.asyncio
async def test_enqueue_preparation_job_returns_already_indexed_for_terminal_job() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {"status": "complete"},
        {"queued": 0, "running": 0, "complete": 1, "partial": 0, "failed": 0},
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    result = await repository.enqueue_preparation_job("review-1", "PMID:1", "pubtator_full_bioc")

    assert result == "already_indexed"
    assert not any("insert into review_preparation_jobs" in sql.lower() for sql, _ in connection.executed)
```

- [ ] **Step 5: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_rerag_repository.py::test_enqueue_preparation_job_returns_already_indexed_for_terminal_job -q`
Expected: FAIL because repository returns `PreparationStatus`.

- [ ] **Step 6: Implement durable classification**

In `enqueue_preparation_job`, first select current status with `for update`. Return:

```python
if status in {"complete", "partial"}:
    return "already_indexed"
if status == "queued":
    return "already_queued"
if status == "running":
    return "already_running"
if status == "failed":
    # update status to queued and return previously_failed_requeued
```

Insert a new job only when no row exists and return `"newly_queued"`.

- [ ] **Step 7: Run focused tests**

Run: `uv run pytest tests/unit/test_review_preparation_queue.py tests/unit/test_review_rerag_repository.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/repositories/review_rerag.py pubtator_link/services/review_preparation_queue.py tests/unit/test_review_preparation_queue.py tests/unit/test_review_rerag_repository.py
git commit -m "feat: make review enqueue dedup durable"
```

### Task 3: Session Source Repository Scope

**Files:**
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag_mappers.py`
- Test: `tests/unit/test_review_rerag_repository.py`

- [ ] **Step 1: Write failing repository tests**

Add tests for linking and session SQL:

```python
@pytest.mark.asyncio
async def test_link_review_session_source_inserts_link() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.link_review_session_source("review-1", "session-1", "PMID:40234174")

    sql, args = connection.executed[0]
    assert "insert into review_session_sources" in sql.lower()
    assert args == ("review-1", "session-1", "PMID:40234174")


@pytest.mark.asyncio
async def test_search_passages_with_session_joins_session_sources() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.search_passages("review-1", "MEFV", session_id="session-1")

    sql, args = connection.executed[0]
    assert "review_session_sources" in sql.lower()
    assert args[7] == "session-1"
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_rerag_repository.py -q`
Expected: FAIL because methods/signatures are missing.

- [ ] **Step 3: Add repository methods and session filters**

Add protocol and implementation methods:

```python
async def link_review_session_source(self, review_id: str, session_id: str, source_id: str) -> None: ...
async def research_session_exists(self, review_id: str, session_id: str) -> bool: ...
async def session_linked_source_ids(self, review_id: str, session_id: str) -> list[str]: ...
```

Thread `session_id: str | None = None` through `search_passages`, `get_passages_by_id`, `neighboring_passages`, `list_review_sources`, `list_failed_sources`, `review_totals`, `available_sections`, `indexed_pmids`, and `passage_ids`.

Use this SQL shape where passage/source rows are read:

```sql
and (
    $session_id::text is null
    or exists (
        select 1
        from review_session_sources rss
        where rss.review_id = review_passages.review_id
          and rss.session_id = $session_id
          and rss.source_id = review_passages.source_id
    )
)
```

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/test_review_rerag_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/repositories/review_rerag.py pubtator_link/repositories/review_rerag_mappers.py tests/unit/test_review_rerag_repository.py
git commit -m "feat: scope review repository reads by session"
```

### Task 4: Indexing Orchestration Dry Run And Wait

**Files:**
- Create: `pubtator_link/services/review_indexing.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Test: `tests/unit/test_review_indexing.py`

- [ ] **Step 1: Write failing service tests**

Create tests:

```python
@pytest.mark.asyncio
async def test_dry_run_reports_counts_without_enqueueing() -> None:
    repository = FakeIndexRepository(existing={"PMID:1": "complete"})
    queue = FakeQueue()
    service = ReviewIndexingService(repository=repository, queue=queue)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1", "2"], dry_run=True),
    )

    assert response.dry_run is True
    assert response.already_indexed == 1
    assert response.estimated_source_count == 2
    assert queue.calls == []


@pytest.mark.asyncio
async def test_wait_for_terminal_times_out_with_retry_after() -> None:
    repository = FakeIndexRepository(existing={"PMID:1": "queued"})
    queue = FakeQueue(result="already_queued")
    service = ReviewIndexingService(repository=repository, queue=queue, poll_interval_ms=1)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1"], wait_for_status="terminal", timeout_ms=2),
    )

    assert response.timed_out is True
    assert response.retry_after_ms is not None
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_indexing.py -q`
Expected: FAIL because the service does not exist.

- [ ] **Step 3: Add request/response fields**

Add to `IndexReviewEvidenceRequest`:

```python
session_id: str | None = Field(default=None, min_length=1)
wait_for_completion: bool = False
wait_for_status: Literal["complete", "complete_or_partial", "terminal"] | None = None
timeout_ms: int = Field(default=0, ge=0, le=120_000)
dry_run: bool = False
```

Add to `IndexReviewEvidenceResponse`:

```python
dry_run: bool = False
waited_ms: int = 0
timed_out: bool = False
estimated_queue_position: int | None = None
estimated_source_count: int = 0
already_indexed: int = 0
already_queued: int = 0
already_running: int = 0
newly_queued: int = 0
previously_failed_requeued: int = 0
```

- [ ] **Step 4: Implement service**

`ReviewIndexingService.index_review_evidence()` should:

1. Validate unknown `session_id` with `repository.research_session_exists`.
2. Build source IDs from PMIDs and curated URLs.
3. For `dry_run`, call repository status inspection only.
4. For mutation, call queue methods and link sources when `session_id` is present.
5. Poll `repository.preparation_status(review_id, session_id=session_id)` until terminal predicate or timeout.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_review_indexing.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_indexing.py tests/unit/test_review_indexing.py
git commit -m "feat: add review indexing orchestration"
```

### Task 5: Session-Scoped Retrieval Services

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing service tests**

Add:

```python
@pytest.mark.asyncio
async def test_retrieve_context_rejects_unknown_session() -> None:
    repository = FakeReviewRepository(session_exists=False)
    service = ReviewContextService(repository)

    with pytest.raises(ValueError, match="session_not_found"):
        await service.retrieve_context(
            "review-1",
            RetrieveReviewContextRequest(question="MEFV", session_id="missing"),
        )


@pytest.mark.asyncio
async def test_retrieve_context_adds_scoped_preparation_lists() -> None:
    repository = FakeReviewRepository(session_exists=True)
    service = ReviewContextService(repository)

    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(question="MEFV", session_id="session-1"),
    )

    assert repository.search_calls[0]["session_id"] == "session-1"
    assert response.prepared_pmids == ["1"]
    assert response.still_preparing_pmids == ["2"]
    assert response.failed_pmids == ["3"]
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_context_service.py -q`
Expected: FAIL because models/services do not accept `session_id`.

- [ ] **Step 3: Add model fields and service validation**

Add `session_id` to retrieval, batch, lookup, neighbor, inspect, and audit request models. Add preparation lists to retrieve and batch responses:

```python
prepared_pmids: list[str] = Field(default_factory=list)
still_preparing_pmids: list[str] = Field(default_factory=list)
failed_pmids: list[str] = Field(default_factory=list)
```

Add a private `_ensure_session_exists(review_id, session_id)` and call it before scoped operations.

- [ ] **Step 4: Pass session_id into repository calls**

Thread `session_id=request.session_id` through search, diagnostics, status, lookup, neighbors, inspect, and batch retrieval.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_context_diagnostics.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_context_service.py tests/unit/test_review_context_service.py
git commit -m "feat: enforce session-scoped review retrieval"
```

### Task 6: REST And MCP Surface

**Files:**
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/test_routes/test_reviews.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing REST/MCP tests**

Add tests asserting:

```python
assert "session_id" in retrieve_review_context_tool.parameters["properties"]
assert "wait_for_completion" in index_review_evidence_tool.parameters["properties"]
assert "dry_run" in index_review_evidence_tool.parameters["properties"]
assert "prepare_mode" not in index_review_evidence_tool.parameters["properties"]
```

Add route tests that POST `{"session_id": "session-1", "dry_run": true}` to index and retrieval bodies and assert the fake service receives `session_id`.

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py -q`
Expected: FAIL because public signatures are not updated.

- [ ] **Step 3: Update REST routes**

Replace inline queue logic in `index_review_evidence` with `ReviewIndexingService`. Add `session_id` query/body support for inspect, audit, retrieve, lookup, neighbor, and batch routes following existing route style.

- [ ] **Step 4: Update MCP tools**

Expose new flat arguments. Keep `prepare_mode` accepted in `IndexReviewEvidenceRequest` for REST/model compatibility, but remove it from `pubtator.index_review_evidence` MCP function signature and descriptions.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/api/routes/reviews.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/service_adapters.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: expose session-scoped review lifecycle tools"
```

### Task 7: Audit Bundle And Workflow Documentation

**Files:**
- Modify: `pubtator_link/services/review_audit.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Test: `tests/unit/test_review_audit.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/test_workflow_help.py`

- [ ] **Step 1: Write failing tests**

Add assertions that:

```python
assert bundle.session_id == "session-1"
assert "pubtator.find_entity_relations" in WorkflowHelpService().get_help("clinical_genetics_review").tool_sequence
assert capabilities["schema_policy"]["deprecated_fields"][0]["field"] == "prepare_mode"
assert capabilities["section_taxonomy"]["canonical_case"] == "lowercase"
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_audit.py tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py -q`
Expected: FAIL because audit/workflow metadata is missing.

- [ ] **Step 3: Scope audit service**

Add `session_id` to `ReviewAuditBundle` and pass `session_id` into repository list/status calls. Filter research sessions to the selected session when provided.

- [ ] **Step 4: Update capabilities and workflow help**

Add:

```python
"schema_policy": {
    "argument_style": "flat",
    "deprecated_fields": [
        {"field": "prepare_mode", "status": "deprecated", "replacement": "omit"},
    ],
},
"section_taxonomy": {
    "canonical_case": "lowercase",
    "normalization": "lowercase ASCII with non-alphanumeric separators collapsed to underscores",
},
"citation_keys": {
    "stable_citation_key": "Stable across calls and snapshots for the same passage_id.",
},
```

Insert `pubtator.find_entity_relations` after entity search in workflow help.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_review_audit.py tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/review_audit.py pubtator_link/mcp/resources.py pubtator_link/services/workflow_help.py tests/unit/test_review_audit.py tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py
git commit -m "docs: document review lifecycle capabilities"
```

### Task 8: Final Verification

**Files:**
- No direct edits.

- [ ] **Step 1: Run formatting**

Run: `make format`
Expected: exit 0.

- [ ] **Step 2: Run local CI**

Run: `make ci-local`
Expected: exit 0.

- [ ] **Step 3: Inspect git status**

Run: `git status --short`
Expected: no uncommitted files except user-owned unrelated work already present before this plan.

- [ ] **Step 4: Commit verification-only fixes if needed**

If formatting changed files:

```bash
git add <formatted-files>
git commit -m "style: format review lifecycle hardening"
```

## Self-Review

Spec coverage:
- `session_id` across index, inspect, retrieve, lookup, neighbors, and audit: Tasks 3, 5, 6, 7.
- durable dedup: Task 2.
- `wait_for_completion`, `wait_for_status`, `timeout_ms`, `dry_run`: Task 4 and Task 6.
- `prepare_mode` de-advertising with compatibility: Task 6 and Task 7.
- hosted MCP non-destructive: Task 6 keeps delete/cleanup out of MCP and preserves non-destructive annotations.
- relation discovery promotion and lowercase section taxonomy: Task 7.

Placeholder scan: no task depends on an unspecified file or unnamed test command.

Type consistency: `session_id`, `PreparationEnqueueResult`, `wait_for_status`, and response counter names match across model, service, REST, and MCP tasks.
