# Research Session Staging Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit research-session staging that turns a query or PMID list into a transparent review manifest with candidate PMIDs, coverage hints, queued preparation jobs, and pollable status.

**Architecture:** Add review-session models and tables, implement a focused `ResearchSessionService` that reuses PubTator search, source preflight, and `ReviewPreparationQueue`, then expose the workflow through REST and MCP. Session staging stores metadata and decisions only; passage text continues to live in the existing review index.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic, asyncpg/PostgreSQL, pytest, pytest-asyncio, Ruff, mypy, Makefile targets.

---

## File Structure

- Modify `pubtator_link/models/review_rerag.py` for research-session request and response models.
- Modify `pubtator_link/db/review_schema.sql` for session manifest tables.
- Modify `pubtator_link/repositories/review_rerag_mappers.py` for session row mapping helpers.
- Modify `pubtator_link/repositories/review_rerag.py` for session persistence methods.
- Create `pubtator_link/services/research_session.py` for orchestration.
- Modify `pubtator_link/api/routes/dependencies.py` to construct and inject `ResearchSessionService`.
- Modify `pubtator_link/api/routes/reviews.py` for staging REST routes.
- Modify `pubtator_link/mcp/service_adapters.py` and `pubtator_link/mcp/tools/review.py` for staging MCP tools.
- Modify `pubtator_link/mcp/resources.py` to describe the staged research workflow.
- Modify `pubtator_link/services/review_audit.py` to include session manifests in audit bundles.
- Add tests under `tests/unit/`, `tests/test_routes/`, and `tests/unit/mcp/`.

## Task 1: Add Research Session Models And SQL Schema

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/db/review_schema.sql`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/test_review_schema_sql.py`

- [ ] **Step 1: Write failing model tests**

Add to `tests/unit/test_review_rerag_models.py`:

```python
import pytest
from pydantic import ValidationError

from pubtator_link.models.review_rerag import (
    ResearchSessionCandidate,
    StageResearchSessionRequest,
)


def test_stage_research_session_request_accepts_query_and_limits() -> None:
    request = StageResearchSessionRequest(
        query="familial mediterranean fever colchicine guideline",
        max_candidates=12,
        stage_full_text=True,
    )

    assert request.query == "familial mediterranean fever colchicine guideline"
    assert request.pmids == []
    assert request.max_candidates == 12
    assert request.stage_full_text is True


def test_stage_research_session_request_requires_query_or_pmids() -> None:
    with pytest.raises(ValidationError):
        StageResearchSessionRequest()


def test_research_session_candidate_records_decision_and_status() -> None:
    candidate = ResearchSessionCandidate(
        pmid="37747561",
        rank=1,
        status="queued",
        decision_reason="selected_by_rank",
    )

    assert candidate.pmid == "37747561"
    assert candidate.status == "queued"
    assert candidate.decision_reason == "selected_by_rank"
```

- [ ] **Step 2: Write failing schema tests**

Add to `tests/unit/test_review_schema_sql.py`:

```python
def test_schema_defines_research_session_tables() -> None:
    assert "create table if not exists review_research_sessions" in SCHEMA
    assert "create table if not exists review_research_session_candidates" in SCHEMA
    assert "review_research_sessions_review_id_idx" in SCHEMA
    assert "review_research_session_candidates_session_idx" in SCHEMA
    assert "unique(review_id, session_id, pmid)" in SCHEMA
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py -q`

Expected: FAIL because the models and tables are not defined.

- [ ] **Step 4: Add model definitions**

In `pubtator_link/models/review_rerag.py`, add:

```python
ResearchSessionStatus = Literal["active", "complete", "partial", "failed"]
ResearchSessionCandidateStatus = Literal[
    "candidate",
    "preflighted",
    "queued",
    "abstract_ready",
    "full_text_ready",
    "abstract_only",
    "metadata_only",
    "failed",
    "skipped",
]
ResearchSessionDecisionReason = Literal[
    "selected_by_rank",
    "explicit_pmid",
    "duplicate",
    "over_candidate_limit",
    "coverage_unknown",
    "metadata_only",
    "preflight_failed",
    "already_indexed",
    "queue_rejected",
]


class StageResearchSessionRequest(BaseModel):
    """Request to stage a transparent research session."""

    session_id: str | None = Field(default=None, min_length=1)
    query: str | None = Field(default=None, min_length=1)
    pmids: list[str] = Field(default_factory=list)
    page: int = Field(default=1, ge=1, le=1000)
    sort: str | None = None
    filters: str | None = None
    publication_types: list[str] = Field(default_factory=list)
    year_min: int | None = Field(default=None, ge=1800, le=2030)
    year_max: int | None = Field(default=None, ge=1800, le=2030)
    sections: list[str] = Field(default_factory=list)
    max_candidates: int = Field(default=20, ge=1, le=100)
    stage_full_text: bool = True

    @model_validator(mode="after")
    def require_query_or_pmids(self) -> Self:
        if not self.query and not self.pmids:
            raise ValueError("query or pmids is required")
        return self


class ResearchSessionCandidate(BaseModel):
    """One PMID candidate in a staged research session."""

    pmid: str
    rank: int | None = Field(default=None, ge=1)
    title: str | None = None
    status: ResearchSessionCandidateStatus = "candidate"
    decision_reason: ResearchSessionDecisionReason = "selected_by_rank"
    coverage_hint: SourceCoverageHint | None = None
    source_id: str | None = None
    error: str | None = None


class ResearchSessionManifest(BaseModel):
    """Transparent manifest for one research session."""

    session_id: str
    review_id: str
    query: str | None = None
    status: ResearchSessionStatus = "active"
    candidates: list[ResearchSessionCandidate] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
    queued_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    preparation_status: PreparationStatus | None = None
    created_at: str | None = None
    updated_at: str | None = None


class StageResearchSessionResponse(BaseModel):
    success: bool = True
    manifest: ResearchSessionManifest
    meta: dict[str, Any] = Field(default_factory=dict, serialization_alias="_meta")


class ResearchSessionStatusResponse(BaseModel):
    success: bool = True
    manifest: ResearchSessionManifest


class ListResearchSessionsResponse(BaseModel):
    success: bool = True
    sessions: list[ResearchSessionManifest] = Field(default_factory=list)
```

Update the existing typing import to include `Any`:

```python
from typing import Any, Literal, Self
```

- [ ] **Step 5: Add SQL tables**

Add to `pubtator_link/db/review_schema.sql` after `review_audit_events`:

```sql
create table if not exists review_research_sessions (
    session_id text not null,
    review_id text not null references reviews(review_id),
    query text,
    status text not null default 'active',
    request jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(review_id, session_id)
);

create index if not exists review_research_sessions_review_id_idx
    on review_research_sessions(review_id, updated_at);

create table if not exists review_research_session_candidates (
    review_id text not null,
    session_id text not null,
    pmid text not null,
    rank integer,
    title text,
    status text not null,
    decision_reason text not null,
    coverage_hint jsonb,
    source_id text,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(review_id, session_id, pmid),
    unique(review_id, session_id, pmid),
    foreign key(review_id, session_id)
        references review_research_sessions(review_id, session_id)
);

create index if not exists review_research_session_candidates_session_idx
    on review_research_session_candidates(review_id, session_id, rank, pmid);

create unique index if not exists review_research_session_candidates_unique_pmid_idx
    on review_research_session_candidates(review_id, session_id, pmid);
```

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py -q`

Expected: PASS.

- [ ] **Step 7: Commit models and schema**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/db/review_schema.sql tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py
git commit -m "feat: add research session models"
```

## Task 2: Add Repository Persistence For Session Manifests

**Files:**
- Modify: `pubtator_link/repositories/review_rerag_mappers.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Test: `tests/unit/test_review_rerag_mappers.py`
- Test: `tests/unit/test_review_rerag_repository.py`

- [ ] **Step 1: Write failing mapper test**

Add to `tests/unit/test_review_rerag_mappers.py`:

```python
from pubtator_link.repositories.review_rerag_mappers import _research_session_candidate_from_row


def test_research_session_candidate_mapper_parses_coverage_hint() -> None:
    row = {
        "pmid": "37747561",
        "rank": 1,
        "title": "Colchicine in familial Mediterranean fever",
        "status": "queued",
        "decision_reason": "selected_by_rank",
        "coverage_hint": {
            "pmid": "37747561",
            "expected_coverage": "full_text",
            "coverage_reason": "full_text_available",
            "pmc_fallback_available": True,
            "resolver_attempts": [],
        },
        "source_id": "PMID:37747561",
        "error": None,
    }

    candidate = _research_session_candidate_from_row(row)

    assert candidate.pmid == "37747561"
    assert candidate.coverage_hint is not None
    assert candidate.coverage_hint.expected_coverage == "full_text"
