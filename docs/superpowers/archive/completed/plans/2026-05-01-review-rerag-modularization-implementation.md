# Review re-RAG Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split review re-RAG internals into focused modules while preserving REST, MCP, and model behavior.

**Architecture:** Keep `ReviewContextService` as the public orchestration facade. Extract row mappers, ranking, packing, diagnostics, and batch budgeting into helper modules with focused tests, moving code rather than rewriting algorithms.

**Tech Stack:** Python 3.11, Pydantic models, pytest, Ruff, mypy, uv, Make.

---

## File Structure

- Create `pubtator_link/repositories/review_rerag_mappers.py`: row conversion and SQL helper functions.
- Modify `pubtator_link/repositories/review_rerag.py`: import mapper helpers and keep SQL execution.
- Create `pubtator_link/services/review_context/__init__.py`: review context helper package marker.
- Create `pubtator_link/services/review_context/ranking.py`: ranking constants and key function.
- Create `pubtator_link/services/review_context/packing.py`: single-query packing, section filtering, truncation, budget totals.
- Create `pubtator_link/services/review_context/diagnostics.py`: query tokenization, suggestions, diagnostics, query summaries.
- Create `pubtator_link/services/review_context/batch_budgeting.py`: merged batch selection and source budget accounting.
- Modify `pubtator_link/services/review_context_service.py`: orchestrate helpers.
- Add tests:
  - `tests/unit/test_review_rerag_mappers.py`
  - `tests/unit/test_review_context_ranking.py`
  - `tests/unit/test_review_context_packing.py`
  - `tests/unit/test_review_context_diagnostics.py`
  - `tests/unit/test_review_context_batch_budgeting.py`

## Task 1: Extract Repository Mappers

**Files:**
- Create: `pubtator_link/repositories/review_rerag_mappers.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Test: `tests/unit/test_review_rerag_mappers.py`

- [ ] **Step 1: Write mapper tests**

Create `tests/unit/test_review_rerag_mappers.py`:

```python
from __future__ import annotations

import json

from pubtator_link.repositories.review_rerag_mappers import (
    _infer_source_coverage,
    _parse_execute_count,
    _passage_from_row,
    _preparation_status_from_row,
    _recall_tsquery,
)


def test_preparation_status_from_missing_row_defaults_to_zero() -> None:
    status = _preparation_status_from_row(None)

    assert status.total == 0
    assert status.failed == 0


def test_passage_from_row_decodes_json_metadata() -> None:
    row = {
        "passage_id": "p1",
        "review_id": "r1",
        "source_id": "s1",
        "source_kind": "pubtator_abstract",
        "pmid": "123",
        "pmcid": None,
        "doi": None,
        "url": None,
        "section": "abstract",
        "heading_path": ["Abstract"],
        "page": None,
        "text": "MEFV colchicine evidence",
        "entity_ids": ["@GENE_MEFV"],
        "relation_types": [],
        "screening_status": "included",
        "source_metadata": json.dumps({"journal": "Example"}),
        "lexical_rank": 2.5,
    }

    passage = _passage_from_row(row)

    assert passage.passage_id == "p1"
    assert passage.source_metadata == {"journal": "Example"}
    assert passage.lexical_rank == 2.5


def test_infer_source_coverage_prefers_full_text_sections() -> None:
    assert (
        _infer_source_coverage(
            source_kind="pubtator_full_bioc",
            sections=["abstract", "results"],
            attempt_statuses=[],
        )
        == "full_text"
    )
    assert (
        _infer_source_coverage(
            source_kind="pubtator_abstract",
            sections=["abstract"],
            attempt_statuses=[],
        )
        == "abstract_only"
    )


