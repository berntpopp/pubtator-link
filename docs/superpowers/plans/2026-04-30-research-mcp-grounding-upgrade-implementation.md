# Research MCP Grounding Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade PubTator-Link into a more discoverable, context-safe research grounding MCP and REST server with compact publication passages, review index inspection, retrieval diagnostics, and batch retrieval.

**Architecture:** Keep existing raw PubTator export contracts intact and add safer purpose-built models, services, routes, and MCP tools. Publication compaction lives in a new service over `PublicationService`; review inspection and diagnostics live in `ReviewContextService` plus repository inspection methods; MCP tools call service adapters over the same internal layer as REST routes.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, FastMCP, asyncpg/PostgreSQL, Ruff, mypy, pytest, uv, Makefile targets.

---

## File Structure

- Modify `pubtator_link/mcp/facade.py`: concise under-2KB server instructions; new MCP tool registrations and descriptions.
- Modify `pubtator_link/mcp/resources.py`: advertised capability groups, recommended workflows, large-output guidance, review re-RAG workflow.
- Modify `pubtator_link/mcp/tools.py`: request models for new MCP tools and `include_diagnostics`.
- Modify `pubtator_link/mcp/service_adapters.py`: adapter functions for publication passages, context estimate, review index inspection, and batch retrieval.
- Create `pubtator_link/models/publication_passages.py`: compact publication request/response models.
- Modify `pubtator_link/models/review_rerag.py`: index inspection, diagnostics, and batch retrieval models.
- Create `pubtator_link/services/publication_passage_service.py`: section normalization, BioC passage compaction, estimates, budgets, and drop reasons.
- Modify `pubtator_link/services/review_context_service.py`: diagnostics, batch retrieval, and index inspection orchestration.
- Modify `pubtator_link/repositories/review_rerag.py`: SQL methods for source summaries, failed sources, totals, and diagnostic metadata.
- Modify `pubtator_link/api/routes/dependencies.py`: dependency for the publication passage service.
- Modify `pubtator_link/api/routes/publications.py`: `POST /api/publications/passages` and `POST /api/publications/context-estimate`.
- Modify `pubtator_link/api/routes/reviews.py`: `GET /api/reviews/{review_id}/index` and `POST /api/reviews/{review_id}/context/batch`.
- Modify tests under `tests/unit/`, `tests/unit/mcp/`, `tests/test_routes/`, and `tests/integration/`.
- Modify docs such as `docs/MCP_CONNECTION_GUIDE.md` and/or `docs/REVIEW_RERAG_POC.md` for Claude Code usage examples.

## Coordination Rules

- Work lanes are intentionally disjoint. Do not edit files outside a lane unless this plan says to.
- Every lane starts with failing tests, runs the focused test command, and commits once green.
- Use `apply_patch` for manual edits.
- Prefer Makefile targets when practical; focused pytest commands are allowed for TDD loops.
- The final integrator runs `make ci-local`.
- If PostgreSQL is not reachable at `postgresql://pubtator_link:pubtator_link@localhost:55432/pubtator_link`, integration tests should skip and report the skip.

---

### Task 1: MCP Discoverability, Capability Resource, and Tool Metadata

**Files:**
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Write failing MCP discoverability tests**

Add tests that assert the first instruction sentence is exactly the capability map, the full instructions are under 2 KB, workflow guidance appears early, capabilities resource advertises workflows and tool groups, and existing/new tool descriptions start with `Use this when`.

```python
def test_server_instructions_are_tool_search_friendly() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    instructions = mcp.instructions or ""

    assert instructions.startswith(
        "PubTator-Link grounds biomedical literature work: search PubMed/PubTator, "
        "fetch compact passages or raw BioC, inspect review indexes, retrieve "
        "review-scoped RAG context, find entity relations, and submit/get text annotations."
    )
    assert len(instructions.encode("utf-8")) < 2048
    assert "pubtator.get_server_capabilities" in instructions
    assert "search -> index -> inspect -> retrieve" in instructions
    assert "raw full BioC can be large" in instructions
    assert "not for diagnosis" in instructions


def test_capabilities_resource_advertises_grounding_workflows() -> None:
    from pubtator_link.mcp.resources import get_capabilities_resource

    capabilities = get_capabilities_resource()

    assert "recommended_workflows" in capabilities
    assert "tool_groups" in capabilities
    assert "large_output_guidance" in capabilities
    assert "review_rerag" in capabilities
    assert "search -> index -> inspect -> retrieve" in capabilities["recommended_workflows"][0]
    assert "pubtator.get_publication_passages" in capabilities["tool_groups"]["publication_grounding"]
    assert "pubtator.inspect_review_index" in capabilities["tool_groups"]["review_grounding"]
```