```

- [ ] **Step 2: Write failing repository test**

Add to `tests/unit/test_review_rerag_repository.py`:

```python
from pubtator_link.models.review_rerag import ResearchSessionCandidate


async def test_repository_round_trips_research_session(repository) -> None:
    await repository.upsert_research_session(
        review_id="review-1",
        session_id="session-1",
        query="FMF colchicine",
        status="active",
        request={"query": "FMF colchicine"},
    )
    await repository.upsert_research_session_candidate(
        review_id="review-1",
        session_id="session-1",
        candidate=ResearchSessionCandidate(
            pmid="37747561",
            rank=1,
            status="queued",
            decision_reason="selected_by_rank",
            source_id="PMID:37747561",
        ),
    )

    manifest = await repository.get_research_session("review-1", "session-1")

    assert manifest is not None
    assert manifest.review_id == "review-1"
    assert manifest.session_id == "session-1"
    assert manifest.candidate_count == 1
    assert manifest.candidates[0].pmid == "37747561"
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_mappers.py tests/unit/test_review_rerag_repository.py -q`

Expected: FAIL because session mapping and repository methods are missing.

- [ ] **Step 4: Add mapper helper**

In `pubtator_link/repositories/review_rerag_mappers.py`, add:

```python
from pubtator_link.models.review_rerag import ResearchSessionCandidate, SourceCoverageHint


def _research_session_candidate_from_row(row: Mapping[str, Any]) -> ResearchSessionCandidate:
    coverage_hint = row.get("coverage_hint")
    return ResearchSessionCandidate(
        pmid=row["pmid"],
        rank=row.get("rank"),
        title=row.get("title"),
        status=row.get("status", "candidate"),
        decision_reason=row.get("decision_reason", "selected_by_rank"),
        coverage_hint=(
            SourceCoverageHint.model_validate(coverage_hint) if coverage_hint else None
        ),
        source_id=row.get("source_id"),
        error=row.get("error"),
    )
```

- [ ] **Step 5: Add repository methods**

In `pubtator_link/repositories/review_rerag.py`, import the new models and mapper, then add methods to `PostgresReviewReragRepository`:

```python
async def upsert_research_session(
    self,
    *,
    review_id: str,
    session_id: str,
    query: str | None,
    status: str,
    request: dict[str, Any],
) -> None:
    await self.ensure_review(review_id)
    async with self.pool.acquire() as conn:
        await conn.execute(
            """
            insert into review_research_sessions
                (review_id, session_id, query, status, request, updated_at)
            values ($1, $2, $3, $4, $5::jsonb, now())
            on conflict (review_id, session_id) do update set
                query = excluded.query,
                status = excluded.status,
                request = excluded.request,
                updated_at = now()
            """,
            review_id,
            session_id,
            query,
            status,
            json.dumps(request),
        )


async def upsert_research_session_candidate(
    self,
    *,
    review_id: str,
    session_id: str,
    candidate: ResearchSessionCandidate,
) -> None:
    async with self.pool.acquire() as conn:
        await conn.execute(
            """
            insert into review_research_session_candidates
                (review_id, session_id, pmid, rank, title, status, decision_reason,
                 coverage_hint, source_id, error, updated_at)
            values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, now())
            on conflict (review_id, session_id, pmid) do update set
                rank = excluded.rank,
                title = excluded.title,
                status = excluded.status,
                decision_reason = excluded.decision_reason,
                coverage_hint = excluded.coverage_hint,
                source_id = excluded.source_id,
                error = excluded.error,
                updated_at = now()
            """,
            review_id,
            session_id,
            candidate.pmid,
            candidate.rank,
            candidate.title,
            candidate.status,
            candidate.decision_reason,
            candidate.coverage_hint.model_dump(mode="json") if candidate.coverage_hint else None,
            candidate.source_id,
            candidate.error,
        )
```

Add `get_research_session()`:

```python
async def get_research_session(
    self, review_id: str, session_id: str
) -> ResearchSessionManifest | None:
    async with self.pool.acquire() as conn:
        session = await conn.fetchrow(
            """
            select review_id, session_id, query, status,
                   created_at::text as created_at, updated_at::text as updated_at
            from review_research_sessions
            where review_id = $1 and session_id = $2
            """,
            review_id,
            session_id,
        )
        if session is None:
            return None
        rows = await conn.fetch(
            """
            select pmid, rank, title, status, decision_reason, coverage_hint,
                   source_id, error
            from review_research_session_candidates
            where review_id = $1 and session_id = $2
            order by rank nulls last, pmid
            """,
            review_id,
            session_id,
        )
    candidates = [_research_session_candidate_from_row(row) for row in rows]
    return ResearchSessionManifest(
        review_id=session["review_id"],
        session_id=session["session_id"],
        query=session["query"],
        status=session["status"],
        candidates=candidates,
        candidate_count=len(candidates),
        queued_count=sum(1 for item in candidates if item.status == "queued"),
        skipped_count=sum(1 for item in candidates if item.status == "skipped"),
        coverage_summary=_coverage_summary(candidates),
        created_at=session["created_at"],
        updated_at=session["updated_at"],
    )