def test_parse_execute_count_and_recall_query_are_stable() -> None:
    assert _parse_execute_count("INSERT 0 7") == 7
    assert _parse_execute_count("UPDATE") == 0
    assert _recall_tsquery("MEFV MEFV colchicine response in FMF") == "mefv | colchicine | response | fmf"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_review_rerag_mappers.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'pubtator_link.repositories.review_rerag_mappers'`.

- [ ] **Step 3: Move mapper functions**

Create `pubtator_link/repositories/review_rerag_mappers.py` by moving these functions unchanged from `review_rerag.py`:

- `_filter_or_none`
- `_preparation_status_from_row`
- `_passage_from_row`
- `_source_summary_from_row`
- `_infer_source_coverage`
- `_failed_source_summary_from_row`
- `_passage_sample_from_row`
- `_review_index_totals_from_row`
- `_parse_execute_count`
- `_recall_tsquery`

Required imports:

```python
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    PreparationStatus,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewPassageSample,
    ReviewSourceSummary,
    SourceCoverage,
)
```

- [ ] **Step 4: Import helpers in repository**

In `pubtator_link/repositories/review_rerag.py`, delete the moved function definitions and add:

```python
from pubtator_link.repositories.review_rerag_mappers import (
    _failed_source_summary_from_row,
    _filter_or_none,
    _parse_execute_count,
    _passage_from_row,
    _passage_sample_from_row,
    _preparation_status_from_row,
    _recall_tsquery,
    _review_index_totals_from_row,
    _source_summary_from_row,
)
```

Remove imports that become unused in `review_rerag.py`, especially `json`, `re`, and mapper-only model imports if Ruff flags them.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/unit/test_review_rerag_mappers.py tests/unit/test_review_rerag_repository.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/repositories/review_rerag.py pubtator_link/repositories/review_rerag_mappers.py tests/unit/test_review_rerag_mappers.py
git commit -m "refactor: extract review rerag row mappers"
```

## Task 2: Extract Ranking

**Files:**
- Create: `pubtator_link/services/review_context/__init__.py`
- Create: `pubtator_link/services/review_context/ranking.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_ranking.py`

- [ ] **Step 1: Write ranking tests**

Create `tests/unit/test_review_context_ranking.py`:

```python
from __future__ import annotations

from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.services.review_context.ranking import rerank_key


def _row(passage_id: str, *, rank: float, section: str, source_kind: str) -> ReviewPassageRow:
    return ReviewPassageRow(
        passage_id=passage_id,
        review_id="r1",
        source_id="s1",
        source_kind=source_kind,
        pmid="123",
        pmcid=None,
        doi=None,
        url=None,
        section=section,
        heading_path=[],
        page=None,
        text="text",
        entity_ids=[],
        relation_types=[],
        screening_status=None,
        source_metadata={},
        lexical_rank=rank,
    )


def test_rerank_key_prefers_higher_rank_then_section_then_source() -> None:
    rows = [
        _row("body", rank=1.0, section="body", source_kind="pubtator_abstract"),
        _row("abstract", rank=1.0, section="abstract", source_kind="pubtator_abstract"),
        _row("full", rank=1.0, section="abstract", source_kind="pubtator_full_bioc"),
        _row("best", rank=2.0, section="body", source_kind="pubtator_abstract"),
    ]

    assert [row.passage_id for row in sorted(rows, key=rerank_key)] == [
        "best",
        "full",
        "abstract",
        "body",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_review_context_ranking.py -q
```

Expected: fail with missing module.

- [ ] **Step 3: Create ranking module**

Create `pubtator_link/services/review_context/__init__.py`:

```python
"""Focused helpers for review context retrieval."""
```

Create `pubtator_link/services/review_context/ranking.py` by moving `SECTION_PRIORITY`, `SOURCE_PRIORITY`, `SOURCE_COVERAGE_SCARCITY_PRIORITY`, and `_rerank_key` logic:

```python
from __future__ import annotations

from pubtator_link.models.review_rerag import ReviewPassageRow

SECTION_PRIORITY = {
    "title": 0,
    "abstract": 1,
    "abstr": 1,
    "summary": 2,
    "introduction": 3,
    "intro": 3,
    "background": 4,
    "methods": 5,
    "method": 5,
    "materials and methods": 5,
    "results": 6,
    "result": 6,
    "discussion": 7,
    "discuss": 7,
    "conclusion": 8,
    "conclusions": 8,
    "concl": 8,
    "table": 9,
    "body": 10,
    "ref": 50,
    "references": 50,
}

SOURCE_PRIORITY = {
    "pubtator_full_bioc": 0,
    "pmc_bioc": 1,
    "europe_pmc_jats": 2,
    "curated_pdf": 3,
    "curated_html": 4,
    "docling_pdf": 5,
    "pubtator_abstract": 6,
}

SOURCE_COVERAGE_SCARCITY_PRIORITY = {
    "title_only": 0,
    "abstract_only": 1,
    "curated_url": 2,
    "full_text": 3,
    "unknown": 4,
}


def rerank_key(row: ReviewPassageRow) -> tuple[float, int, int, str, str]:
    return (
        -row.lexical_rank,
        SECTION_PRIORITY.get(row.section.strip().lower(), 100),
        SOURCE_PRIORITY.get(row.source_kind, 100),
        row.pmid or "",
        row.passage_id,
    )
```

When writing the file, use the exact current dictionaries from `review_context_service.py`.

- [ ] **Step 4: Use ranking helper from service**

In `ReviewContextService.retrieve_context()`, replace:

```python
sorted_candidates = sorted(candidates, key=self._rerank_key)
```

with:

```python
sorted_candidates = sorted(candidates, key=rerank_key)
```

Import:

```python
from pubtator_link.services.review_context.ranking import (
    SOURCE_COVERAGE_SCARCITY_PRIORITY,
    rerank_key,
)
```

Delete `SECTION_PRIORITY`, `SOURCE_PRIORITY`, `SOURCE_COVERAGE_SCARCITY_PRIORITY`, and `_rerank_key` from `review_context_service.py`.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_ranking.py tests/unit/test_review_context_service.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/review_context pubtator_link/services/review_context_service.py tests/unit/test_review_context_ranking.py
git commit -m "refactor: extract review context ranking"
```

## Task 3: Extract Packing Helpers

**Files:**
- Create: `pubtator_link/services/review_context/packing.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_packing.py`

- [ ] **Step 1: Write packing tests**

Create `tests/unit/test_review_context_packing.py` with tests for query-window truncation and over-budget drops. Use the same `_row()` helper shape as Task 2 and import:

```python
from pubtator_link.models.review_rerag import RetrieveReviewContextRequest
from pubtator_link.services.review_context.packing import (
    context_budget,
    context_passage_from_row,
    excerpt_text,
    pack_passages,
)
```

Test code:

```python
def test_excerpt_text_centers_first_query_token() -> None:
    text = "A" * 50 + " colchicine " + "B" * 50

    excerpt, start, end, truncated = excerpt_text(
        text,
        query_tokens=["colchicine"],
        max_chars=40,
        allow_truncated=True,
    )

    assert truncated is True
    assert "colchicine" in excerpt
    assert end - start == 40


def test_pack_passages_drops_over_budget_passage() -> None:
    row = _row("p1", rank=1.0, section="abstract", source_kind="pubtator_abstract")
    row.text = "x" * 100
    request = RetrieveReviewContextRequest(question="MEFV", max_chars=10)

    packed = pack_passages([row], request)

    assert packed.selected == []
    assert packed.dropped[0].reason == "char_budget_exceeded"


def test_context_budget_estimates_total_chars() -> None:
    budget = context_budget(max_chars=1000, text_chars=400, dropped_count=2)

    assert budget.max_chars == 1000
    assert budget.text_chars == 400
    assert budget.estimated_total_chars > 400
    assert budget.dropped_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_review_context_packing.py -q
```

Expected: fail with missing module.

- [ ] **Step 3: Create packing module**

Create `packing.py` by moving these methods and making them module functions:

- `_pack_passages` -> `pack_passages`
- `_context_passage_from_row` -> `context_passage_from_row`
- `_effective_passage_len` -> `effective_passage_len`
- `_is_table_section` -> `is_table_section`
- `_is_reference_section` -> `is_reference_section`
- `_section_allowed` -> `section_allowed`
- `_excerpt_text` -> `excerpt_text`
- `_context_budget` -> `context_budget`
- `_pack_totals` -> `pack_totals`

Define:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PackedPassages:
    selected: list[ReviewPassageRow]
    dropped: list[ContextDropReason]
```