Extend `test_review_rerag_tool_descriptions_explain_workflow_and_query_style`:

```python
    for name in (
        "pubtator.fetch_publication_annotations",
        "pubtator.retrieve_review_context",
        "pubtator.index_review_evidence",
    ):
        assert tools[name].description.startswith("Use this when")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: FAIL because instructions, resource keys, and new future tool names are absent.

- [ ] **Step 3: Implement concise instructions and capabilities**

Set `instructions` in `create_pubtator_mcp()` to one compact literal:

```python
instructions=(
    "PubTator-Link grounds biomedical literature work: search PubMed/PubTator, "
    "fetch compact passages or raw BioC, inspect review indexes, retrieve "
    "review-scoped RAG context, find entity relations, and submit/get text annotations. "
    "If tools are deferred, search for pubtator tools or call "
    "pubtator.get_server_capabilities. For grounded answers use "
    "search -> index -> inspect -> retrieve. Prefer compact passage tools before "
    "raw export because raw full BioC can be large. If retrieval returns zero "
    "passages, inspect the review index and retry shorter keyword queries or PMID "
    f"filters. {RESEARCH_USE_NOTICE}"
)
```

Update `get_capabilities_resource()` so it contains:

```python
"recommended_workflows": [
    "search -> index -> inspect -> retrieve for review-grounded answers",
    "publication passages -> context estimate -> compact passage retrieval before raw BioC",
],
"tool_groups": {
    "literature_search": ["pubtator.search_literature"],
    "publication_grounding": [
        "pubtator.get_publication_passages",
        "pubtator.estimate_publication_context",
        "pubtator.fetch_publication_annotations",
        "pubtator.fetch_pmc_annotations",
    ],
    "review_grounding": [
        "pubtator.index_review_evidence",
        "pubtator.inspect_review_index",
        "pubtator.retrieve_review_context",
        "pubtator.retrieve_review_context_batch",
    ],
    "entities_relations": [
        "pubtator.search_biomedical_entities",
        "pubtator.find_entity_relations",
    ],
    "text_annotation": [
        "pubtator.submit_text_annotation",
        "pubtator.get_text_annotation_results",
    ],
},
"large_output_guidance": {
    "prefer": "pubtator.get_publication_passages",
    "avoid_by_default": "pubtator.fetch_publication_annotations full=true",
    "reason": "raw full BioC can be multi-megabyte; compact tools return citable passages",
},
```

Keep `review_rerag` limitations and research-use notice.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/facade.py pubtator_link/mcp/resources.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "docs: improve mcp grounding discoverability"
```

---

### Task 2: Compact Publication Passage Models, Service, Routes, and MCP Tools

**Files:**
- Create: `pubtator_link/models/publication_passages.py`
- Create: `pubtator_link/services/publication_passage_service.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/api/routes/publications.py`
- Modify: `pubtator_link/mcp/tools.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Create: `tests/unit/test_publication_passage_service.py`
- Modify: `tests/test_routes/test_publications.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/unit/test_publication_passage_service.py` with tests using a fake `PublicationService.export_publications_list()` that returns BioC-like documents:

```python
import pytest

from pubtator_link.models.publication_passages import (
    PublicationPassageRequest,
    PublicationContextEstimateRequest,
)
from pubtator_link.services.publication_passage_service import PublicationPassageService


class FakePublicationService:
    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        return {
            "export_data": {
                "documents": [
                    {
                        "id": "111",
                        "infons": {"pmcid": "PMC111"},
                        "passages": [
                            {"infons": {"section_type": "TITLE"}, "text": "Trial title"},
                            {"infons": {"section_type": "ABSTRACT"}, "text": "Abstract text"},
                            {"infons": {"section_type": "METHODS"}, "text": "Methods text"},
                            {"infons": {"section_type": "TABLE"}, "text": "Table text"},
                            {"infons": {"section_type": "REF"}, "text": "Reference text"},
                        ],
                    }
                ]
            }
        }