```

Add `list_research_sessions()`:

```python
async def list_research_sessions(self, review_id: str) -> list[ResearchSessionManifest]:
    async with self.pool.acquire() as conn:
        sessions = await conn.fetch(
            """
            select review_id, session_id, query, status,
                   created_at::text as created_at, updated_at::text as updated_at
            from review_research_sessions
            where review_id = $1
            order by updated_at desc, session_id
            """,
            review_id,
        )
    manifests: list[ResearchSessionManifest] = []
    for session in sessions:
        manifest = await self.get_research_session(
            session["review_id"],
            session["session_id"],
        )
        if manifest is not None:
            manifests.append(manifest)
    return manifests
```

Also add:

```python
def _coverage_summary(candidates: list[ResearchSessionCandidate]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for candidate in candidates:
        coverage = (
            candidate.coverage_hint.expected_coverage
            if candidate.coverage_hint is not None
            else "unknown"
        )
        summary[coverage] = summary.get(coverage, 0) + 1
    return summary
```

- [ ] **Step 6: Run repository tests**

Run: `uv run pytest tests/unit/test_review_rerag_mappers.py tests/unit/test_review_rerag_repository.py -q`

Expected: PASS.

- [ ] **Step 7: Commit repository persistence**

```bash
git add pubtator_link/repositories/review_rerag.py pubtator_link/repositories/review_rerag_mappers.py tests/unit/test_review_rerag_mappers.py tests/unit/test_review_rerag_repository.py
git commit -m "feat: persist research sessions"
```

## Task 3: Add Research Session Service

**Files:**
- Create: `pubtator_link/services/research_session.py`
- Test: `tests/unit/test_research_session_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/unit/test_research_session_service.py`:

```python
from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.models.review_rerag import PreparationStatus, SourceCoverageHint
from pubtator_link.services.research_session import ResearchSessionService


class FakeRepository:
    def __init__(self) -> None:
        self.sessions = {}
        self.candidates = []

    async def upsert_research_session(self, **kwargs):
        self.sessions[(kwargs["review_id"], kwargs["session_id"])] = kwargs

    async def upsert_research_session_candidate(self, **kwargs):
        self.candidates.append(kwargs["candidate"])

    async def get_research_session(self, review_id, session_id):
        from pubtator_link.models.review_rerag import ResearchSessionManifest

        return ResearchSessionManifest(
            review_id=review_id,
            session_id=session_id,
            candidates=self.candidates,
            candidate_count=len(self.candidates),
            queued_count=sum(1 for item in self.candidates if item.status == "queued"),
            skipped_count=sum(1 for item in self.candidates if item.status == "skipped"),
        )


class FakeSearch:
    async def search(self, request):
        return SearchResponse(
            success=True,
            query=request.query or "",
            results=[
                SearchResult(pmid="1", title="first"),
                SearchResult(pmid="2", title="second"),
            ],
            total_results=2,
            page=1,
            per_page=20,
            total_pages=1,
        )


class FakePreflight:
    async def preflight_pmids(self, pmids):
        return [
            SourceCoverageHint(
                pmid=pmid,
                expected_coverage="full_text" if pmid == "1" else "abstract_only",
                coverage_reason="full_text_available" if pmid == "1" else "no_pmcid",
            )
            for pmid in pmids
        ]


class FakeQueue:
    class Repository:
        async def preparation_status(self, review_id):
            return PreparationStatus(queued=1)

    repository = Repository()

    async def enqueue_pmid(self, review_id, pmid):
        return pmid == "1"


async def test_stage_session_searches_preflights_and_queues_candidates() -> None:
    repository = FakeRepository()
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(),
        queue=FakeQueue(),
    )

    response = await service.stage(
        review_id="review-1",
        request={"query": "FMF", "max_candidates": 2, "stage_full_text": True},
    )

    assert response.manifest.review_id == "review-1"
    assert response.manifest.candidate_count == 2
    assert response.manifest.queued_count == 1
    assert response.manifest.candidates[0].status == "queued"
    assert response.manifest.candidates[1].status == "skipped"
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/unit/test_research_session_service.py -q`

Expected: FAIL because the service file is missing.

- [ ] **Step 3: Implement service**

Create `pubtator_link/services/research_session.py`:

```python
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pubtator_link.models.responses import SearchResponse
from pubtator_link.models.review_rerag import (
    ResearchSessionCandidate,
    StageResearchSessionRequest,
    StageResearchSessionResponse,
)


