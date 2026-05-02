# MCP Context Discipline and Ergonomics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PubTator-Link MCP review retrieval context-safe by default, add diagnostics and budgeting metadata, and expose flat v2 MCP tools for LLM-friendly calls.

**Architecture:** Keep existing REST and MCP contracts, then add additive model fields and v2 MCP aliases. Batch retrieval gets explicit response modes; compact mode returns merged passages and per-query summaries, while full mode preserves current behavior. Budgeting and truncation live in `ReviewContextService` so REST and MCP share the same behavior.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic v2, PostgreSQL repository abstractions, Ruff, mypy, pytest, uv, Makefile.

---

## File Map

- Modify `pubtator_link/models/review_rerag.py`: add response modes, budget metadata, dropped reasons, score metadata, source coverage, batch summaries, and new request fields.
- Modify `pubtator_link/services/review_context_service.py`: implement compact/full/diagnostics batch modes, response-size budgeting, bounded passage excerpts, table/reference controls, and summary diagnostics.
- Modify `pubtator_link/repositories/review_rerag.py`: infer source coverage and expose any score fields already present in rows.
- Modify `pubtator_link/mcp/tools.py`: add v2 flat-friendly request field constraints and shared literals where needed.
- Modify `pubtator_link/mcp/service_adapters.py`: add v2 adapter helpers that construct internal request models from flat args.
- Modify `pubtator_link/mcp/facade.py`: register v2 flat MCP tools, update descriptions, keep old wrapped tools.
- Modify `pubtator_link/mcp/resources.py`: add sample calls, output cheat sheet, budgeting defaults, and recommended modes.
- Modify `pubtator_link/api/routes/reviews.py`: ensure REST routes accept and return new model fields without route duplication.
- Modify `README.md` and `docs/MCP_CONNECTION_GUIDE.md`: document v2 tools, response modes, context budgets, and no-jq usage.
- Test `tests/unit/test_review_context_service.py`: service behavior and budgets.
- Test `tests/unit/test_review_rerag_models.py`: model defaults and validation.
- Test `tests/unit/mcp/test_review_rerag_mcp.py`: v2 tool registration and schema shape.
- Test `tests/unit/mcp/test_mcp_service_adapters.py`: v2 adapter calls.
- Test `tests/unit/mcp/test_mcp_facade.py`: capabilities/discovery.
- Test `tests/test_routes/test_reviews.py`: REST route shape.

## Task 1: Add Review Context Budget Models

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Test: `tests/unit/test_review_rerag_models.py`

- [ ] **Step 1: Write failing model tests**

Append these tests to `tests/unit/test_review_rerag_models.py`:

```python
def test_batch_request_defaults_to_compact_context_safe_mode() -> None:
    request = RetrieveReviewContextBatchRequest(queries=["MEFV colchicine"])

    assert request.response_mode == "compact"
    assert request.max_response_chars == 24000
    assert request.allow_truncated_passages is True
    assert request.max_chars_per_passage == 2200
    assert request.include_tables is False
    assert request.include_references is False
    assert request.table_mode == "preview"


def test_context_pack_budget_metadata_defaults() -> None:
    budget = ContextBudget(
        max_chars=12000,
        text_chars=1000,
        estimated_json_chars=1500,
        estimated_total_chars=2500,
        estimated_tokens=695,
    )
    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:1:abstract:0",
        pmid="1",
        section="ABSTRACT",
        text="Evidence text",
        char_count=13,
        start_char=0,
        end_char=13,
        boundary="full_passage",
    )
    pack = ContextPack(
        question="MEFV",
        passages=[passage],
        citation_map={"S1": "PMID:1:abstract:0"},
        total_chars=13,
        estimated_tokens=4,
        budget=budget,
    )

    assert pack.passages[0].truncated is False
    assert pack.budget.estimated_total_chars == 2500
    assert pack.dropped == []


def test_batch_summary_has_no_passage_text() -> None:
    summary = QueryDiagnosticsSummary(
        query="MEFV colchicine",
        query_tokens=["mefv", "colchicine"],
        candidate_count=3,
        selected_count=2,
        returned_count=1,
        dropped_count=1,
        top_sections=["ABSTRACT"],
        top_pmids=["123"],
        suggested_queries=["MEFV", "colchicine"],
    )

    assert "text" not in summary.model_dump()
    assert summary.zero_result_reason is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_models.py -q
```

Expected: FAIL with missing names or unexpected keyword arguments for the new
model fields.

- [ ] **Step 3: Add model types and fields**

In `pubtator_link/models/review_rerag.py`, add imports:

```python
import math
from typing import Literal
```

If `Literal` is already imported, only add `math`.

Add these definitions near the review context models:

```python
ReviewBatchResponseMode = Literal["compact", "merged_only", "full", "diagnostics"]
ReviewTableMode = Literal["off", "preview", "full"]
SourceCoverage = Literal["title_only", "abstract_only", "full_text", "curated_url", "unknown"]
ZeroResultReason = Literal[
    "review_not_indexed",
    "no_candidate_matches",
    "filters_excluded_all_candidates",
    "all_candidates_over_budget",
    "preparation_failed",
]


def estimate_tokens_from_chars(char_count: int) -> int:
    """Return a conservative tokenizer-free estimate for LLM context planning."""
    return max(1, math.ceil(char_count / 3.6))


class ContextBudget(BaseModel):
    """Approximate context budget accounting for an MCP/REST response."""

    max_chars: int
    text_chars: int
    estimated_json_chars: int
    estimated_total_chars: int
    estimated_tokens: int
    truncated: bool = False
    dropped_count: int = 0


class ContextDropReason(BaseModel):
    """Reason a candidate passage was not included in a compact response."""

    reason: str
    passage_id: str | None = None
    pmid: str | None = None
    section: str | None = None
    char_count: int | None = None


class PassageScore(BaseModel):
    """Transparent score features for a selected review passage."""

    lexical_rank: float = 0.0
    section_boost: float = 0.0
    entity_overlap: int = 0
    pmid_filter_boost: float = 0.0
    final_rank: float = 0.0


class QueryDiagnosticsSummary(BaseModel):
    """Compact per-query diagnostics for batch retrieval."""

    query: str
    query_tokens: list[str]
    candidate_count: int = 0
    selected_count: int = 0
    returned_count: int = 0
    dropped_count: int = 0
    top_sections: list[str] = Field(default_factory=list)
    top_pmids: list[str] = Field(default_factory=list)
    zero_result_reason: ZeroResultReason | None = None
    suggested_queries: list[str] = Field(default_factory=list)
```

Extend `ContextPassage`:

```python
    char_count: int | None = None
    truncated: bool = False
    start_char: int | None = None
    end_char: int | None = None
    boundary: str | None = None
    score: PassageScore | None = None
```

Extend `ContextPack`:

```python
    total_chars: int = 0
    estimated_tokens: int = 0
    budget: ContextBudget | None = None
    dropped: list[ContextDropReason] = Field(default_factory=list)
```

Extend `RetrieveReviewContextRequest`:

```python
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)
```

Extend `RetrieveReviewContextBatchRequest`:

```python
    response_mode: ReviewBatchResponseMode = "compact"
    max_response_chars: int = Field(default=24000, ge=2000, le=100000)
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)
```

Extend `RetrieveReviewContextBatchResponse`:

```python
    response_mode: ReviewBatchResponseMode = "compact"
    query_summaries: list[QueryDiagnosticsSummary] = Field(default_factory=list)
    budget: ContextBudget | None = None
```

Extend `ReviewSourceSummary` with:

```python
    coverage: SourceCoverage = "unknown"
```

- [ ] **Step 4: Run model tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/models/review_rerag.py tests/unit/test_review_rerag_models.py
git commit -m "feat: add review context budget models"
```

## Task 2: Implement Compact Batch Response Modes

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing service tests**

Append these tests to `tests/unit/test_review_context_service.py`:

```python
async def test_batch_compact_mode_omits_per_query_passage_text() -> None:
    repository = FakeReviewRepository(
        passages=[
            ReviewPassageRow(
                passage_id="p1",
                review_id="rev",
                source_id=1,
                source_kind="pmid",
                pmid="123",
                pmcid=None,
                doi=None,
                url=None,
                section="ABSTRACT",
                heading_path=[],
                page=None,
                text="MEFV colchicine evidence",
                entity_ids=[],
                relation_types=[],
                screening_status="included",
                source_metadata={},
                lexical_rank=0.1,
            )
        ]
    )
    service = ReviewContextService(repository=repository)

    response = await service.retrieve_context_batch(
        "rev",
        RetrieveReviewContextBatchRequest(
            queries=["MEFV", "colchicine"],
            response_mode="compact",
            max_chars=12000,
        ),
    )

    assert response.response_mode == "compact"
    assert response.merged_context_pack.passages[0].text == "MEFV colchicine evidence"
    assert response.results == []
    assert response.query_summaries
    assert response.query_summaries[0].returned_count == 1
    assert response.budget is not None


async def test_batch_full_mode_preserves_per_query_results() -> None:
    repository = FakeReviewRepository(
        passages=[
            ReviewPassageRow(
                passage_id="p1",
                review_id="rev",
                source_id=1,
                source_kind="pmid",
                pmid="123",
                pmcid=None,
                doi=None,
                url=None,
                section="ABSTRACT",
                heading_path=[],
                page=None,
                text="MEFV colchicine evidence",
                entity_ids=[],
                relation_types=[],
                screening_status="included",
                source_metadata={},
                lexical_rank=0.1,
            )
        ]
    )
    service = ReviewContextService(repository=repository)

    response = await service.retrieve_context_batch(
        "rev",
        RetrieveReviewContextBatchRequest(
            queries=["MEFV"],
            response_mode="full",
            max_chars=12000,
        ),
    )

    assert response.response_mode == "full"
    assert response.results[0].context_pack.passages[0].text == "MEFV colchicine evidence"