@pytest.mark.asyncio
async def test_get_publication_passages_filters_sections_and_references() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], sections=["abstract", "table"])
    )

    assert response.success is True
    assert [passage.section for passage in response.passages] == ["abstract", "table"]
    assert [passage.text for passage in response.passages] == ["Abstract text", "Table text"]
    assert response.passages[0].passage_id == "PMID:111:abstract:0"
    assert response.passages[0].source == "pubtator_abstract"
    assert "documents" not in response.model_dump()
    assert {drop.reason for drop in response.dropped} >= {"section_filtered", "reference_excluded"}


@pytest.mark.asyncio
async def test_get_publication_passages_enforces_char_budget_without_truncation() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], max_chars=25, max_passages_per_pmid=10)
    )

    assert [passage.text for passage in response.passages] == ["Trial title", "Abstract text"]
    assert any(drop.reason == "char_budget_exceeded" for drop in response.dropped)


@pytest.mark.asyncio
async def test_estimate_publication_context_counts_sections_and_warns_large_output() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.estimate_context(
        PublicationContextEstimateRequest(pmids=["111"], full=True)
    )

    assert response.success is True
    assert response.estimated_passages == 4
    assert response.sections_by_pmid["111"] == ["title", "abstract", "methods", "table"]
    assert response.recommended_mode == "compact_passages"
```

- [ ] **Step 2: Run service tests to verify failure**

Run: `uv run pytest tests/unit/test_publication_passage_service.py -q`

Expected: FAIL because models and service do not exist.

- [ ] **Step 3: Implement publication passage models**

Create Pydantic models with these names and fields:

```python
PublicationPassageMode = Literal["abstracts", "compact_passages", "section_text"]
PassageDropReasonCode = Literal[
    "char_budget_exceeded",
    "section_filtered",
    "reference_excluded",
    "table_excluded",
    "max_passages_per_pmid_exceeded",
    "upstream_error",
]
PublicationPassageSource = Literal["pubtator_abstract", "pubtator_full_bioc"]

class PublicationPassageRequest(BaseModel):
    pmids: list[str] = Field(min_length=1, max_length=25)
    sections: list[str] = Field(default_factory=list)
    mode: PublicationPassageMode = "compact_passages"
    full: bool = False
    max_passages_per_pmid: int = Field(default=6, ge=1, le=30)
    max_chars: int = Field(default=12000, ge=1000, le=50000)
    include_tables: bool = True
    include_references: bool = False

class PublicationContextEstimateRequest(BaseModel):
    pmids: list[str] = Field(min_length=1, max_length=25)
    sections: list[str] = Field(default_factory=list)
    mode: PublicationPassageMode = "compact_passages"
    full: bool = False
    max_passages_per_pmid: int = Field(default=6, ge=1, le=30)
    include_tables: bool = True
    include_references: bool = False