class ResearchSessionSearchProvider:
    async def search(self, request: StageResearchSessionRequest) -> SearchResponse:
        raise NotImplementedError


class ResearchSessionService:
    def __init__(
        self,
        *,
        repository: Any,
        search_provider: ResearchSessionSearchProvider,
        preflight_service: Any,
        queue: Any,
    ) -> None:
        self.repository = repository
        self.search_provider = search_provider
        self.preflight_service = preflight_service
        self.queue = queue

    async def stage(
        self,
        *,
        review_id: str,
        request: StageResearchSessionRequest | dict[str, Any],
    ) -> StageResearchSessionResponse:
        stage_request = (
            request
            if isinstance(request, StageResearchSessionRequest)
            else StageResearchSessionRequest.model_validate(request)
        )
        session_id = stage_request.session_id or f"session-{uuid4().hex}"
        candidates = await self._candidate_pmids(stage_request)
        limited = candidates[: stage_request.max_candidates]
        await self.repository.upsert_research_session(
            review_id=review_id,
            session_id=session_id,
            query=stage_request.query,
            status="active",
            request=stage_request.model_dump(mode="json"),
        )

        hints = await self.preflight_service.preflight_pmids([pmid for pmid, _title in limited])
        hints_by_pmid = {hint.pmid: hint for hint in hints}
        for rank, (pmid, title) in enumerate(limited, start=1):
            hint = hints_by_pmid.get(pmid)
            should_queue = stage_request.stage_full_text and (
                hint is None or hint.expected_coverage in {"full_text", "abstract_only", "unknown"}
            )
            if should_queue and await self.queue.enqueue_pmid(review_id, pmid):
                status = "queued"
                reason = "selected_by_rank"
            elif should_queue:
                status = "skipped"
                reason = "already_indexed"
            else:
                status = "skipped"
                reason = "metadata_only"
            await self.repository.upsert_research_session_candidate(
                review_id=review_id,
                session_id=session_id,
                candidate=ResearchSessionCandidate(
                    pmid=pmid,
                    rank=rank,
                    title=title,
                    status=status,
                    decision_reason=reason,
                    coverage_hint=hint,
                    source_id=f"PMID:{pmid}",
                ),
            )

        manifest = await self.repository.get_research_session(review_id, session_id)
        manifest.preparation_status = await self.queue.repository.preparation_status(review_id)
        return StageResearchSessionResponse(
            manifest=manifest,
            meta={
                "next_commands": [
                    "pubtator.get_research_session_status",
                    "pubtator.inspect_review_index",
                    "pubtator.retrieve_review_context_batch",
                ],
                "unsafe_for_clinical_use": True,
            },
        )

    async def _candidate_pmids(
        self, request: StageResearchSessionRequest
    ) -> list[tuple[str, str | None]]:
        seen: set[str] = set()
        candidates: list[tuple[str, str | None]] = []
        for pmid in request.pmids:
            if pmid not in seen:
                seen.add(pmid)
                candidates.append((pmid, None))
        if request.query:
            response = await self.search_provider.search(request)
            for result in response.results:
                if result.pmid and result.pmid not in seen:
                    seen.add(result.pmid)
                    candidates.append((result.pmid, result.title))
        return candidates
```

- [ ] **Step 4: Run service tests**

Run: `uv run pytest tests/unit/test_research_session_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit service**

```bash
git add pubtator_link/services/research_session.py tests/unit/test_research_session_service.py
git commit -m "feat: add research session staging service"
```

## Task 4: Wire REST Dependencies And Routes

**Files:**
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing route tests**

Add to `tests/test_routes/test_reviews.py`:

```python
def test_stage_research_session_route_is_registered(app) -> None:
    route_paths = {route.path for route in app.routes}
    assert "/api/reviews/{review_id}/sessions/stage" in route_paths
    assert "/api/reviews/{review_id}/sessions/{session_id}" in route_paths
    assert "/api/reviews/{review_id}/sessions" in route_paths
```