Return `PackedPassages` from `pack_passages`.

- [ ] **Step 4: Update service usage**

In `retrieve_context()`, replace:

```python
selected, dropped = self._pack_passages(sorted_candidates, request)
passages = [
    self._context_passage_from_row(index=index, row=row, request=request)
    for index, row in enumerate(selected, start=1)
]
text_chars, estimated_tokens = self._pack_totals(passages)
budget = self._context_budget(
    max_chars=request.max_chars,
    text_chars=text_chars,
    dropped_count=len(dropped),
)
```

with:

```python
packed = pack_passages(sorted_candidates, request)
selected = packed.selected
dropped = packed.dropped
passages = [
    context_passage_from_row(index=index, row=row, request=request)
    for index, row in enumerate(selected, start=1)
]
text_chars, estimated_tokens = pack_totals(passages)
budget = context_budget(
    max_chars=request.max_chars,
    text_chars=text_chars,
    dropped_count=len(dropped),
)
```

Replace remaining `self._pack_totals` and `self._context_budget` calls in batch retrieval with `pack_totals` and `context_budget`.

Delete moved private methods from `ReviewContextService`.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_packing.py tests/unit/test_review_context_service.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/review_context/packing.py pubtator_link/services/review_context_service.py tests/unit/test_review_context_packing.py
git commit -m "refactor: extract review context packing"
```

## Task 4: Extract Diagnostics Helpers

**Files:**
- Create: `pubtator_link/services/review_context/diagnostics.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_diagnostics.py`

- [ ] **Step 1: Write diagnostics tests**

Create tests for tokenization, query suggestions, and query summary zero-result reason:

```python
from __future__ import annotations

from pubtator_link.models.review_rerag import ContextPack, PreparationStatus, RetrieveReviewContextResponse
from pubtator_link.services.review_context.diagnostics import query_summary, query_tokens, suggested_queries


def test_query_tokens_deduplicates_and_limits_short_tokens() -> None:
    assert query_tokens("MEFV and FMF colchicine MEFV in children") == [
        "mefv",
        "fmf",
        "colchicine",
        "children",
    ]


def test_suggested_queries_removes_section_tokens() -> None:
    assert suggested_queries(["mefv", "abstract", "colchicine"], ["abstract"]) == [
        "mefv colchicine"
    ]