async def test_batch_diagnostics_mode_returns_no_passage_text() -> None:
    repository = FakeReviewRepository(passages=[])
    service = ReviewContextService(repository=repository)

    response = await service.retrieve_context_batch(
        "rev",
        RetrieveReviewContextBatchRequest(
            queries=["MEFV colchicine"],
            response_mode="diagnostics",
            include_diagnostics=True,
        ),
    )

    assert response.response_mode == "diagnostics"
    assert response.results == []
    assert response.merged_context_pack.passages == []
    assert response.query_summaries[0].zero_result_reason in {
        "review_not_indexed",
        "no_candidate_matches",
    }
```

Adjust constructor names if the test file uses a different fake repository
helper. Keep the assertion behavior identical.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: FAIL because batch still returns full `results` in default mode and
does not populate summaries/budget.

- [ ] **Step 3: Add budget and summary helpers**

In `pubtator_link/services/review_context_service.py`, import the new model
names:

```python
from pubtator_link.models.review_rerag import (
    ContextBudget,
    ContextDropReason,
    QueryDiagnosticsSummary,
    estimate_tokens_from_chars,
)
```

Add helper methods to `ReviewContextService`:

```python
    @staticmethod
    def _context_budget(max_chars: int, text_chars: int, dropped_count: int = 0) -> ContextBudget:
        estimated_json_chars = 1200 + int(text_chars * 0.25)
        estimated_total_chars = text_chars + estimated_json_chars
        return ContextBudget(
            max_chars=max_chars,
            text_chars=text_chars,
            estimated_json_chars=estimated_json_chars,
            estimated_total_chars=estimated_total_chars,
            estimated_tokens=estimate_tokens_from_chars(estimated_total_chars),
            dropped_count=dropped_count,
        )

    @staticmethod
    def _pack_totals(passages: Sequence[ContextPassage]) -> tuple[int, int]:
        text_chars = sum(len(passage.text) for passage in passages)
        return text_chars, estimate_tokens_from_chars(text_chars)

    def _query_summary(
        self,
        query: str,
        result: RetrieveReviewContextResponse,
        returned_count: int,
        dropped_count: int,
    ) -> QueryDiagnosticsSummary:
        passages = result.context_pack.passages
        diagnostics = result.diagnostics
        top_sections = list(dict.fromkeys(passage.section for passage in passages))[:5]
        top_pmids = [
            pmid
            for pmid in dict.fromkeys(passage.pmid for passage in passages)
            if pmid is not None
        ][:10]
        candidate_count = diagnostics.candidate_count if diagnostics else len(passages)
        selected_count = diagnostics.selected_count if diagnostics else len(passages)
        suggested_queries = diagnostics.suggested_queries if diagnostics else []
        query_tokens = diagnostics.query_tokens if diagnostics else self._query_tokens(query)
        zero_result_reason = None
        if returned_count == 0:
            zero_result_reason = "no_candidate_matches"
            if result.preparation_status.total == 0:
                zero_result_reason = "review_not_indexed"
            elif result.preparation_status.failed and not candidate_count:
                zero_result_reason = "preparation_failed"
            elif candidate_count and dropped_count:
                zero_result_reason = "all_candidates_over_budget"
        return QueryDiagnosticsSummary(
            query=query,
            query_tokens=query_tokens,
            candidate_count=candidate_count,
            selected_count=selected_count,
            returned_count=returned_count,
            dropped_count=dropped_count,
            top_sections=top_sections,
            top_pmids=top_pmids,
            zero_result_reason=zero_result_reason,
            suggested_queries=suggested_queries,
        )