- [ ] **Step 2: Run route test to verify failure**

Run: `uv run pytest tests/test_routes/test_reviews.py -q`

Expected: FAIL because the routes are not registered.

- [ ] **Step 3: Add dependency wiring**

In `pubtator_link/api/routes/dependencies.py`, import the service:

```python
from pubtator_link.api.search_filters import merge_search_filters
from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.models.review_rerag import StageResearchSessionRequest
from ...services.research_session import ResearchSessionService
```

Add global/resource fields matching existing patterns:

```python
_research_session_service: ResearchSessionService | None = None
```

Add `research_session_service: ResearchSessionService | None = None` to
`AppResources`.

Add a dependency function:

```python
async def get_research_session_service() -> ResearchSessionService:
    global _research_session_service
    resources = current_app_resources()
    if resources is not None:
        if resources.research_session_service is None:
            if resources.review_repository is None or resources.review_queue is None:
                raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
            resources.research_session_service = ResearchSessionService(
                repository=resources.review_repository,
                search_provider=_RouteSearchProvider(resources.api_client),
                preflight_service=resources.source_preflight_service,
                queue=resources.review_queue,
            )
        return resources.research_session_service
    if _research_session_service is None:
        _research_session_service = ResearchSessionService(
            repository=await get_review_repository(),
            search_provider=_RouteSearchProvider(await get_api_client()),
            preflight_service=await get_source_preflight_service(),
            queue=await get_review_queue(),
        )
    return _research_session_service
```

Define `_RouteSearchProvider` in `pubtator_link/api/routes/dependencies.py`:

```python
class _RouteSearchProvider:
    def __init__(self, client: PubTator3Client) -> None:
        self.client = client

    async def search(self, request: StageResearchSessionRequest) -> SearchResponse:
        raw = await self.client.search_publications(
            text=request.query or "",
            page=request.page,
            sort=request.sort,
            filters=merge_search_filters(
                filters=request.filters,
                publication_types=request.publication_types,
                year_min=request.year_min,
                year_max=request.year_max,
            ),
            sections=",".join(request.sections) if request.sections else None,
        )
        results = [
            SearchResult(
                pmid=item.get("pmid", ""),
                title=item.get("title", ""),
                abstract=item.get("abstract"),
                authors=item.get("authors", []),
                journal=item.get("journal"),
                pub_date=item.get("pub_date")
                or item.get("meta_date_publication")
                or item.get("date"),
                annotations=item.get("annotations", []),
                score=item.get("score"),
                pmcid=item.get("pmcid"),
                doi=item.get("doi"),
                date=item.get("date"),
                text_hl=item.get("text_hl"),
                citations=item.get("citations"),
                volume=item.get("volume") or item.get("meta_volume"),
                issue=item.get("issue") or item.get("meta_issue"),
                pages=item.get("pages") or item.get("meta_pages"),
                publication_types=item.get("publication_types", []),
            )
            for item in raw.get("results", [])
        ]
        total_results = int(raw.get("count", raw.get("total", 0)))
        per_page = int(raw.get("page_size", raw.get("per_page", 20)))
        return SearchResponse(
            success=True,
            query=request.query or "",
            results=results,
            total_results=total_results,
            page=request.page,
            per_page=per_page,
            total_pages=int(
                raw.get(
                    "total_pages",
                    (total_results + per_page - 1) // per_page if per_page else 0,
                )
            ),
            sort_order=request.sort,
        )
```

Add type alias:

```python
ResearchSessionServiceDep = Annotated[
    ResearchSessionService,
    Depends(get_research_session_service),
]
```

- [ ] **Step 4: Add REST routes**

In `pubtator_link/api/routes/reviews.py`, import:

```python
ResearchSessionServiceDep,
```

and models:

```python
ListResearchSessionsResponse,
ResearchSessionStatusResponse,
StageResearchSessionRequest,
StageResearchSessionResponse,
```

Add routes:

```python
@router.post(
    "/{review_id}/sessions/stage",
    response_model=StageResearchSessionResponse,
    operation_id="stage_research_session",
    summary="Stage a transparent research session",
)
@handle_api_errors
async def stage_research_session(
    review_id: str,
    request: StageResearchSessionRequest,
    service: ResearchSessionServiceDep,
) -> StageResearchSessionResponse:
    return await service.stage(review_id=review_id, request=request)


@router.get(
    "/{review_id}/sessions/{session_id}",
    response_model=ResearchSessionStatusResponse,
    operation_id="get_research_session_status",
    summary="Get staged research session status",
)
@handle_api_errors
async def get_research_session_status(
    review_id: str,
    session_id: str,
    service: ResearchSessionServiceDep,
) -> ResearchSessionStatusResponse:
    try:
        return await service.get_status(review_id=review_id, session_id=session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{review_id}/sessions",
    response_model=ListResearchSessionsResponse,
    operation_id="list_research_sessions",
    summary="List staged research sessions",
)
@handle_api_errors
async def list_research_sessions(
    review_id: str,
    service: ResearchSessionServiceDep,
) -> ListResearchSessionsResponse:
    return await service.list_sessions(review_id=review_id)
```

Implement `get_status()` and `list_sessions()` on `ResearchSessionService` before
running tests:

```python
async def get_status(self, *, review_id: str, session_id: str) -> ResearchSessionStatusResponse:
    manifest = await self.repository.get_research_session(review_id, session_id)
    if manifest is None:
        raise LookupError(f"Research session not found: {session_id}")
    manifest.preparation_status = await self.queue.repository.preparation_status(review_id)
    return ResearchSessionStatusResponse(manifest=manifest)


async def list_sessions(self, *, review_id: str) -> ListResearchSessionsResponse:
    sessions = await self.repository.list_research_sessions(review_id)
    return ListResearchSessionsResponse(sessions=sessions)
```

- [ ] **Step 5: Run route tests**

Run: `uv run pytest tests/test_routes/test_reviews.py tests/unit/test_research_session_service.py -q`

Expected: PASS.

- [ ] **Step 6: Commit REST wiring**

```bash
git add pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/reviews.py pubtator_link/services/research_session.py tests/test_routes/test_reviews.py tests/unit/test_research_session_service.py
git commit -m "feat: expose research session REST routes"
```

## Task 5: Add MCP Tools, Resources, And Audit Export

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/services/review_audit.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_review_audit.py`

- [ ] **Step 1: Write failing MCP tests**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_research_session_tools_are_registered(mcp_tool_names) -> None:
    assert "pubtator.stage_research_session" in mcp_tool_names
    assert "pubtator.get_research_session_status" in mcp_tool_names
    assert "pubtator.list_research_sessions" in mcp_tool_names
```

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
from pubtator_link.mcp.service_adapters import stage_research_session_impl


async def test_stage_research_session_impl_calls_service() -> None:
    class Service:
        async def stage(self, *, review_id, request):
            assert review_id == "review-1"
            assert request.query == "FMF"
            return type("Response", (), {"model_dump": lambda self: {"success": True}})()

    result = await stage_research_session_impl(
        service=Service(),
        review_id="review-1",
        query="FMF",
        pmids=None,
        max_candidates=10,
        stage_full_text=True,
    )

    assert result == {"success": True}
```

- [ ] **Step 2: Run MCP tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: FAIL because tools and adapters are missing.

- [ ] **Step 3: Add service adapters**

In `pubtator_link/mcp/service_adapters.py`, import `StageResearchSessionRequest`
and add:

```python
async def stage_research_session_impl(
    *,
    service: Any,
    review_id: str,
    query: str | None = None,
    pmids: list[str] | None = None,
    session_id: str | None = None,
    max_candidates: int = 20,
    stage_full_text: bool = True,
) -> dict[str, Any]:
    response = await service.stage(
        review_id=review_id,
        request=StageResearchSessionRequest(
            session_id=session_id,
            query=query,
            pmids=pmids or [],
            max_candidates=max_candidates,
            stage_full_text=stage_full_text,
        ),
    )
    return response.model_dump(by_alias=True)


async def get_research_session_status_impl(
    *, service: Any, review_id: str, session_id: str
) -> dict[str, Any]:
    return (
        await service.get_status(review_id=review_id, session_id=session_id)
    ).model_dump(by_alias=True)


async def list_research_sessions_impl(*, service: Any, review_id: str) -> dict[str, Any]:
    return (await service.list_sessions(review_id=review_id)).model_dump(by_alias=True)