def test_query_summary_marks_unindexed_review() -> None:
    result = RetrieveReviewContextResponse(
        review_id="r1",
        context_pack=ContextPack(question="MEFV", passages=[], citation_map={}),
        preparation_status=PreparationStatus(),
        diagnostics=None,
    )

    summary = query_summary(query="MEFV", result=result, returned_count=0, dropped_count=0)

    assert summary.zero_result_reason == "review_not_indexed"
    assert summary.next_steps == ["index_review_evidence", "inspect_review_index"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_review_context_diagnostics.py -q
```

Expected: fail with missing module.

- [ ] **Step 3: Create diagnostics module**

Move these methods to module functions:

- `_query_summary` -> `query_summary`
- `_query_tokens` -> `query_tokens`
- `_suggested_queries` -> `suggested_queries`

Also add:

```python
async def build_diagnostics(
    *,
    repository: ReviewContextRepository,
    review_id: str,
    request: RetrieveReviewContextRequest,
    candidate_count: int,
    selected_count: int,
) -> RetrieveReviewDiagnostics:
    query_tokens_value = query_tokens(request.question)
    available_sections = await repository.available_sections(review_id)
    indexed_pmids = await repository.indexed_pmids(review_id)
    failed_sources = await repository.list_review_failed_sources(review_id)
    section_label = ", ".join(available_sections) if available_sections else "none"
    message = (
        f"No passages selected. Review {review_id} has {len(indexed_pmids)} indexed PMIDs "
        f"and sections {section_label}. Try shorter keyword queries or remove section filters."
        if selected_count == 0
        else f"Selected {selected_count} passages from {candidate_count} candidates."
    )
    return RetrieveReviewDiagnostics(
        query=request.question,
        query_tokens=query_tokens_value,
        candidate_count=candidate_count,
        selected_count=selected_count,
        available_sections=available_sections,
        indexed_pmids=indexed_pmids,
        failed_sources=failed_sources,
        filter_summary={
            "pmids": list(request.pmids),
            "entity_ids": list(request.entity_ids),
            "sections": list(request.sections),
        },
        suggested_queries=suggested_queries(query_tokens_value, available_sections),
        message=message,
    )
```

Because `ReviewContextRepository` is currently defined in `review_context_service.py`, use a local `Protocol` in `diagnostics.py` with only `available_sections`, `indexed_pmids`, and `list_review_failed_sources`.

- [ ] **Step 4: Update service usage**

Replace:

```python
diagnostics = await self._diagnostics(
    review_id=review_id,
    request=request,
    candidate_count=len(candidates),
    selected_count=len(selected),
)
```

with:

```python
diagnostics = await build_diagnostics(
    repository=self.repository,
    review_id=review_id,
    request=request,
    candidate_count=len(candidates),
    selected_count=len(selected),
)
```

Replace calls using the old private summary helper:

```python
self._query_summary(
    query=request.queries[query_index],
    result=result,
    returned_count=returned_counts[query_index],
    dropped_count=dropped_counts[query_index],
)
```

with the module function:

```python
query_summary(
    query=request.queries[query_index],
    result=result,
    returned_count=returned_counts[query_index],
    dropped_count=dropped_counts[query_index],
)
```

Replace calls to `self._query_tokens(query)` with `query_tokens(query)`.

Delete moved private methods from `ReviewContextService`.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_diagnostics.py tests/unit/test_review_context_service.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/review_context/diagnostics.py pubtator_link/services/review_context_service.py tests/unit/test_review_context_diagnostics.py
git commit -m "refactor: extract review context diagnostics"
```

## Task 5: Extract Batch Budgeting

**Files:**
- Create: `pubtator_link/services/review_context/batch_budgeting.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`

- [ ] **Step 1: Write batch budgeting characterization tests**

Create helper tests for the highest-risk behavior before moving code:

```python
from __future__ import annotations

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    PreparationStatus,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextResponse,
)
from pubtator_link.services.review_context.batch_budgeting import merge_batch_context


def _passage(passage_id: str, text: str, pmid: str = "1") -> ContextPassage:
    return ContextPassage(
        citation_key="S1",
        passage_id=passage_id,
        source_id=f"source-{pmid}",
        pmid=pmid,
        pmcid=None,
        section="abstract",
        text=text,
        source_kind="pubtator_abstract",
    )


def _result(query: str, passages: list[ContextPassage]) -> RetrieveReviewContextResponse:
    return RetrieveReviewContextResponse(
        review_id="r1",
        context_pack=ContextPack(question=query, passages=passages, citation_map={}),
        preparation_status=PreparationStatus(complete=1),
        diagnostics=None,
    )


def test_merge_batch_context_deduplicates_passages() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1", "q2"],
        max_total_passages=5,
        max_chars=1000,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[
            _result("q1", [_passage("p1", "one")]),
            _result("q2", [_passage("p1", "one")]),
        ],
        coverage_by_source={},
    )

    assert [passage.passage_id for passage in merged.passages] == ["p1"]
    assert merged.dropped[0].reason == "duplicate_passage"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py -q
```

Expected: fail with missing module.

- [ ] **Step 3: Create batch budgeting module**

Move the merge-specific local functions and loops from `retrieve_context_batch()`
into `merge_batch_context`.

Define return container:

```python
from dataclasses import dataclass

@dataclass
class MergedBatchContext:
    passages: list[ContextPassage]
    dropped: list[ContextDropReason]
    query_summaries: list[QueryDiagnosticsSummary]
    source_budget_summaries: list[SourceBudgetSummary]
    text_chars: int
    estimated_tokens: int
    budget_text_chars: int
```

Signature:

```python
def merge_batch_context(
    *,
    request: RetrieveReviewContextBatchRequest,
    query_results: list[RetrieveReviewContextResponse],
    coverage_by_source: dict[str, SourceCoverage],
) -> MergedBatchContext:
    merged_passages: list[ContextPassage] = []
    dropped: list[ContextDropReason] = []
    query_summaries: list[QueryDiagnosticsSummary] = []
    source_budget_summaries: list[SourceBudgetSummary] = []
    text_chars = 0
    estimated_tokens = 0
    budget_text_chars = 0
    # Move the current merge loops from ReviewContextService.retrieve_context_batch()
    # into this function without changing branch behavior.
    return MergedBatchContext(
        passages=merged_passages,
        dropped=dropped,
        query_summaries=query_summaries,
        source_budget_summaries=source_budget_summaries,
        text_chars=text_chars,
        estimated_tokens=estimated_tokens,
        budget_text_chars=budget_text_chars,
    )
```

The function must preserve current handling for:

- `response_mode == "diagnostics"`
- `budget_strategy == "query_fair"`
- `budget_strategy in {"source_fair", "scarcity_first"}`
- duplicate passage drops
- max total passage drops
- char budget drops
- response char budget drops
- source budget summaries

- [ ] **Step 4: Update service orchestration**

In `retrieve_context_batch()`:

1. Keep the loop that calls `self.retrieve_context` with the same
   `RetrieveReviewContextRequest` fields currently built from the batch request:
   `question`, `pmids`, `entity_ids`, `sections`, `max_passages`,
   `max_chars`, `include_diagnostics`, `include_tables`,
   `include_references`, `table_mode`, `allow_truncated_passages`, and
   `max_chars_per_passage`.
2. Build `results` only for `response_mode == "full"`.
3. Fetch `coverage_by_source = await self._source_coverage_by_key(review_id)` only when `request.budget_strategy != "query_fair"`.
4. Call `merge_batch_context(request=request, query_results=query_results, coverage_by_source=coverage_by_source)`.
5. Use returned values to construct `RetrieveReviewContextBatchResponse`.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/review_context/batch_budgeting.py pubtator_link/services/review_context_service.py tests/unit/test_review_context_batch_budgeting.py
git commit -m "refactor: extract review context batch budgeting"
```

## Task 6: Final Cleanup And Verification

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: helper modules as needed.

- [ ] **Step 1: Remove unused imports and private methods**

Run:

```bash
uv run ruff check pubtator_link/services/review_context_service.py pubtator_link/services/review_context pubtator_link/repositories/review_rerag.py pubtator_link/repositories/review_rerag_mappers.py
```

Fix only unused imports, typing issues, or names caused by the extraction.

- [ ] **Step 2: Format touched modules**

```bash
uv run ruff format pubtator_link/services/review_context_service.py pubtator_link/services/review_context pubtator_link/repositories/review_rerag.py pubtator_link/repositories/review_rerag_mappers.py tests/unit/test_review_context_ranking.py tests/unit/test_review_context_packing.py tests/unit/test_review_context_diagnostics.py tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_rerag_mappers.py
```

Expected: files formatted or left unchanged.

- [ ] **Step 3: Run focused review tests**

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/unit/test_review_rerag_models.py tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Run full verification**

```bash
make ci-local
make test-cov
```

Expected:

- `make ci-local` exits 0.
- `make test-cov` exits 0 and reports coverage at or above 80%.

- [ ] **Step 5: Commit final cleanup**

```bash
git add pubtator_link/services/review_context_service.py pubtator_link/services/review_context pubtator_link/repositories/review_rerag.py pubtator_link/repositories/review_rerag_mappers.py tests/unit
git commit -m "refactor: modularize review rerag internals"
```

## Plan Self-Review Checklist

- Spec coverage: Tasks cover repository mappers, ranking, packing, diagnostics, batch budgeting, and final verification.
- Placeholder scan: code steps name exact modules, functions, and expected commands; dictionary copy instruction points to current source to avoid stale partial mappings.
- Type consistency: helper names match service update instructions and tests.