```

If `PreparationStatus` has no `total` property, use:

```python
sum(
    [
        result.preparation_status.queued,
        result.preparation_status.running,
        result.preparation_status.complete,
        result.preparation_status.partial,
        result.preparation_status.failed,
    ]
)
```

- [ ] **Step 4: Update `retrieve_context_batch` response mode behavior**

Replace the body of `retrieve_context_batch()` with logic equivalent to:

```python
        results: list[RetrieveReviewContextResponse] = []
        query_summaries: list[QueryDiagnosticsSummary] = []
        merged_passages: list[ContextPassage] = []
        dropped: list[ContextDropReason] = []
        seen_passage_ids: set[str] = set()
        total_chars = 0

        for query in request.queries:
            result = await self.retrieve_context(
                review_id,
                RetrieveReviewContextRequest(
                    question=query,
                    pmids=request.pmids,
                    entity_ids=request.entity_ids,
                    sections=request.sections,
                    max_passages=request.max_passages_per_query,
                    max_chars=request.max_chars,
                    include_diagnostics=request.include_diagnostics
                    or request.response_mode == "diagnostics",
                    include_tables=request.include_tables,
                    include_references=request.include_references,
                    table_mode=request.table_mode,
                    allow_truncated_passages=request.allow_truncated_passages,
                    max_chars_per_passage=request.max_chars_per_passage,
                ),
            )
            if request.response_mode == "full":
                results.append(result)

            returned_for_query = 0
            dropped_for_query = 0
            if request.response_mode != "diagnostics":
                for passage in result.context_pack.passages:
                    if request.deduplicate_passages and passage.passage_id in seen_passage_ids:
                        dropped_for_query += 1
                        continue
                    if len(merged_passages) >= request.max_total_passages:
                        dropped_for_query += 1
                        dropped.append(
                            ContextDropReason(
                                reason="max_total_passages_exceeded",
                                passage_id=passage.passage_id,
                                pmid=passage.pmid,
                                section=passage.section,
                                char_count=len(passage.text),
                            )
                        )
                        break
                    if total_chars + len(passage.text) > request.max_chars:
                        dropped_for_query += 1
                        dropped.append(
                            ContextDropReason(
                                reason="char_budget_exceeded",
                                passage_id=passage.passage_id,
                                pmid=passage.pmid,
                                section=passage.section,
                                char_count=len(passage.text),
                            )
                        )
                        continue
                    seen_passage_ids.add(passage.passage_id)
                    merged_passages.append(
                        passage.model_copy(
                            update={"citation_key": f"S{len(merged_passages) + 1}"}
                        )
                    )
                    total_chars += len(passage.text)
                    returned_for_query += 1

            query_summaries.append(
                self._query_summary(
                    query=query,
                    result=result,
                    returned_count=returned_for_query,
                    dropped_count=dropped_for_query,
                )
            )

        citation_map = {passage.citation_key: passage.passage_id for passage in merged_passages}
        text_chars, estimated_tokens = self._pack_totals(merged_passages)
        budget = self._context_budget(
            max_chars=request.max_chars,
            text_chars=text_chars,
            dropped_count=len(dropped),
        )
        return RetrieveReviewContextBatchResponse(
            review_id=review_id,
            response_mode=request.response_mode,
            results=results,
            query_summaries=query_summaries,
            merged_context_pack=ContextPack(
                question="\n".join(request.queries),
                passages=merged_passages,
                citation_map=citation_map,
                total_chars=text_chars,
                estimated_tokens=estimated_tokens,
                budget=budget,
                dropped=dropped,
            ),
            preparation_status=await self._preparation_status(review_id),
            budget=budget,
        )
```

- [ ] **Step 5: Run service tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/services/review_context_service.py tests/unit/test_review_context_service.py
git commit -m "feat: compact batch review retrieval"
```

## Task 3: Add Oversized Passage Excerpts and Table Controls

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
async def test_single_retrieval_excerpts_oversized_passage() -> None:
    long_text = "intro " + ("background " * 200) + " MEFV colchicine " + ("evidence " * 200)
    repository = FakeReviewRepository(
        passages=[
            ReviewPassageRow(
                passage_id="p-long",
                review_id="rev",
                source_id=1,
                source_kind="pmid",
                pmid="123",
                pmcid=None,
                doi=None,
                url=None,
                section="DISCUSS",
                heading_path=[],
                page=None,
                text=long_text,
                entity_ids=[],
                relation_types=[],
                screening_status="included",
                source_metadata={},
                lexical_rank=0.1,
            )
        ]
    )
    service = ReviewContextService(repository=repository)

    response = await service.retrieve_context(
        "rev",
        RetrieveReviewContextRequest(
            question="MEFV colchicine",
            max_chars=1000,
            max_chars_per_passage=500,
            allow_truncated_passages=True,
        ),
    )

    passage = response.context_pack.passages[0]
    assert passage.truncated is True
    assert passage.char_count == len(passage.text)
    assert passage.start_char is not None
    assert passage.end_char is not None
    assert "MEFV colchicine" in passage.text
    assert len(passage.text) <= 500