```

- [ ] **Step 4: Register MCP tools**

In `pubtator_link/mcp/tools/review.py`, import dependency, adapters, and schemas:

```python
get_research_session_service,
stage_research_session_impl,
get_research_session_status_impl,
list_research_sessions_impl,
ListResearchSessionsResponse,
ResearchSessionStatusResponse,
StageResearchSessionResponse,
```

Add tools inside `register_review_tools()`:

```python
@mcp.tool(
    name="pubtator.stage_research_session",
    title="Stage Research Session",
    output_schema=StageResearchSessionResponse.model_json_schema(),
    annotations=REVIEW_WRITE_ANNOTATIONS,
)
async def stage_research_session(
    review_id: str,
    query: str | None = None,
    pmids: list[str] | None = None,
    session_id: str | None = None,
    max_candidates: int = 20,
    stage_full_text: bool = True,
) -> dict[str, Any]:
    """Use this after search planning to stage candidate PMIDs with coverage hints and queued review preparation. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    service = await get_research_session_service()
    return await stage_research_session_impl(
        service=service,
        review_id=review_id,
        query=query,
        pmids=pmids,
        session_id=session_id,
        max_candidates=max_candidates,
        stage_full_text=stage_full_text,
    )
```

Add the status tool:

```python
@mcp.tool(
    name="pubtator.get_research_session_status",
    title="Get Research Session Status",
    output_schema=ResearchSessionStatusResponse.model_json_schema(),
    annotations=READ_ONLY_OPEN_WORLD,
)
async def get_research_session_status(review_id: str, session_id: str) -> dict[str, Any]:
    """Use this to poll staged candidate, coverage, and preparation status for a research session. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    service = await get_research_session_service()
    return await get_research_session_status_impl(
        service=service,
        review_id=review_id,
        session_id=session_id,
    )
```

Add the list tool:

```python
@mcp.tool(
    name="pubtator.list_research_sessions",
    title="List Research Sessions",
    output_schema=ListResearchSessionsResponse.model_json_schema(),
    annotations=READ_ONLY_OPEN_WORLD,
)
async def list_research_sessions(review_id: str) -> dict[str, Any]:
    """Use this to list staged research sessions for one review ID. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    service = await get_research_session_service()
    return await list_research_sessions_impl(service=service, review_id=review_id)
```

- [ ] **Step 5: Update MCP resources and audit bundle**

In `pubtator_link/mcp/resources.py`, add the workflow sentence:

```markdown
For live research sessions, call `pubtator.stage_research_session` with a
review ID and query or PMID list, then poll `pubtator.get_research_session_status`
before retrieving review context.
```

In `pubtator_link/services/review_audit.py`, include session manifests by
calling `repository.list_research_sessions(review_id)` and adding the serialized
values to the audit bundle model. In `ReviewAuditBundle`, add:

```python
research_sessions: list[ResearchSessionManifest] = Field(default_factory=list)
```

- [ ] **Step 6: Run MCP and audit tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_review_audit.py -q`

Expected: PASS.

- [ ] **Step 7: Commit MCP and audit export**

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/resources.py pubtator_link/services/review_audit.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_review_audit.py
git commit -m "feat: expose research session MCP workflow"
```

## Task 6: Final Verification And Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`

- [ ] **Step 1: Add README tool row**

In `README.md`, add rows to the MCP tool table:

```markdown
| `pubtator.stage_research_session` | Stage query or PMID candidates with coverage hints and queued review preparation |
| `pubtator.get_research_session_status` | Poll staged candidate and preparation status |
| `pubtator.list_research_sessions` | List staged sessions for a review ID |
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run pytest \
  tests/unit/test_review_rerag_models.py \
  tests/unit/test_review_schema_sql.py \
  tests/unit/test_review_rerag_mappers.py \
  tests/unit/test_review_rerag_repository.py \
  tests/unit/test_research_session_service.py \
  tests/test_routes/test_reviews.py \
  tests/unit/mcp/test_mcp_facade.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/test_review_audit.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run full local CI**

Run: `make ci-local`

Expected: PASS.

- [ ] **Step 4: Commit docs and final polish**

```bash
git add README.md docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md
git commit -m "docs: document research session staging"
```

## Self-Review Checklist

- Spec coverage: models, schema, repository, service, REST, MCP, resources,
  audit export, tests, and docs are covered.
- Placeholder scan: no task relies on unspecified future work.
- Type consistency: `StageResearchSessionRequest`,
  `ResearchSessionManifest`, `StageResearchSessionResponse`,
  `ResearchSessionStatusResponse`, and `ListResearchSessionsResponse` are named
  consistently across tasks.
- Scope check: discovery parity tools, automatic search-time prefetch, and UI
  workflows are intentionally excluded from this plan.