```

Also define `PublicationPassage`, `PassageDropReason`, `PublicationContextEstimate`, `PublicationPassageResponse`, and `PublicationContextEstimateResponse` with fields from the design.

- [ ] **Step 4: Implement publication passage service**

Create `PublicationPassageService` with:

- `get_passages(request: PublicationPassageRequest) -> PublicationPassageResponse`
- `estimate_context(request: PublicationContextEstimateRequest) -> PublicationContextEstimateResponse`
- section normalization that maps `ABSTR` and `abstract` to `abstract`, `DISCUSS` to `discussion`, `CONCL` to `conclusion`, `REF` and `references` to `references`, `TABLE` to `table`
- source value `pubtator_full_bioc` when `request.full` is true, else `pubtator_abstract`
- no raw BioC in responses
- budget enforcement by dropping whole passages

Use `passage_id_for_pmid()` from `pubtator_link.models.review_rerag`.

- [ ] **Step 5: Run service tests to verify pass**

Run: `uv run pytest tests/unit/test_publication_passage_service.py -q`

Expected: PASS.

- [ ] **Step 6: Write failing route and MCP adapter tests**

Add route tests:

```python
@pytest.mark.asyncio
async def test_publication_passages_endpoint_returns_compact_passages() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_passages.return_value = PublicationPassageResponse(
        pmids=["111"],
        mode="compact_passages",
        passages=[PublicationPassage(
            passage_id="PMID:111:abstract:0",
            pmid="111",
            pmcid=None,
            section="abstract",
            text="Abstract text",
            char_count=13,
            source="pubtator_abstract",
        )],
        dropped=[],
        context_estimate=PublicationContextEstimate(
            estimated_passages=1,
            estimated_chars=13,
            sections_by_pmid={"111": ["abstract"]},
            recommended_mode="compact_passages",
            warning=None,
        ),
    )
    app.dependency_overrides[get_publication_passage_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/publications/passages", json={"pmids": ["111"]})
    assert response.status_code == 200
    assert response.json()["passages"][0]["text"] == "Abstract text"
    assert "documents" not in response.text
```

Add MCP assertions that `pubtator.get_publication_passages` and `pubtator.estimate_publication_context` are registered and descriptions start with `Use this when`.

- [ ] **Step 7: Implement route, dependency, adapter, and MCP tools**

Add:

- `get_publication_passage_service()` dependency
- `POST /api/publications/passages`
- `POST /api/publications/context-estimate`
- MCP request classes `GetPublicationPassagesMcpRequest` and `EstimatePublicationContextMcpRequest`
- adapter functions `get_publication_passages_impl()` and `estimate_publication_context_impl()`
- MCP tools `pubtator.get_publication_passages` and `pubtator.estimate_publication_context`

Tool descriptions must start with:

```text
Use this when a user needs compact citable publication passages from PMIDs without raw BioC.
Use this when a user needs to estimate passage count and context size before fetching publication passages.
```

- [ ] **Step 8: Run focused route and MCP tests**

Run: `uv run pytest tests/unit/test_publication_passage_service.py tests/test_routes/test_publications.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/models/publication_passages.py pubtator_link/services/publication_passage_service.py pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/publications.py pubtator_link/mcp/tools.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/facade.py tests/unit/test_publication_passage_service.py tests/test_routes/test_publications.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: add compact publication passage tools"
```

---

### Task 3: Review Index Inspection Repository, Service, Route, and MCP Tool

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/mcp/tools.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `tests/unit/test_review_rerag_repository.py`
- Modify: `tests/unit/test_review_context_service.py`
- Modify: `tests/test_routes/test_reviews.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`
- Modify: `tests/integration/test_review_schema_postgres.py`

- [ ] **Step 1: Write failing model/service/repository tests**

Add model classes for expected shapes in tests:

```python
ReviewIndexTotals(pmid_count=1, source_count=1, passage_count=2, char_count=30, failed_source_count=1)
ReviewSourceSummary(source_id="111", pmid="111", source_kind="pubtator_abstract", job_status="complete", error=None, attempt_statuses=["success"], sections=["abstract"], passage_count=2, char_count=30, sample_passages=[])
FailedSourceSummary(source_id="222", pmid="222", source_kind="pubtator_full_bioc", job_status="failed", error="not available", attempt_statuses=["not_available"])
```

Extend `FakeReviewContextRepository` with methods returning these values, then assert:

```python
response = await service.inspect_review_index(
    review_id="review-1",
    request=InspectReviewIndexRequest(include_passage_samples=True, sample_per_pmid=1),
)
assert response.success is True
assert response.totals.passage_count == 2
assert response.sources[0].sample_passages[0].passage_id == "p1"
assert response.failed_sources[0].error == "not available"
```

Repository tests should assert SQL touches `review_preparation_jobs`, `full_text_retrieval_attempts`, and `review_passages`.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py -q`

Expected: FAIL because inspection models and repository methods do not exist.

- [ ] **Step 3: Implement review index models**

Add to `models/review_rerag.py`:

```python
class ReviewPassageSample(BaseModel):
    passage_id: str
    section: str
    text: str
    char_count: int

class ReviewSourceSummary(BaseModel):
    source_id: str
    pmid: str | None = None
    source_kind: str
    job_status: str
    error: str | None = None
    attempt_statuses: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    passage_count: int = 0
    char_count: int = 0
    sample_passages: list[ReviewPassageSample] = Field(default_factory=list)

class FailedSourceSummary(BaseModel):
    source_id: str
    pmid: str | None = None
    source_kind: str
    job_status: str
    error: str | None = None
    attempt_statuses: list[str] = Field(default_factory=list)

class ReviewIndexTotals(BaseModel):
    pmid_count: int = 0
    source_count: int = 0
    passage_count: int = 0
    char_count: int = 0
    failed_source_count: int = 0

class InspectReviewIndexRequest(BaseModel):
    pmids: list[str] = Field(default_factory=list)
    include_passage_samples: bool = False
    sample_per_pmid: int = Field(default=2, ge=1, le=5)

class InspectReviewIndexResponse(BaseModel):
    success: bool = True
    review_id: str
    preparation_status: PreparationStatus
    sources: list[ReviewSourceSummary]
    totals: ReviewIndexTotals
    failed_sources: list[FailedSourceSummary]
```

- [ ] **Step 4: Implement repository inspection methods**

Add protocol and Postgres methods:

- `list_review_sources(review_id, pmids=None, include_passage_samples=False, sample_per_pmid=2) -> list[ReviewSourceSummary]`
- `list_review_failed_sources(review_id) -> list[FailedSourceSummary]`
- `review_index_totals(review_id) -> ReviewIndexTotals`

Use SQL joins over `review_preparation_jobs`, `full_text_retrieval_attempts`, and `review_passages`. Aggregate sections using `array_agg(distinct p.section order by p.section)`, attempt statuses with `array_agg(distinct a.status order by a.status)`, counts with `count(distinct p.passage_id)`, and chars with `coalesce(sum(length(p.text)), 0)`.

- [ ] **Step 5: Implement service inspection method**

Add `inspect_review_index()` to `ReviewContextService` that returns repository summaries, totals, failures, and preparation status. If the repository has no matching sources and status totals are all zero, return an empty successful response that distinguishes not indexed via `totals.source_count == 0`.

- [ ] **Step 6: Add route and MCP tool**

Add:

- `GET /api/reviews/{review_id}/index` with query params `pmids`, `include_passage_samples`, `sample_per_pmid`
- `InspectReviewIndexMcpRequest`
- `inspect_review_index_impl()`
- MCP tool `pubtator.inspect_review_index`

Tool description starts:

```text
Use this when a user needs to inspect what PMIDs, sections, passage counts, and failures are indexed for a review_id.
```

- [ ] **Step 7: Run focused tests**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: PASS.

- [ ] **Step 8: Add/adjust PostgreSQL integration test**

In `tests/integration/test_review_schema_postgres.py`, add a test that inserts one job, one failed attempt, and one passage, then calls `list_review_sources()`, `list_review_failed_sources()`, and `review_index_totals()`. Use existing skip logic for missing DB.

Run:

```bash
PUBTATOR_LINK_TEST_DATABASE_URL=postgresql://pubtator_link:pubtator_link@localhost:55432/pubtator_link uv run pytest tests/integration/test_review_schema_postgres.py -q
```

Expected: PASS when Docker DB is running; SKIP when unavailable.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/repositories/review_rerag.py pubtator_link/services/review_context_service.py pubtator_link/api/routes/reviews.py pubtator_link/mcp/tools.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/facade.py tests/unit/test_review_rerag_repository.py tests/unit/test_review_context_service.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py tests/integration/test_review_schema_postgres.py
git commit -m "feat: add review index inspection"
```

---

### Task 4: Retrieval Diagnostics and Batch Review Context Retrieval

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/mcp/tools.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `tests/unit/test_review_context_service.py`
- Modify: `tests/unit/test_review_rerag_repository.py`
- Modify: `tests/test_routes/test_reviews.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Write failing diagnostics and batch tests**

Add tests for:

- zero-result retrieval includes `diagnostics`
- non-zero retrieval includes diagnostics when `include_diagnostics=True`
- deterministic `suggested_queries` are shorter keyword variants
- batch retrieval deduplicates by `passage_id`, preserves per-query diagnostics, and assigns merged citation keys

Example service test:

```python
@pytest.mark.asyncio
async def test_zero_result_retrieval_includes_actionable_diagnostics() -> None:
    repository = FakeReviewContextRepository(
        [],
        preparation_status={"complete": 2, "failed": 1},
        available_sections=["abstract", "table", "discussion"],
        indexed_pmids=["111", "222"],
        failed_sources=[
            FailedSourceSummary(
                source_id="333",
                pmid="333",
                source_kind="pubtator_full_bioc",
                job_status="failed",
                error="not available",
                attempt_statuses=["not_available"],
            )
        ],
    )
    service = ReviewContextService(repository)
    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(question="Does colchicine reduce attacks in children?"),
    )
    assert response.context_pack.passages == []
    assert response.diagnostics is not None
    assert response.diagnostics.candidate_count == 0
    assert response.diagnostics.selected_count == 0
    assert response.diagnostics.indexed_pmids == ["111", "222"]
    assert "Try shorter keyword queries" in response.diagnostics.message
    assert response.diagnostics.suggested_queries
```

Batch test:

```python
request = RetrieveReviewContextBatchRequest(
    queries=["colchicine children", "FMF phenotype"],
    max_passages_per_query=2,
    max_total_passages=3,
)
response = await service.retrieve_context_batch("review-1", request)
assert [result.context_pack.question for result in response.results] == request.queries
assert len({p.passage_id for p in response.merged_context_pack.passages}) == len(response.merged_context_pack.passages)
assert all(result.diagnostics is not None for result in response.results)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_context_service.py -q`

Expected: FAIL because diagnostics and batch models/methods do not exist.

- [ ] **Step 3: Implement diagnostics and batch models**

Add:

```python
class RetrieveReviewDiagnostics(BaseModel):
    query: str
    query_tokens: list[str]
    query_mode: Literal["strict", "relaxed", "strict_and_relaxed"] = "strict_and_relaxed"
    candidate_count: int = 0
    selected_count: int = 0
    available_sections: list[str] = Field(default_factory=list)
    indexed_pmids: list[str] = Field(default_factory=list)
    failed_sources: list[FailedSourceSummary] = Field(default_factory=list)
    filter_summary: dict[str, list[str]] = Field(default_factory=dict)
    suggested_queries: list[str] = Field(default_factory=list)
    message: str
```

Extend `RetrieveReviewContextRequest` with `include_diagnostics: bool = False`. Extend `RetrieveReviewContextResponse` with `diagnostics: RetrieveReviewDiagnostics | None = None`.

Add:

```python
class RetrieveReviewContextBatchRequest(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=10)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages_per_query: int = Field(default=8, ge=1, le=30)
    max_total_passages: int = Field(default=20, ge=1, le=60)
    max_chars: int = Field(default=12000, ge=500, le=50000)
    deduplicate_passages: bool = True
    include_diagnostics: bool = True

class RetrieveReviewContextBatchResponse(BaseModel):
    success: bool = True
    review_id: str
    results: list[RetrieveReviewContextResponse]
    merged_context_pack: ContextPack
    preparation_status: PreparationStatus
```

- [ ] **Step 4: Add repository diagnostic metadata methods**

Add methods returning compact metadata without changing retrieval SQL:

- `available_sections(review_id: str) -> list[str]`
- `indexed_pmids(review_id: str) -> list[str]`

SQL should select distinct non-null values from `review_passages` ordered ascending.

- [ ] **Step 5: Implement diagnostics**

In `ReviewContextService.retrieve_context()`:

- keep current retrieval and packing behavior
- compute `candidate_count = len(candidates)` and `selected_count = len(selected)`
- include diagnostics when `selected` is empty or request `include_diagnostics` is true
- tokenize query with deterministic regex `[a-zA-Z0-9]+`, lowercase, skip tokens under 3 chars, cap at 12
- suggested queries are deterministic chunks such as first 3 tokens, first 5 tokens, and token pairs with available section labels removed when present
- message for zero results: `No passages selected. Review {review_id} has {n} indexed PMIDs and sections {sections}. Try shorter keyword queries or remove section filters.`

- [ ] **Step 6: Implement batch retrieval**

Add `retrieve_context_batch()` to `ReviewContextService`:

- call `retrieve_context()` for each query using shared filters
- set per-query `max_passages=max_passages_per_query`, `max_chars=max_chars`, `include_diagnostics=include_diagnostics`
- merge passages deterministically in query order
- deduplicate by passage ID when requested
- enforce `max_total_passages` and `max_chars`
- rebuild merged citation keys as `S1`, `S2`, ...

- [ ] **Step 7: Add REST route and MCP tool**

Add:

- `POST /api/reviews/{review_id}/context/batch`
- `RetrieveReviewContextBatchMcpRequest`
- adapter `retrieve_review_context_batch_impl()`
- MCP tool `pubtator.retrieve_review_context_batch`

Tool description starts:

```text
Use this when a user wants to try multiple short review retrieval query variants in one call and receive merged compact context.
```

- [ ] **Step 8: Run focused tests**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_context_service.py pubtator_link/repositories/review_rerag.py pubtator_link/api/routes/reviews.py pubtator_link/mcp/tools.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/facade.py tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: add retrieval diagnostics and batch context"
```

---

### Task 5: Documentation and Claude Code Usage Examples

**Files:**
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `docs/REVIEW_RERAG_POC.md`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing documentation metadata test**

Add a small test that ensures the capabilities resource lists all new MCP tools:

```python
def test_capabilities_resource_lists_grounding_upgrade_tools() -> None:
    from pubtator_link.mcp.resources import get_capabilities_resource

    capabilities = get_capabilities_resource()
    all_tools = set(capabilities["tools"])

    assert "pubtator.get_publication_passages" in all_tools
    assert "pubtator.estimate_publication_context" in all_tools
    assert "pubtator.inspect_review_index" in all_tools
    assert "pubtator.retrieve_review_context_batch" in all_tools
```

- [ ] **Step 2: Run test to verify failure if prior tasks missed a tool**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py -q`

Expected: PASS if Tasks 1-4 are correct; otherwise FAIL and fix missing resource entries.

- [ ] **Step 3: Update docs**

Add a concise Claude Code workflow section:

```markdown
## Research Grounding Workflow

For Claude Code, PubTator-Link is designed for deferred Tool Search. If tools
are not visible, ask Claude to search for PubTator-Link tools or call
`pubtator.get_server_capabilities`.

Recommended review workflow:

1. `pubtator.search_literature` to find candidate PMIDs.
2. `pubtator.index_review_evidence` with a stable `review_id`.
3. `pubtator.inspect_review_index` to verify PMIDs, sections, counts, and failures.
4. `pubtator.retrieve_review_context` or
   `pubtator.retrieve_review_context_batch` for compact citable passages.
5. `pubtator.get_publication_passages` for explicit PMID section retrieval.

Use `pubtator.fetch_publication_annotations` with `full=true` only when raw BioC
is intentionally needed. Compact passage tools are safer for routine grounding.
Research use only; not for diagnosis, treatment, triage, patient management, or
clinical decision support.
```

- [ ] **Step 4: Run docs-adjacent tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/MCP_CONNECTION_GUIDE.md docs/REVIEW_RERAG_POC.md tests/unit/mcp/test_mcp_facade.py
git commit -m "docs: document research grounding workflow"
```

---

### Task 6: Final Integration and Verification

**Files:**
- Review all touched files.

- [ ] **Step 1: Inspect git history and changed files**

Run:

```bash
git status --short
git log --oneline -8
git diff --stat HEAD~5..HEAD
```

Expected: clean worktree after task commits, with scoped commits for the upgrade.

- [ ] **Step 2: Run formatting and lint fixes if needed**

Run:

```bash
make format
make lint
```

Expected: PASS. If formatting changes files, commit them:

```bash
git add .
git commit -m "style: format grounding upgrade"
```

- [ ] **Step 3: Run focused full test subset**

Run:

```bash
uv run pytest tests/unit/test_publication_passage_service.py tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_publications.py tests/test_routes/test_reviews.py -q
```

Expected: PASS.

- [ ] **Step 4: Run PostgreSQL integration if DB is available**

Run:

```bash
PUBTATOR_LINK_TEST_DATABASE_URL=postgresql://pubtator_link:pubtator_link@localhost:55432/pubtator_link uv run pytest tests/integration/test_review_schema_postgres.py -q
```

Expected: PASS if Docker DB is reachable; SKIP if not reachable.

- [ ] **Step 5: Run required repo check**

Run:

```bash
make ci-local
```

Expected: PASS. Treat failures as real unless there is clear evidence of external dependency unavailability.

- [ ] **Step 6: Final commit if integration fixes were needed**

If any final fixes were needed:

```bash
git add <changed files>
git commit -m "fix: stabilize grounding upgrade integration"
```

Expected: no uncommitted changes.

---

## Self-Review

- Spec coverage: Task 1 covers discoverability, server instructions, resources, and tool descriptions. Task 2 covers compact publication passages, estimates, REST, and MCP. Task 3 covers review index inspection and failed source visibility. Task 4 covers zero-result diagnostics, optional diagnostics, and batch retrieval. Task 5 covers docs and Claude Code examples. Task 6 covers focused tests, PostgreSQL integration, and `make ci-local`.
- Placeholder scan: No open-ended implementation placeholders are intentionally left in task steps.
- Type consistency: Request/response names are consistent across models, services, adapters, routes, and MCP tools.