async def test_review_retrieval_excludes_tables_by_default() -> None:
    repository = FakeReviewRepository(
        passages=[
            ReviewPassageRow(
                passage_id="p-table",
                review_id="rev",
                source_id=1,
                source_kind="pmid",
                pmid="123",
                pmcid=None,
                doi=None,
                url=None,
                section="TABLE",
                heading_path=[],
                page=None,
                text="MEFV colchicine table row",
                entity_ids=[],
                relation_types=[],
                screening_status="included",
                source_metadata={},
                lexical_rank=0.1,
            ),
            ReviewPassageRow(
                passage_id="p-abstract",
                review_id="rev",
                source_id=1,
                source_kind="pmid",
                pmid="123",
                pmcid=None,
                doi=None,
                url=None,
                section="ABSTRACT",
                heading_path=[],
                page=None,
                text="MEFV colchicine abstract evidence",
                entity_ids=[],
                relation_types=[],
                screening_status="included",
                source_metadata={},
                lexical_rank=0.2,
            ),
        ]
    )
    service = ReviewContextService(repository=repository)

    response = await service.retrieve_context(
        "rev",
        RetrieveReviewContextRequest(question="MEFV colchicine"),
    )

    assert [passage.section for passage in response.context_pack.passages] == ["ABSTRACT"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: FAIL because long passages are dropped or unbounded and table
controls are not applied.

- [ ] **Step 3: Implement section exclusion and excerpts**

In `ReviewContextService`, add helpers:

```python
    @staticmethod
    def _is_table_section(section: str) -> bool:
        return "table" in section.lower()

    @staticmethod
    def _is_reference_section(section: str) -> bool:
        lowered = section.lower()
        return "reference" in lowered or lowered in {"refs", "bibliography"}

    def _section_allowed(self, row: ReviewPassageRow, request: RetrieveReviewContextRequest) -> bool:
        if self._is_reference_section(row.section) and not request.include_references:
            return False
        if self._is_table_section(row.section):
            if request.table_mode == "off":
                return False
            if not request.include_tables and request.table_mode != "preview":
                return False
            if not request.include_tables and request.table_mode == "preview":
                return False
        return True

    def _excerpt_text(
        self,
        text: str,
        query_tokens: Sequence[str],
        max_chars: int,
    ) -> tuple[str, int, int, bool]:
        if len(text) <= max_chars:
            return text, 0, len(text), False
        lowered = text.lower()
        match_index = -1
        for token in query_tokens:
            match_index = lowered.find(token.lower())
            if match_index >= 0:
                break
        if match_index < 0:
            match_index = 0
        half_window = max_chars // 2
        start = max(0, match_index - half_window)
        end = min(len(text), start + max_chars)
        start = max(0, end - max_chars)
        return text[start:end], start, end, True
```

Update `_pack_passages()` so it:

- skips rows where `_section_allowed(row, request)` is false.
- uses `_excerpt_text()` when `allow_truncated_passages` is true and the row is
  larger than `max_chars_per_passage`.
- drops oversized rows with reason `passage_over_max_chars_per_passage` when
  truncation is disabled.
- sets `char_count`, `truncated`, `start_char`, `end_char`, and `boundary` on
  `ContextPassage`.

If `_pack_passages()` currently returns `ReviewPassageRow`, split the behavior:

```python
selected_rows = self._pack_passages(sorted_candidates, request)
passages = self._context_passages_from_rows(selected_rows, request)
```

The new converter should assign the citation keys and excerpt metadata.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/services/review_context_service.py tests/unit/test_review_context_service.py
git commit -m "feat: bound review passage excerpts"
```

## Task 4: Add Source Coverage to Review Index Inspection

**Files:**
- Modify: `pubtator_link/repositories/review_rerag.py`
- Test: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing coverage test**

Append:

```python
async def test_inspect_review_index_reports_source_coverage() -> None:
    repository = FakeReviewRepository(
        sources=[
            ReviewSourceSummary(
                source_id=1,
                pmid="123",
                source_kind="pmid",
                job_status="complete",
                error=None,
                attempt_statuses=["pubtator_full_text:complete"],
                sections=["ABSTRACT", "RESULTS"],
                passage_count=2,
                char_count=1000,
            )
        ]
    )
    service = ReviewContextService(repository=repository)

    response = await service.inspect_review_index("rev", InspectReviewIndexRequest())

    assert response.sources[0].coverage == "full_text"
```

If the existing fake repository does not accept `sources`, extend only the fake
test helper to support it.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py::test_inspect_review_index_reports_source_coverage -q
```

Expected: FAIL because coverage is missing or remains `unknown`.

- [ ] **Step 3: Add inference helper**

In `pubtator_link/repositories/review_rerag.py`, add:

```python
def _infer_source_coverage(
    source_kind: str,
    sections: Sequence[str],
    attempt_statuses: Sequence[str],
) -> SourceCoverage:
    if source_kind == "curated_url":
        return "curated_url"
    lowered_sections = {section.lower() for section in sections}
    lowered_attempts = " ".join(attempt_statuses).lower()
    if any(section not in {"title", "abstract"} for section in lowered_sections):
        return "full_text"
    if "full_text" in lowered_attempts and "complete" in lowered_attempts:
        return "full_text"
    if "abstract" in lowered_sections:
        return "abstract_only"
    if "title" in lowered_sections:
        return "title_only"
    return "unknown"
```

Import `Sequence` and `SourceCoverage` as needed.

Update `_source_summary_from_row()`:

```python
    sections = list(row["sections"] or [])
    attempt_statuses = list(row["attempt_statuses"] or [])
    return ReviewSourceSummary(
        ...
        attempt_statuses=attempt_statuses,
        sections=sections,
        ...
        coverage=_infer_source_coverage(
            source_kind=row["source_kind"],
            sections=sections,
            attempt_statuses=attempt_statuses,
        ),
    )
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/repositories/review_rerag.py tests/unit/test_review_context_service.py
git commit -m "feat: report review source coverage"
```

## Task 5: Add Flat v2 MCP Adapters and Tools

**Files:**
- Modify: `pubtator_link/mcp/tools.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing MCP registration test**

Append to `tests/unit/mcp/test_review_rerag_mcp.py`:

```python
def test_flat_v2_review_tools_are_registered_without_request_wrapper() -> None:
    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    assert "pubtator.retrieve_review_context_batch_v2" in tools
    schema = tools["pubtator.retrieve_review_context_batch_v2"].parameters
    properties = schema["properties"]
    assert "review_id" in properties
    assert "queries" in properties
    assert "request" not in properties
    assert properties["response_mode"]["default"] == "compact"
```

- [ ] **Step 2: Write failing adapter test**

Append to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
async def test_retrieve_review_context_batch_v2_adapter_builds_request() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_v2_impl

    class RecordingService:
        def __init__(self) -> None:
            self.review_id = None
            self.request = None

        async def retrieve_context_batch(self, review_id, request):
            self.review_id = review_id
            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                query_summaries=[],
                merged_context_pack=ContextPack(question="", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
            )

    service = RecordingService()

    result = await retrieve_review_context_batch_v2_impl(
        service=service,
        review_id="rev",
        queries=["MEFV", "colchicine"],
        response_mode="diagnostics",
        max_chars=8000,
        max_response_chars=12000,
        include_tables=False,
    )

    assert service.review_id == "rev"
    assert service.request.response_mode == "diagnostics"
    assert service.request.max_response_chars == 12000
    assert result["response_mode"] == "diagnostics"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: FAIL because v2 tools and adapter do not exist.

- [ ] **Step 4: Add adapter helper**

In `pubtator_link/mcp/service_adapters.py`, add:

```python
async def retrieve_review_context_batch_v2_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    queries: list[str],
    pmids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    sections: list[str] | None = None,
    response_mode: ReviewBatchResponseMode = "compact",
    max_passages_per_query: int = 8,
    max_total_passages: int = 20,
    max_chars: int = 12000,
    max_response_chars: int = 24000,
    deduplicate_passages: bool = True,
    include_diagnostics: bool = True,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode = "preview",
    allow_truncated_passages: bool = True,
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    response = await service.retrieve_context_batch(
        review_id=review_id,
        request=RetrieveReviewContextBatchRequest(
            queries=queries,
            pmids=pmids or [],
            entity_ids=entity_ids or [],
            sections=sections or [],
            response_mode=response_mode,
            max_passages_per_query=max_passages_per_query,
            max_total_passages=max_total_passages,
            max_chars=max_chars,
            max_response_chars=max_response_chars,
            deduplicate_passages=deduplicate_passages,
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        ),
    )
    return response.model_dump()
```

Import `ReviewBatchResponseMode` and `ReviewTableMode`.

- [ ] **Step 5: Register v2 batch tool**

In `pubtator_link/mcp/facade.py`, import the adapter and model literals. Register:

```python
    @mcp.tool(
        name="pubtator.retrieve_review_context_batch_v2",
        title="Retrieve Review Context Batch V2",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context_batch_v2(
        review_id: str,
        queries: list[str],
        pmids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        sections: list[str] | None = None,
        response_mode: ReviewBatchResponseMode = "compact",
        max_passages_per_query: int = 8,
        max_total_passages: int = 20,
        max_chars: int = 12000,
        max_response_chars: int = 24000,
        deduplicate_passages: bool = True,
        include_diagnostics: bool = True,
        include_tables: bool = False,
        include_references: bool = False,
        table_mode: ReviewTableMode = "preview",
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this flat-argument tool for compact review RAG retrieval without a request wrapper. Default response_mode compact returns merged passages plus per-query summaries; use diagnostics for query refinement and full only when per-query passage text is needed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await retrieve_review_context_batch_v2_impl(
            service=service,
            review_id=review_id,
            queries=queries,
            pmids=pmids,
            entity_ids=entity_ids,
            sections=sections,
            response_mode=response_mode,
            max_passages_per_query=max_passages_per_query,
            max_total_passages=max_total_passages,
            max_chars=max_chars,
            max_response_chars=max_response_chars,
            deduplicate_passages=deduplicate_passages,
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        )
```

- [ ] **Step 6: Run MCP tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/mcp/facade.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: add flat batch review mcp tool"
```

## Task 6: Add Remaining Flat v2 MCP Tools

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing registration test**

Append to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_common_flat_v2_tools_are_registered() -> None:
    mcp = create_pubtator_mcp()
    tool_names = set(mcp._tool_manager._tools)

    assert "pubtator.search_literature_v2" in tool_names
    assert "pubtator.search_biomedical_entities_v2" in tool_names
    assert "pubtator.get_publication_passages_v2" in tool_names
    assert "pubtator.inspect_review_index_v2" in tool_names
    assert "pubtator.retrieve_review_context_v2" in tool_names

    schema = mcp._tool_manager._tools["pubtator.retrieve_review_context_v2"].parameters
    assert "review_id" in schema["properties"]
    assert "question" in schema["properties"]
    assert "request" not in schema["properties"]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: FAIL because the v2 tools are not registered.

- [ ] **Step 3: Add flat adapter helpers**

Add helpers in `pubtator_link/mcp/service_adapters.py` that wrap existing
implementations by constructing existing request models:

```python
async def retrieve_review_context_v2_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    question: str,
    pmids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    sections: list[str] | None = None,
    max_passages: int = 8,
    max_chars: int = 6000,
    include_diagnostics: bool = False,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode = "preview",
    allow_truncated_passages: bool = True,
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    response = await service.retrieve_context(
        review_id=review_id,
        request=RetrieveReviewContextRequest(
            question=question,
            pmids=pmids or [],
            entity_ids=entity_ids or [],
            sections=sections or [],
            max_passages=max_passages,
            max_chars=max_chars,
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        ),
    )
    return response.model_dump()
```

Add similar flat wrappers for search, entity search, publication passages, and
inspect review index. Each wrapper should call the existing implementation with
the existing request model so behavior stays centralized.

- [ ] **Step 4: Register flat tools**

In `pubtator_link/mcp/facade.py`, register the v2 tools near their existing
wrapped counterparts. Use descriptions starting with “Use this flat-argument
tool...” and keep research-use limitations.

For `search_literature_v2`, expose:

```python
text: str
page: int = 1
sort: str | None = None
filters: str | None = None
sections: list[str] | None = None
```

For `search_biomedical_entities_v2`, expose:

```python
query: str
concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] | None = None
limit: int = 10
```

For `get_publication_passages_v2`, expose:

```python
pmids: list[str]
sections: list[str] | None = None
mode: Literal["abstracts", "compact_passages", "section_text"] = "compact_passages"
full: bool = False
max_passages_per_pmid: int = 6
max_chars: int = 12000
include_tables: bool = True
include_references: bool = False
```

For `inspect_review_index_v2`, expose:

```python
review_id: str
pmids: list[str] | None = None
include_passage_samples: bool = False
sample_per_pmid: int = 2
```

- [ ] **Step 5: Run MCP tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/mcp/facade.py pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: add flat mcp grounding tools"
```

## Task 7: Update REST Route Tests for New Batch Shape

**Files:**
- Modify: `tests/test_routes/test_reviews.py`
- Modify: `pubtator_link/api/routes/reviews.py` only if needed

- [ ] **Step 1: Write route test for compact response mode**

Append or update a route test:

```python
async def test_retrieve_review_context_batch_accepts_response_mode(client, monkeypatch) -> None:
    service = AsyncMock()
    service.retrieve_context_batch.return_value = RetrieveReviewContextBatchResponse(
        review_id="rev",
        response_mode="diagnostics",
        results=[],
        query_summaries=[
            QueryDiagnosticsSummary(
                query="MEFV",
                query_tokens=["mefv"],
                candidate_count=0,
                selected_count=0,
                returned_count=0,
                dropped_count=0,
                top_sections=[],
                top_pmids=[],
                zero_result_reason="no_candidate_matches",
                suggested_queries=["colchicine"],
            )
        ],
        merged_context_pack=ContextPack(question="MEFV", passages=[], citation_map={}),
        preparation_status=PreparationStatus(),
    )
    monkeypatch.setattr(
        "pubtator_link.api.routes.reviews.get_review_context_service",
        AsyncMock(return_value=service),
    )

    response = await client.post(
        "/api/reviews/rev/context-batch",
        json={"queries": ["MEFV"], "response_mode": "diagnostics"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_mode"] == "diagnostics"
    assert body["results"] == []
    assert body["query_summaries"][0]["zero_result_reason"] == "no_candidate_matches"
```

Use the actual route path in the file if it differs.

- [ ] **Step 2: Run route tests**

Run:

```bash
uv run pytest tests/test_routes/test_reviews.py -q
```

Expected: PASS or FAIL only for route path/import mismatches. Fix the route
test to match existing test fixtures and route naming; route implementation
should not need substantial changes because it already consumes Pydantic models.

- [ ] **Step 3: Commit**

Run:

```bash
git add tests/test_routes/test_reviews.py pubtator_link/api/routes/reviews.py
git commit -m "test: cover review batch response modes"
```

## Task 8: Improve Capabilities Resource and Docs

**Files:**
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `README.md`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing capabilities test**

Append to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_capabilities_include_context_management_cheatsheet() -> None:
    capabilities = get_capabilities_resource()

    assert "sample_calls" in capabilities
    assert "output_cheatsheet" in capabilities
    assert "budgeting_defaults" in capabilities
    assert capabilities["budgeting_defaults"]["batch_response_mode"] == "compact"
    assert "pubtator.retrieve_review_context_batch_v2" in capabilities["sample_calls"]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py::test_capabilities_include_context_management_cheatsheet -q
```

Expected: FAIL because these keys are missing.

- [ ] **Step 3: Update capabilities**

In `pubtator_link/mcp/resources.py`, extend `get_capabilities_resource()` with:

```python
        "sample_calls": {
            "pubtator.search_literature_v2": {
                "text": "MEFV colchicine familial Mediterranean fever guideline",
                "sort": "score desc",
            },
            "pubtator.retrieve_review_context_batch_v2": {
                "review_id": "fmf-colchicine-guidelines",
                "queries": ["MEFV colchicine", "familial Mediterranean fever child", "EULAR PReS recommendation"],
                "response_mode": "compact",
                "max_chars": 12000,
                "max_response_chars": 24000,
            },
            "pubtator.retrieve_review_context_batch_v2_diagnostics": {
                "review_id": "fmf-colchicine-guidelines",
                "queries": ["MEFV colchicine", "FMF guideline"],
                "response_mode": "diagnostics",
            },
        },
        "output_cheatsheet": {
            "search_pmids": "results[].pmid",
            "single_context_passages": "context_pack.passages[]",
            "batch_merged_passages": "merged_context_pack.passages[]",
            "batch_query_summaries": "query_summaries[]",
            "citation_map": "merged_context_pack.citation_map",
            "budget": "budget",
        },
        "budgeting_defaults": {
            "batch_response_mode": "compact",
            "batch_max_chars": 12000,
            "batch_max_response_chars": 24000,
            "max_chars_per_passage": 2200,
            "tables": "preview/off by default for review retrieval",
        },
```

- [ ] **Step 4: Update README**

In `README.md`, update the MCP tool list so compact and v2 tools are visible
before raw BioC tools. Add a short section:

```markdown
### Context-Safe Review Retrieval

Prefer `pubtator.retrieve_review_context_batch_v2` for LLM clients. It uses flat
arguments and defaults to `response_mode="compact"`, returning merged citable
passages plus per-query summaries. Use `response_mode="diagnostics"` to refine
queries without passage text, and `response_mode="full"` only when full
per-query passage packs are intentionally needed.
```

- [ ] **Step 5: Update connection guide**

In `docs/MCP_CONNECTION_GUIDE.md`, add:

```markdown
For Claude Code, v2 tools use flat arguments and are easier to call than the
compatibility tools that accept `{ "request": { ... } }`. If tools are deferred,
ask Claude to search for `PubTator compact passages review RAG PMID`.

Recommended batch modes:

- `compact`: default; merged passages plus per-query summaries.
- `diagnostics`: no passage text; use for query refinement and zero-result
  debugging.
- `merged_only`: smallest citable passage response.
- `full`: full per-query responses; can be large.
```

- [ ] **Step 6: Run docs/capabilities tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/mcp/resources.py README.md docs/MCP_CONNECTION_GUIDE.md tests/unit/mcp/test_mcp_facade.py
git commit -m "docs: describe context-safe mcp usage"
```

## Task 9: Final Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run focused review and MCP tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_context_service.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/test_routes/test_reviews.py -q
```

Expected: PASS.

- [ ] **Step 2: Run formatting**

Run:

```bash
make format
```

Expected: Ruff formats files or reports no changes.

- [ ] **Step 3: Run lint and typecheck**

Run:

```bash
make lint
make typecheck-fast
```

Expected: both pass.

- [ ] **Step 4: Run required local CI**

Run:

```bash
make ci-local
```

Expected: PASS. If PostgreSQL integration tests skip because
`PUBTATOR_LINK_TEST_DATABASE_URL` is unset, report the skip clearly. If Docker
Postgres is running, use:

```bash
PUBTATOR_LINK_TEST_DATABASE_URL=postgresql://pubtator_link:pubtator_link@localhost:55432/pubtator_link make ci-local
```

or the port configured by the local Compose stack.

- [ ] **Step 5: Commit any formatting-only changes**

If `make format` changed files after the previous task commits, run:

```bash
git add pubtator_link tests README.md docs/MCP_CONNECTION_GUIDE.md
git commit -m "style: format mcp context discipline changes"
```

Expected: commit only if formatting changed tracked files.

## Self-Review

- Spec coverage: Tasks 1-3 cover budget metadata, response modes, hard payload
  discipline, table/reference controls, and oversized passages. Task 4 covers
  source coverage. Tasks 5-6 cover flat v2 MCP tools. Task 8 covers
  discoverability, capabilities, and docs. Task 9 covers verification.
- Placeholder scan: The plan intentionally avoids deferred implementation
  placeholders. Where existing tests may use different fake helper names, the
  required behavior and exact assertions are specified.
- Type consistency: The plan uses `ReviewBatchResponseMode`,
  `ReviewTableMode`, `ContextBudget`, `ContextDropReason`,
  `QueryDiagnosticsSummary`, and `SourceCoverage` consistently across models,
  service, adapters, and tests.

