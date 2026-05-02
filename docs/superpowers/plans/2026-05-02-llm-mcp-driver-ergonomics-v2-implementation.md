# LLM MCP Driver Ergonomics V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact MCP driver contract, top-level retrieval recovery, passage quote/confidence metadata, better dropped/preflight guidance, wait-mode progress, and a thin selected-passage audit trail helper.

**Architecture:** Keep all public changes additive. Put shared response models in `pubtator_link/models/review_rerag.py`, deterministic retrieval helpers in `pubtator_link/services/review_context/`, and MCP wiring in the existing review tool/adapters layer. Preserve progressive discovery by improving `pubtator.get_server_capabilities` instead of hiding or eagerly forcing tools.

**Tech Stack:** Python 3.11, Pydantic v2, FastMCP, FastAPI, pytest, Ruff, mypy, uv, Makefile.

---

## File Structure

- Modify `pubtator_link/models/review_rerag.py`: add `RecoveryHint`, `RecoverySuggestedFilters`, `RecoveryBudgetAdvice`, `PassageQuote`, `GroundingConfidence`, `SourceDroppedSummary`, `IndexProgressSummary`, `ReviewAuditTrailItem`, `ReviewAuditTrailResponse`, and additive response fields.
- Modify `pubtator_link/services/review_context/packing.py`: build quote metadata and deterministic grounding confidence while converting rows to `ContextPassage`.
- Modify `pubtator_link/services/review_context/diagnostics.py`: create top-level recovery hints from existing diagnostics and query summaries.
- Modify `pubtator_link/services/review_context/batch_budgeting.py`: replace count-only dropped summaries with structured reason counts, suggested filters, and budget advice while preserving JSON compatibility.
- Modify `pubtator_link/services/review_context_service.py`: attach recovery to single/batch retrieval and add a thin `get_audit_trail()` service method.
- Modify `pubtator_link/services/source_preflight.py`: add post-index coverage expectation and confidence.
- Modify `pubtator_link/mcp/tools/review.py`: report wait-mode indexing progress and register `pubtator.get_review_audit_trail`.
- Modify `pubtator_link/mcp/service_adapters.py`: add `get_review_audit_trail_impl()`.
- Modify `pubtator_link/mcp/resources.py` and `pubtator_link/services/workflow_help.py`: expose the `llm_driver_contract`, new response fields, and audit-trail workflow.
- Optional REST parity if still desired after MCP implementation: modify `pubtator_link/api/routes/reviews.py`.
- Update docs: `docs/MCP_CONNECTION_GUIDE.md`, `docs/2026-05-02-pubtator-link-observability-implementation-guide.md`, `docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md`.
- Tests: `tests/unit/test_review_rerag_models.py`, `tests/unit/test_review_context_packing.py`, `tests/unit/test_review_context_diagnostics.py`, `tests/unit/test_review_context_batch_budgeting.py`, `tests/unit/test_review_context_service.py`, `tests/unit/test_source_preflight.py`, `tests/unit/mcp/test_mcp_service_adapters.py`, `tests/unit/mcp/test_mcp_facade.py`, `tests/unit/mcp/test_review_rerag_mcp.py`, `tests/unit/test_workflow_help.py`.

### Task 1: Add Additive Public Models

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Test: `tests/unit/test_review_rerag_models.py`

- [ ] **Step 1: Write failing model serialization tests**

Add to `tests/unit/test_review_rerag_models.py`:

```python
from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    GroundingConfidence,
    PassageQuote,
    RecoveryBudgetAdvice,
    RecoveryHint,
    RecoverySuggestedFilters,
    ReviewAuditTrailItem,
    ReviewAuditTrailResponse,
    SourceCoverageHint,
    SourceDroppedSummary,
)


def test_recovery_hint_serializes_bounded_filters_and_budget_advice() -> None:
    hint = RecoveryHint(
        reason="all_candidates_over_budget",
        message="Candidates matched but were excluded by response budget.",
        next_steps=["increase_budget", "filter_sections"],
        suggested_queries=["mefv colchicine"],
        suggested_filters=RecoverySuggestedFilters(
            sections=["abstract", "results"],
            pmids=["40234174"],
        ),
        budget_advice=RecoveryBudgetAdvice(
            increase_max_chars_to=18000,
            increase_max_response_chars_to=36000,
            lower_max_passages_per_query_to=4,
        ),
    )

    dumped = hint.model_dump(mode="json")

    assert dumped["reason"] == "all_candidates_over_budget"
    assert dumped["suggested_filters"]["sections"] == ["abstract", "results"]
    assert dumped["budget_advice"]["increase_max_chars_to"] == 18000


def test_context_passage_serializes_quote_and_grounding_confidence() -> None:
    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:1:abstract:0",
        section="abstract",
        text="MEFV variants respond to colchicine in this cohort.",
        quote=PassageQuote(
            text="MEFV variants respond to colchicine",
            returned_start_offset=0,
            returned_end_offset=35,
            passage_start_char=10,
            passage_end_char=45,
        ),
        confidence_for_grounding=GroundingConfidence(
            level="high",
            score=0.84,
            factors={"lexical_match": 0.9, "section_weight": 0.8},
            match_mode="strict_and_relaxed",
            explanation="High lexical match in an abstract passage.",
        ),
    )

    dumped = passage.model_dump(mode="json")

    assert dumped["quote"]["passage_start_char"] == 10
    assert dumped["confidence_for_grounding"]["level"] == "high"
    assert dumped["stable_citation_key"].startswith("c_")


def test_context_pack_accepts_structured_dropped_summary_and_recovery() -> None:
    pack = ContextPack(
        question="MEFV colchicine",
        passages=[],
        citation_map={},
        dropped_summary=SourceDroppedSummary(
            total_dropped=3,
            visible_dropped=3,
            by_reason={"char_budget_exceeded": 3},
            suggested_filters=RecoverySuggestedFilters(sections=["abstract"]),
        ),
        recovery=RecoveryHint(
            reason="all_candidates_over_budget",
            message="Candidates matched but were excluded by response budget.",
            next_steps=["increase_budget"],
        ),
    )

    dumped = pack.model_dump(mode="json")

    assert dumped["dropped_summary"]["by_reason"] == {"char_budget_exceeded": 3}
    assert dumped["recovery"]["next_steps"] == ["increase_budget"]


def test_source_coverage_hint_includes_after_index_expectation() -> None:
    hint = SourceCoverageHint(
        pmid="40234174",
        expected_coverage="unknown",
        expected_coverage_after_index="abstract_only",
        expected_coverage_confidence="moderate",
        coverage_resolution_stage="preflight_resolver_chain",
    )

    dumped = hint.model_dump(mode="json")

    assert dumped["expected_coverage_after_index"] == "abstract_only"
    assert dumped["expected_coverage_confidence"] == "moderate"


def test_review_audit_trail_response_serializes_copy_ready_block() -> None:
    response = ReviewAuditTrailResponse(
        review_id="rev-1",
        items=[
            ReviewAuditTrailItem(
                pmid="40234174",
                passage_id="PMID:40234174:abstract:0",
                stable_citation_key="c_abc123",
                section="abstract",
                quote="MEFV variants respond to colchicine.",
                char_count=35,
            )
        ],
        audit_block="- c_abc123 PMID 40234174 PMID:40234174:abstract:0 abstract: MEFV variants respond to colchicine.",
    )

    dumped = response.model_dump(mode="json")

    assert dumped["items"][0]["stable_citation_key"] == "c_abc123"
    assert dumped["audit_block"].startswith("- c_abc123 PMID 40234174")
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_models.py::test_recovery_hint_serializes_bounded_filters_and_budget_advice \
  tests/unit/test_review_rerag_models.py::test_context_passage_serializes_quote_and_grounding_confidence \
  tests/unit/test_review_rerag_models.py::test_context_pack_accepts_structured_dropped_summary_and_recovery \
  tests/unit/test_review_rerag_models.py::test_source_coverage_hint_includes_after_index_expectation \
  tests/unit/test_review_rerag_models.py::test_review_audit_trail_response_serializes_copy_ready_block -q
```

Expected: FAIL with missing model/import errors.

- [ ] **Step 3: Add model types and optional fields**

In `pubtator_link/models/review_rerag.py`, add literals near the existing coverage/result literals:

```python
GroundingConfidenceLevel = Literal["high", "moderate", "low", "unknown"]
CoverageExpectationConfidence = Literal["high", "moderate", "low", "unknown"]
CoverageResolutionStage = Literal[
    "preflight_resolver_chain",
    "indexer_resolver_chain",
    "not_resolved",
]
```

Add these models after `ContextDropReason`:

```python
class RecoverySuggestedFilters(BaseModel):
    """Bounded filters an LLM can apply on a follow-up retrieval call."""

    sections: list[str] = Field(default_factory=list)
    pmids: list[str] = Field(default_factory=list)


class RecoveryBudgetAdvice(BaseModel):
    """Bounded context-budget adjustments for recovery."""

    increase_max_chars_to: int | None = Field(default=None, ge=500)
    increase_max_response_chars_to: int | None = Field(default=None, ge=2000)
    lower_max_passages_per_query_to: int | None = Field(default=None, ge=1)


class RecoveryHint(BaseModel):
    """Top-level deterministic recovery guidance for LLM drivers."""

    reason: str
    message: str
    next_steps: list[str] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list)
    suggested_filters: RecoverySuggestedFilters | None = None
    budget_advice: RecoveryBudgetAdvice | None = None


class SourceDroppedSummary(BaseModel):
    """Structured accounting for passages dropped from a compact response."""

    total_dropped: int = Field(default=0, ge=0)
    visible_dropped: int = Field(default=0, ge=0)
    truncated_count: int = Field(default=0, ge=0)
    by_reason: dict[str, int] = Field(default_factory=dict)
    suggested_filters: RecoverySuggestedFilters | None = None
    budget_advice: RecoveryBudgetAdvice | None = None


class PassageQuote(BaseModel):
    """Citation-ready quote with returned-text and original-passage offsets."""

    text: str
    returned_start_offset: int = Field(ge=0)
    returned_end_offset: int = Field(ge=0)
    passage_start_char: int = Field(ge=0)
    passage_end_char: int = Field(ge=0)
    offset_basis: Literal["returned_text_and_original_passage"] = (
        "returned_text_and_original_passage"
    )


class GroundingConfidence(BaseModel):
    """Deterministic source-grounding confidence, not clinical certainty."""

    level: GroundingConfidenceLevel = "unknown"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    factors: dict[str, float] = Field(default_factory=dict)
    match_mode: Literal["strict", "relaxed", "strict_and_relaxed"] = "strict_and_relaxed"
    explanation: str
```

Extend `SourceCoverageHint`:

```python
expected_coverage_after_index: SourceCoverage = "unknown"
expected_coverage_confidence: CoverageExpectationConfidence = "unknown"
coverage_resolution_stage: CoverageResolutionStage = "not_resolved"
```

Extend `ContextPassage`:

```python
quote: PassageQuote | None = None
confidence_for_grounding: GroundingConfidence | None = None
```

Change `ContextPack.dropped_summary` type from `dict[str, int]` to:

```python
dropped_summary: SourceDroppedSummary | dict[str, int] = Field(default_factory=dict)
recovery: RecoveryHint | None = None
```

Extend `RetrieveReviewContextResponse` and `RetrieveReviewContextBatchResponse`:

```python
recovery: RecoveryHint | None = None
```

Add after `ReviewPassageLookupResponse`:

```python
class ReviewAuditTrailItem(BaseModel):
    """One copy-ready selected passage audit item."""

    pmid: str | None = None
    pmcid: str | None = None
    passage_id: str
    stable_citation_key: str
    section: str
    quote: str
    char_count: int = Field(ge=0)


class ReviewAuditTrailResponse(BaseModel):
    """Thin audit trail for selected passage IDs used in an answer."""

    success: bool = True
    review_id: str
    session_id: str | None = None
    items: list[ReviewAuditTrailItem] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    audit_block: str = ""
```

- [ ] **Step 4: Run model tests to verify green**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/models/review_rerag.py tests/unit/test_review_rerag_models.py
git commit -m "feat: add llm driver response models"
```

### Task 2: Add Quote And Grounding Confidence In Passage Packing

**Files:**
- Modify: `pubtator_link/services/review_context/packing.py`
- Test: `tests/unit/test_review_context_packing.py`

- [ ] **Step 1: Write failing quote and confidence tests**

Add to `tests/unit/test_review_context_packing.py`:

```python
def test_context_passage_quote_offsets_use_returned_and_original_text() -> None:
    row = _row("p1", rank=1.0, section="abstract", source_kind="pubtator_abstract")
    row.text = "A" * 50 + "MEFV variants respond to colchicine. Follow-up sentence." + "B" * 50

    passage = context_passage_from_row(
        index=1,
        row=row,
        request=RetrieveReviewContextRequest(
            question="MEFV colchicine",
            max_chars_per_passage=60,
        ),
    )

    assert passage.quote is not None
    assert "MEFV variants respond to colchicine" in passage.quote.text
    assert passage.quote.returned_start_offset >= 0
    assert passage.quote.returned_end_offset <= len(passage.text)
    assert passage.quote.passage_start_char == passage.start_char + passage.quote.returned_start_offset
    assert passage.quote.passage_end_char == passage.start_char + passage.quote.returned_end_offset


def test_context_passage_confidence_explains_low_truncated_unknown_source() -> None:
    row = _row("p1", rank=0.0, section="unknown", source_kind="unknown")
    row.text = "A" * 500

    passage = context_passage_from_row(
        index=1,
        row=row,
        request=RetrieveReviewContextRequest(
            question="MEFV",
            max_chars_per_passage=300,
        ),
    )

    assert passage.confidence_for_grounding is not None
    assert passage.confidence_for_grounding.level in {"low", "unknown"}
    assert "truncation_penalty" in passage.confidence_for_grounding.factors
```

- [ ] **Step 2: Run packing tests to verify red**

Run:

```bash
uv run pytest tests/unit/test_review_context_packing.py::test_context_passage_quote_offsets_use_returned_and_original_text \
  tests/unit/test_review_context_packing.py::test_context_passage_confidence_explains_low_truncated_unknown_source -q
```

Expected: FAIL because `quote` and `confidence_for_grounding` are not populated.

- [ ] **Step 3: Implement quote and confidence helpers**

In `pubtator_link/services/review_context/packing.py`, import:

```python
from pubtator_link.models.review_rerag import GroundingConfidence, PassageQuote
```

Add helpers near `excerpt_text()`:

```python
QUOTE_MAX_CHARS = 320


def passage_quote(
    returned_text: str,
    *,
    passage_start_char: int,
    query_tokens: Sequence[str],
) -> PassageQuote | None:
    if not returned_text:
        return None
    lowered = returned_text.lower()
    match_index = -1
    for token in query_tokens:
        match_index = lowered.find(token.lower())
        if match_index >= 0:
            break
    if match_index < 0:
        match_index = 0
    sentence_start = returned_text.rfind(".", 0, match_index) + 1
    sentence_start = max(0, sentence_start)
    sentence_end = returned_text.find(".", match_index)
    if sentence_end < 0:
        sentence_end = min(len(returned_text), sentence_start + QUOTE_MAX_CHARS)
    else:
        sentence_end = min(len(returned_text), sentence_end + 1)
    if sentence_end - sentence_start > QUOTE_MAX_CHARS:
        sentence_end = sentence_start + QUOTE_MAX_CHARS
    quote_text = returned_text[sentence_start:sentence_end].strip()
    leading_trim = len(returned_text[sentence_start:sentence_end]) - len(
        returned_text[sentence_start:sentence_end].lstrip()
    )
    returned_start = sentence_start + leading_trim
    returned_end = returned_start + len(quote_text)
    return PassageQuote(
        text=quote_text,
        returned_start_offset=returned_start,
        returned_end_offset=returned_end,
        passage_start_char=passage_start_char + returned_start,
        passage_end_char=passage_start_char + returned_end,
    )


def grounding_confidence_from_row(
    row: ReviewPassageRow,
    *,
    truncated: bool,
    query_tokens: Sequence[str],
) -> GroundingConfidence:
    lexical_match = 0.0
    lowered = row.text.lower()
    if query_tokens:
        matched = sum(1 for token in query_tokens if token.lower() in lowered)
        lexical_match = matched / len(query_tokens)
    section_weight = 1.0 if row.section.lower() in {"abstract", "results", "discussion"} else 0.5
    coverage_weight = 1.0 if row.source_kind in {"pmc_bioc", "europe_pmc_jats"} else 0.7
    if row.source_kind == "pubtator_abstract":
        coverage_weight = 0.6
    if row.source_kind == "unknown":
        coverage_weight = 0.2
    entity_overlap = 1.0 if row.entity_ids else 0.0
    truncation_penalty = 0.15 if truncated else 0.0
    score = max(
        0.0,
        min(
            1.0,
            (lexical_match * 0.45)
            + (section_weight * 0.2)
            + (coverage_weight * 0.25)
            + (entity_overlap * 0.1)
            - truncation_penalty,
        ),
    )
    level = "unknown"
    if score >= 0.75:
        level = "high"
    elif score >= 0.45:
        level = "moderate"
    elif score > 0:
        level = "low"
    return GroundingConfidence(
        level=level,
        score=round(score, 3),
        factors={
            "lexical_match": round(lexical_match, 3),
            "section_weight": round(section_weight, 3),
            "coverage_weight": round(coverage_weight, 3),
            "entity_overlap": round(entity_overlap, 3),
            "truncation_penalty": round(truncation_penalty, 3),
        },
        match_mode="strict_and_relaxed",
        explanation=(
            f"{level.capitalize()} deterministic retrieval grounding based on lexical match, "
            f"section, source coverage, entity overlap, and truncation."
        ),
    )
```

Update `context_passage_from_row()`:

```python
tokens = query_tokens(request.question)
text, start_char, end_char, truncated = excerpt_text(
    row.text,
    query_tokens=tokens,
    max_chars=request.max_chars_per_passage,
    allow_truncated=request.allow_truncated_passages,
)
...
quote=passage_quote(text, passage_start_char=start_char, query_tokens=tokens),
confidence_for_grounding=grounding_confidence_from_row(
    row,
    truncated=truncated,
    query_tokens=tokens,
),
```

- [ ] **Step 4: Run packing tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_packing.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/review_context/packing.py tests/unit/test_review_context_packing.py
git commit -m "feat: add passage quote and grounding confidence"
```

### Task 3: Promote Retrieval Recovery And Smarter Dropped Summaries

**Files:**
- Modify: `pubtator_link/services/review_context/diagnostics.py`
- Modify: `pubtator_link/services/review_context/batch_budgeting.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_diagnostics.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing recovery helper tests**

Add to `tests/unit/test_review_context_diagnostics.py`:

```python
from pubtator_link.models.review_rerag import QueryDiagnosticsSummary
from pubtator_link.services.review_context.diagnostics import recovery_from_query_summary


def test_recovery_from_zero_result_query_summary_promotes_next_steps() -> None:
    summary = QueryDiagnosticsSummary(
        query="MEFV colchicine",
        query_tokens=["mefv", "colchicine"],
        candidate_count=0,
        selected_count=0,
        returned_count=0,
        dropped_count=0,
        zero_result_reason="no_candidate_matches",
        suggested_queries=["mefv"],
        next_steps=["shorten_query", "drop_filters"],
    )

    recovery = recovery_from_query_summary(summary)

    assert recovery is not None
    assert recovery.reason == "no_candidate_matches"
    assert recovery.suggested_queries == ["mefv"]
    assert recovery.next_steps == ["shorten_query", "drop_filters"]


def test_recovery_from_high_drop_query_summary_suggests_budget() -> None:
    summary = QueryDiagnosticsSummary(
        query="MEFV colchicine",
        query_tokens=["mefv", "colchicine"],
        candidate_count=20,
        selected_count=8,
        returned_count=2,
        dropped_count=8,
        top_sections=["abstract"],
        top_pmids=["40234174"],
        next_steps=["increase_budget", "narrow_query"],
    )

    recovery = recovery_from_query_summary(summary)

    assert recovery is not None
    assert recovery.reason == "high_drop_pressure"
    assert recovery.suggested_filters is not None
    assert recovery.suggested_filters.sections == ["abstract"]
    assert recovery.budget_advice is not None
```

- [ ] **Step 2: Run recovery tests to verify red**

Run:

```bash
uv run pytest tests/unit/test_review_context_diagnostics.py::test_recovery_from_zero_result_query_summary_promotes_next_steps \
  tests/unit/test_review_context_diagnostics.py::test_recovery_from_high_drop_query_summary_suggests_budget -q
```

Expected: FAIL because `recovery_from_query_summary` does not exist.

- [ ] **Step 3: Implement recovery helper**

In `pubtator_link/services/review_context/diagnostics.py`, import:

```python
from pubtator_link.models.review_rerag import (
    RecoveryBudgetAdvice,
    RecoveryHint,
    RecoverySuggestedFilters,
)
```

Add:

```python
def recovery_from_query_summary(summary: QueryDiagnosticsSummary) -> RecoveryHint | None:
    if summary.returned_count == 0 and summary.zero_result_reason is not None:
        return RecoveryHint(
            reason=summary.zero_result_reason,
            message=f"No passages returned for query: {summary.query}",
            next_steps=summary.next_steps,
            suggested_queries=summary.suggested_queries,
            suggested_filters=RecoverySuggestedFilters(
                sections=summary.top_sections[:3],
                pmids=summary.top_pmids[:5],
            ),
        )
    if summary.dropped_count >= max(3, summary.returned_count * 3):
        return RecoveryHint(
            reason="high_drop_pressure",
            message=f"Many candidate passages were dropped for query: {summary.query}",
            next_steps=summary.next_steps or ["increase_budget", "filter_sections"],
            suggested_queries=summary.suggested_queries,
            suggested_filters=RecoverySuggestedFilters(
                sections=summary.top_sections[:3],
                pmids=summary.top_pmids[:5],
            ),
            budget_advice=RecoveryBudgetAdvice(
                increase_max_chars_to=18000,
                increase_max_response_chars_to=36000,
                lower_max_passages_per_query_to=4,
            ),
        )
    return None
```

- [ ] **Step 4: Write failing dropped summary test**

Add to `tests/unit/test_review_context_batch_budgeting.py`:

```python
def test_merge_batch_context_structures_dropped_summary_with_filter_advice() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["MEFV colchicine"],
        max_total_passages=1,
        max_chars=200,
        max_response_chars=2000,
    )
    result = _response(
        "MEFV colchicine",
        [
            _passage("p1", pmid="40234174", section="abstract", text="A" * 100),
            _passage("p2", pmid="40234174", section="results", text="B" * 100),
            _passage("p3", pmid="26802180", section="discussion", text="C" * 100),
        ],
    )

    merged = merge_batch_context(
        request=request,
        query_results=[result],
        coverage_by_source={},
    )

    assert hasattr(merged.dropped_summary, "by_reason")
    assert merged.dropped_summary.by_reason["max_total_passages_exceeded"] >= 1
    assert merged.dropped_summary.suggested_filters is not None
    assert merged.dropped_summary.suggested_filters.sections
```

If helper names differ in the file, create local `_passage()` and `_response()` helpers using existing model constructors.

- [ ] **Step 5: Run dropped summary test to verify red**

Run:

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py::test_merge_batch_context_structures_dropped_summary_with_filter_advice -q
```

Expected: FAIL because `dropped_summary` is still a plain count dict.

- [ ] **Step 6: Implement structured dropped summary**

In `pubtator_link/services/review_context/batch_budgeting.py`, import:

```python
from collections import Counter
from pubtator_link.models.review_rerag import RecoveryBudgetAdvice, RecoverySuggestedFilters, SourceDroppedSummary
```

Change `MergedBatchContext.dropped_summary` annotation:

```python
dropped_summary: SourceDroppedSummary
```

Add near the bottom:

```python
def build_dropped_summary(
    *,
    dropped: list[ContextDropReason],
    visible_dropped: list[ContextDropReason],
    request: RetrieveReviewContextBatchRequest,
) -> SourceDroppedSummary:
    by_reason = dict(Counter(item.reason for item in dropped))
    section_counts = Counter(item.section for item in dropped if item.section)
    pmid_counts = Counter(item.pmid for item in dropped if item.pmid)
    budget_reasons = {
        "char_budget_exceeded",
        "response_char_budget_exceeded",
        "passage_over_max_chars_per_passage",
    }
    budget_advice = None
    if budget_reasons.intersection(by_reason):
        budget_advice = RecoveryBudgetAdvice(
            increase_max_chars_to=min(50000, max(request.max_chars + 2000, int(request.max_chars * 1.5))),
            increase_max_response_chars_to=min(
                100000,
                max(request.max_response_chars + 4000, int(request.max_response_chars * 1.5)),
            ),
            lower_max_passages_per_query_to=max(1, request.max_passages_per_query // 2),
        )
    return SourceDroppedSummary(
        total_dropped=len(dropped),
        visible_dropped=len(visible_dropped),
        truncated_count=max(0, len(dropped) - len(visible_dropped)),
        by_reason=by_reason,
        suggested_filters=RecoverySuggestedFilters(
            sections=[section for section, _count in section_counts.most_common(3)],
            pmids=[pmid for pmid, _count in pmid_counts.most_common(5)],
        ),
        budget_advice=budget_advice,
    )
```

Replace the existing `dropped_summary = {"truncated_count": ...}` block with:

```python
dropped_summary = build_dropped_summary(
    dropped=dropped,
    visible_dropped=visible_dropped,
    request=request,
)
```

- [ ] **Step 7: Attach recovery in service responses**

In `pubtator_link/services/review_context_service.py`, import:

```python
from pubtator_link.services.review_context.diagnostics import (
    build_diagnostics,
    query_summary,
    recovery_from_query_summary,
)
```

For single retrieval, after diagnostics/preparation values are computed:

```python
single_summary = query_summary(
    query=request.question,
    result=response_without_recovery,
    returned_count=len(passages),
    dropped_count=len(dropped),
)
recovery = recovery_from_query_summary(single_summary)
```

If assembling `response_without_recovery` is awkward, build the response in a local variable and then return `response.model_copy(update={"recovery": recovery, "context_pack": response.context_pack.model_copy(update={"recovery": recovery})})`.

For batch retrieval, compute:

```python
recovery = next(
    (hint for hint in (recovery_from_query_summary(summary) for summary in merged.query_summaries) if hint is not None),
    None,
)
```

Set both response `recovery=recovery` and merged `ContextPack(recovery=recovery, dropped_summary=merged.dropped_summary)`.

- [ ] **Step 8: Run focused retrieval tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_diagnostics.py tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/services/review_context/diagnostics.py pubtator_link/services/review_context/batch_budgeting.py pubtator_link/services/review_context_service.py tests/unit/test_review_context_diagnostics.py tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py
git commit -m "feat: promote review retrieval recovery hints"
```

### Task 4: Add Post-Index Coverage Expectation To Preflight

**Files:**
- Modify: `pubtator_link/services/source_preflight.py`
- Test: `tests/unit/test_source_preflight.py`

- [ ] **Step 1: Write failing preflight expectation tests**

Add to `tests/unit/test_source_preflight.py`:

```python
@pytest.mark.asyncio
async def test_preflight_sets_after_index_expectation_for_abstract_fallback() -> None:
    async def convert(_pmid: str) -> dict[str, str | None]:
        return {}

    async def abstract_available(_pmid: str) -> bool:
        return True

    service = SourcePreflightService(
        id_converter=convert,
        pubtator_abstract_available=abstract_available,
    )

    [hint] = await service.preflight_pmids(["40234174"])

    assert hint.expected_coverage == "abstract_only"
    assert hint.expected_coverage_after_index == "abstract_only"
    assert hint.expected_coverage_confidence == "moderate"
    assert hint.coverage_resolution_stage == "preflight_resolver_chain"


@pytest.mark.asyncio
async def test_preflight_marks_unknown_after_index_when_no_resolver_succeeds() -> None:
    service = SourcePreflightService()

    [hint] = await service.preflight_pmids(["40234174"])

    assert hint.expected_coverage == "unknown"
    assert hint.expected_coverage_after_index == "unknown"
    assert hint.expected_coverage_confidence == "unknown"
    assert hint.coverage_resolution_stage == "not_resolved"
```

- [ ] **Step 2: Run preflight tests to verify red**

Run:

```bash
uv run pytest tests/unit/test_source_preflight.py::test_preflight_sets_after_index_expectation_for_abstract_fallback \
  tests/unit/test_source_preflight.py::test_preflight_marks_unknown_after_index_when_no_resolver_succeeds -q
```

Expected: FAIL because new fields are not populated.

- [ ] **Step 3: Populate expectation fields**

In `pubtator_link/services/source_preflight.py`, update successful full-text returns:

```python
expected_coverage_after_index="full_text",
expected_coverage_confidence="high",
coverage_resolution_stage="preflight_resolver_chain",
```

Update abstract fallback return:

```python
expected_coverage_after_index="abstract_only",
expected_coverage_confidence="moderate",
coverage_resolution_stage="preflight_resolver_chain",
```

Update timeout returns:

```python
expected_coverage_after_index="unknown",
expected_coverage_confidence="unknown",
coverage_resolution_stage="not_resolved",
```

Update final no-coverage return:

```python
expected_coverage_after_index="unknown",
expected_coverage_confidence="unknown",
coverage_resolution_stage="not_resolved",
```

When Europe PMC is configured and succeeds, use the same high-confidence full-text fields.

- [ ] **Step 4: Run source preflight tests**

Run:

```bash
uv run pytest tests/unit/test_source_preflight.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/source_preflight.py tests/unit/test_source_preflight.py
git commit -m "feat: expose post-index preflight expectation"
```

### Task 5: Add Thin Review Audit Trail Service And MCP Tool

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing service test**

Add to `tests/unit/test_review_context_service.py`:

```python
@pytest.mark.asyncio
async def test_get_audit_trail_returns_copy_ready_items() -> None:
    repository = FakeReviewContextRepository()
    repository.passages_by_id = {
        "PMID:40234174:abstract:0": ReviewPassageRow(
            passage_id="PMID:40234174:abstract:0",
            review_id="rev-1",
            source_id="src-1",
            source_kind="pubtator_abstract",
            pmid="40234174",
            pmcid=None,
            doi=None,
            url=None,
            section="abstract",
            heading_path=None,
            page=None,
            text="MEFV variants respond to colchicine in familial Mediterranean fever.",
            entity_ids=[],
            relation_types=[],
            screening_status="candidate",
            source_metadata={},
        )
    }
    service = ReviewContextService(repository)

    response = await service.get_audit_trail(
        review_id="rev-1",
        passage_ids=["PMID:40234174:abstract:0", "missing"],
        max_chars_per_passage=500,
    )

    assert response.items[0].pmid == "40234174"
    assert response.items[0].stable_citation_key.startswith("c_")
    assert response.not_found == ["missing"]
    assert "PMID:40234174:abstract:0" in response.audit_block
```

If the fake repository uses a different storage shape, add only the minimal attributes needed by its existing `get_passages_by_id()` implementation.

- [ ] **Step 2: Run service test to verify red**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py::test_get_audit_trail_returns_copy_ready_items -q
```

Expected: FAIL because `ReviewContextService.get_audit_trail` does not exist.

- [ ] **Step 3: Implement service method**

In `pubtator_link/services/review_context_service.py`, import:

```python
from pubtator_link.models.review_rerag import ReviewAuditTrailItem, ReviewAuditTrailResponse
```

Add method near `get_passages_by_id()`:

```python
async def get_audit_trail(
    self,
    *,
    review_id: str,
    passage_ids: list[str],
    session_id: str | None = None,
    max_chars_per_passage: int = 500,
) -> ReviewAuditTrailResponse:
    await self._ensure_session_exists(review_id, session_id)
    lookup = await self.get_passages_by_id(
        review_id=review_id,
        passage_ids=passage_ids,
        session_id=session_id,
        max_chars_per_passage=max_chars_per_passage,
    )
    items: list[ReviewAuditTrailItem] = []
    lines: list[str] = []
    for passage in lookup.passages:
        quote = passage.quote.text if passage.quote is not None else passage.text[:max_chars_per_passage]
        stable_key = passage.stable_citation_key or stable_citation_key_for_passage(passage.passage_id)
        item = ReviewAuditTrailItem(
            pmid=passage.pmid,
            pmcid=passage.pmcid,
            passage_id=passage.passage_id,
            stable_citation_key=stable_key,
            section=passage.section,
            quote=quote,
            char_count=len(quote),
        )
        items.append(item)
        pmid_text = f"PMID {passage.pmid}" if passage.pmid else "PMID unavailable"
        lines.append(f"- {stable_key} {pmid_text} {passage.passage_id} {passage.section}: {quote}")
    return ReviewAuditTrailResponse(
        review_id=review_id,
        session_id=session_id,
        items=items,
        not_found=lookup.not_found,
        audit_block="\n".join(lines),
    )
```

Also import `stable_citation_key_for_passage` from the model module if not already imported.

- [ ] **Step 4: Write failing MCP adapter/facade tests**

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_get_review_audit_trail_adapter_calls_service() -> None:
    from pubtator_link.mcp.service_adapters import get_review_audit_trail_impl

    class Service:
        async def get_audit_trail(self, **kwargs):
            assert kwargs["review_id"] == "rev-1"
            assert kwargs["passage_ids"] == ["p1"]
            return ReviewAuditTrailResponse(
                review_id="rev-1",
                items=[
                    ReviewAuditTrailItem(
                        passage_id="p1",
                        stable_citation_key="c_1",
                        section="abstract",
                        quote="Evidence text.",
                        char_count=14,
                    )
                ],
                audit_block="- c_1 PMID unavailable p1 abstract: Evidence text.",
            )

    result = await get_review_audit_trail_impl(
        service=Service(),
        review_id="rev-1",
        passage_ids=["p1"],
    )

    assert result["success"] is True
    assert result["items"][0]["stable_citation_key"] == "c_1"
```

Update `tests/unit/mcp/test_mcp_facade.py`:

```python
EXPECTED_PUBLIC_TOOL_NAMES.add("pubtator.get_review_audit_trail")
```

Add `"pubtator.get_review_audit_trail": ("review_id", "passage_ids")` to `required_properties`.

Add to output schema expected dict:

```python
"pubtator.get_review_audit_trail": {"success", "review_id", "items", "audit_block"},
```

- [ ] **Step 5: Run MCP tests to verify red**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_get_review_audit_trail_adapter_calls_service \
  tests/unit/mcp/test_mcp_facade.py::test_public_mcp_tools_use_flat_arguments_consistently \
  tests/unit/mcp/test_mcp_facade.py::test_high_use_mcp_tools_expose_specific_output_schemas -q
```

Expected: FAIL because adapter/tool are not registered.

- [ ] **Step 6: Implement adapter and tool**

In `pubtator_link/mcp/service_adapters.py`, import `ReviewAuditTrailResponse` and add:

```python
async def get_review_audit_trail_impl(
    *,
    service: ReviewContextService,
    review_id: str,
    passage_ids: list[str],
    session_id: str | None = None,
    max_chars_per_passage: int = 500,
) -> dict[str, Any]:
    response = await service.get_audit_trail(
        review_id=review_id,
        passage_ids=passage_ids,
        session_id=session_id,
        max_chars_per_passage=max_chars_per_passage,
    )
    return response.model_dump(mode="json")
```

In `pubtator_link/mcp/tools/review.py`, import the adapter and response model, then register after `get_review_passages_by_id`:

```python
@mcp.tool(
    name="pubtator.get_review_audit_trail",
    title="Get Review Audit Trail",
    output_schema=ReviewAuditTrailResponse.model_json_schema(),
    annotations=READ_ONLY_OPEN_WORLD,
)
async def get_review_audit_trail(
    review_id: str,
    passage_ids: list[str],
    session_id: str | None = None,
    max_chars_per_passage: int = 500,
) -> dict[str, Any]:
    """Use this to return a copy-ready audit block for selected prepared review passage IDs without calling upstream APIs."""

    async def call() -> dict[str, Any]:
        service = await get_review_context_service()
        return await get_review_audit_trail_impl(
            service=service,
            review_id=review_id,
            passage_ids=passage_ids,
            session_id=session_id,
            max_chars_per_passage=max_chars_per_passage,
        )

    return await run_mcp_tool("pubtator.get_review_audit_trail", call)
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/services/review_context_service.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add selected passage audit trail tool"
```

### Task 6: Add Wait-Mode MCP Progress Reporting

**Files:**
- Modify: `pubtator_link/mcp/tools/review.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Write failing progress test**

Add to `tests/unit/mcp/test_review_rerag_mcp.py`:

```python
@pytest.mark.asyncio
async def test_index_review_evidence_reports_progress_when_waiting(monkeypatch) -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    progress_calls: list[tuple[float, float | None]] = []

    class FakeContext:
        async def report_progress(self, progress: float, total: float | None = None) -> None:
            progress_calls.append((progress, total))

        async def warning(self, _message: str) -> None:
            return None

    async def fake_impl(**_kwargs):
        return {
            "success": True,
            "review_id": "rev-1",
            "queued": 1,
            "already_prepared": 0,
            "preparation_status": {
                "queued": 0,
                "running": 0,
                "complete": 1,
                "partial": 0,
                "failed": 0,
            },
            "waited_ms": 10,
            "timed_out": False,
        }

    monkeypatch.setattr("pubtator_link.mcp.tools.review.index_review_evidence_impl", fake_impl)

    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.index_review_evidence"]
    await tool.fn(
        review_id="rev-1",
        pmids=["40234174"],
        wait_until_ready=True,
        ctx=FakeContext(),
    )

    assert progress_calls[0] == (0, 100)
    assert progress_calls[-1] == (100, 100)
```

- [ ] **Step 2: Run progress test to verify red**

Run:

```bash
uv run pytest tests/unit/mcp/test_review_rerag_mcp.py::test_index_review_evidence_reports_progress_when_waiting -q
```

Expected: FAIL because no progress calls are emitted.

- [ ] **Step 3: Implement bounded progress calls**

In `pubtator_link/mcp/tools/review.py`, add helper:

```python
async def _report_index_progress(
    ctx: Context | None,
    *,
    progress: float,
    total: float = 100,
) -> None:
    if ctx is not None:
        await ctx.report_progress(progress=progress, total=total)
```

In `index_review_evidence.call()`:

```python
if wait_until_ready:
    await _report_index_progress(ctx, progress=0)
result = await index_review_evidence_impl(...)
if wait_until_ready:
    status = result.get("preparation_status", {})
    complete = int(status.get("complete", 0)) + int(status.get("partial", 0))
    total = max(1, int(status.get("queued", 0)) + int(status.get("running", 0)) + complete + int(status.get("failed", 0)))
    progress = 100 if result.get("timed_out") is False else min(95, (complete / total) * 100)
    await _report_index_progress(ctx, progress=progress)
```

Keep this best-effort and response-compatible. Do not add sleeps or new polling loops inside the MCP tool.

- [ ] **Step 4: Run focused MCP progress test**

Run:

```bash
uv run pytest tests/unit/mcp/test_review_rerag_mcp.py::test_index_review_evidence_reports_progress_when_waiting -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/tools/review.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: report wait-mode index progress"
```

### Task 7: Add LLM Driver Contract To Capabilities And Workflow Help

**Files:**
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/test_workflow_help.py`

- [ ] **Step 1: Write failing capabilities test**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_capabilities_expose_llm_driver_contract_for_core_workflow() -> None:
    from pubtator_link.mcp.resources import get_capabilities_resource

    contract = get_capabilities_resource()["llm_driver_contract"]

    assert contract["version"] == "2026-05-02"
    assert contract["discovery_policy"]["strategy"] == "progressive_discovery"
    assert "pubtator.retrieve_review_context_batch" in contract["core_workflow_tools"]
    assert "pubtator.get_review_audit_trail" in contract["core_workflow_tools"]
    assert "schemas" in contract["detail_levels"]
    assert "pubtator.index_review_evidence" in contract["schema_bundle"]
    assert "recovery" in contract["response_contracts"]
```

- [ ] **Step 2: Write failing workflow help test**

Add to `tests/unit/test_workflow_help.py`:

```python
def test_workflow_help_mentions_recovery_quote_confidence_and_audit_trail() -> None:
    help_text = workflow_help_text()

    assert "recovery" in help_text
    assert "quote" in help_text
    assert "confidence_for_grounding" in help_text
    assert "pubtator.get_review_audit_trail" in help_text
```

- [ ] **Step 3: Run docs-surface tests to verify red**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py::test_capabilities_expose_llm_driver_contract_for_core_workflow \
  tests/unit/test_workflow_help.py::test_workflow_help_mentions_recovery_quote_confidence_and_audit_trail -q
```

Expected: FAIL because capabilities/workflow help do not include these fields.

- [ ] **Step 4: Add capabilities contract**

In `pubtator_link/mcp/resources.py`, add helper:

```python
def get_llm_driver_contract() -> dict[str, Any]:
    return {
        "version": "2026-05-02",
        "recommended_entrypoint": "pubtator.workflow_help",
        "discovery_policy": {
            "strategy": "progressive_discovery",
            "rationale": "Full tool schemas are large; inspect core workflow tools as needed.",
        },
        "core_workflow_tools": [
            "pubtator.search_biomedical_entities",
            "pubtator.search_literature",
            "pubtator.preflight_review_sources",
            "pubtator.index_review_evidence",
            "pubtator.inspect_review_index",
            "pubtator.retrieve_review_context_batch",
            "pubtator.retrieve_review_context",
            "pubtator.get_review_passages_by_id",
            "pubtator.get_review_audit_trail",
        ],
        "detail_levels": ["catalog", "schemas", "examples"],
        "schema_bundle": {
            "pubtator.index_review_evidence": {
                "input_schema": "tools/list.parameters.pubtator.index_review_evidence",
                "output_schema": "IndexReviewEvidenceResponse",
            },
            "pubtator.retrieve_review_context_batch": {
                "input_schema": "tools/list.parameters.pubtator.retrieve_review_context_batch",
                "output_schema": "RetrieveReviewContextBatchResponse",
            },
            "pubtator.get_review_audit_trail": {
                "input_schema": "tools/list.parameters.pubtator.get_review_audit_trail",
                "output_schema": "ReviewAuditTrailResponse",
            },
        },
        "response_contracts": {
            "recovery": "Top-level recovery hints appear on empty, degraded, or high-drop retrievals.",
            "quote": "Context passages include optional quote offsets for returned text and original passage text.",
            "confidence_for_grounding": "Deterministic retrieval confidence for source grounding, not clinical certainty.",
            "dropped_summary": "Structured dropped-passage reason counts plus bounded filter and budget advice.",
        },
    }
```

Add to `get_capabilities_resource()`:

```python
"llm_driver_contract": get_llm_driver_contract(),
```

Also add `"pubtator.get_review_audit_trail"` to `tools`, `tool_categories["retrieval"]`, `core_tools`, `sample_calls`, `output_cheatsheet`, and `review_rerag["tools"]`.

- [ ] **Step 5: Update workflow help**

In `pubtator_link/services/workflow_help.py`, add concise text to the review workflow steps or `_meta`:

```python
"After retrieval, prefer top-level recovery for empty/high-drop queries, use passages[].quote for short verbatim snippets, passages[].confidence_for_grounding for retrieval confidence, and pubtator.get_review_audit_trail for selected passage audit blocks."
```

Keep the wording research-use scoped and do not add clinical advice.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/mcp/resources.py pubtator_link/services/workflow_help.py tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py
git commit -m "docs: expose llm driver contract"
```

### Task 8: Update User-Facing Docs And Recommendation Status

**Files:**
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `docs/2026-05-02-pubtator-link-observability-implementation-guide.md`
- Modify: `docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md`

- [ ] **Step 1: Update MCP connection guide**

Add a short section to `docs/MCP_CONNECTION_GUIDE.md`:

```markdown
### LLM Driver Ergonomics

For review-grounded work, start with `pubtator.workflow_help` or
`pubtator.get_server_capabilities`. The capabilities payload includes
`llm_driver_contract`, which identifies the core workflow tools and the response
fields an LLM should inspect:

- `recovery` for empty, degraded, or high-drop retrievals,
- `merged_context_pack.passages[].quote` for bounded citation snippets,
- `merged_context_pack.passages[].confidence_for_grounding` for deterministic
  retrieval confidence,
- `merged_context_pack.dropped_summary` for reason counts and suggested filters,
- `pubtator.get_review_audit_trail` for copy-ready selected-passage audit blocks.
```

- [ ] **Step 2: Update observability guide**

Add a recommendation status table to `docs/2026-05-02-pubtator-link-observability-implementation-guide.md`:

```markdown
## LLM MCP Ergonomics Recommendation Status

| # | Recommendation | Status |
|---|---|---|
| 1 | Fix batch output schema | Implemented |
| 2 | Fix `prepare_mode` validation | Implemented with hidden compatibility shim |
| 3 | Reduce deferred-tool friction | Implemented as `llm_driver_contract`; client eager-loading remains host-controlled |
| 4 | Promote recovery fields | Implemented with top-level `recovery` |
| 5 | Add quote offsets | Implemented with passage `quote` |
| 6 | Add grounding confidence | Implemented with `confidence_for_grounding` |
| 7 | Progress notifications | Implemented for wait-mode indexing |
| 8 | Improve preflight coverage expectation | Implemented with `expected_coverage_after_index` |
| 9 | Smarter dropped summaries | Implemented with structured `dropped_summary` |
| 10 | Add audit trail helper | Implemented as `pubtator.get_review_audit_trail` |
```

- [ ] **Step 3: Update parallel/concurrency analysis**

Add a concise note to `docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md`:

```markdown
### Batch Retrieval Recovery

Batch retrieval is the preferred multi-question path. Compact batch responses
can omit empty `results` while remaining schema-valid. When retrieval is empty or
over budget, drivers should inspect top-level `recovery` first, then
`query_summaries[]` and `merged_context_pack.dropped_summary` for bounded
follow-up filters.
```

- [ ] **Step 4: Run markdown sanity checks**

Run:

```bash
rg -n "LLM Driver Ergonomics|Recommendation Status|Batch Retrieval Recovery" docs/MCP_CONNECTION_GUIDE.md docs/2026-05-02-pubtator-link-observability-implementation-guide.md docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md
```

Expected: output shows all three new sections.

- [ ] **Step 5: Commit**

```bash
git add docs/MCP_CONNECTION_GUIDE.md docs/2026-05-02-pubtator-link-observability-implementation-guide.md docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md
git commit -m "docs: document llm mcp ergonomics status"
```

### Task 9: Final Verification And Docker Smoke

**Files:**
- No source changes expected.

- [ ] **Step 1: Run focused review/MCP test set**

Run:

```bash
uv run pytest \
  tests/unit/test_review_rerag_models.py \
  tests/unit/test_review_context_packing.py \
  tests/unit/test_review_context_diagnostics.py \
  tests/unit/test_review_context_batch_budgeting.py \
  tests/unit/test_review_context_service.py \
  tests/unit/test_source_preflight.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/mcp/test_mcp_facade.py \
  tests/unit/mcp/test_review_rerag_mcp.py \
  tests/unit/test_workflow_help.py -q
```

Expected: PASS.

- [ ] **Step 2: Run format**

Run:

```bash
make format
```

Expected: command exits 0.

- [ ] **Step 3: Run lint**

Run:

```bash
make lint
```

Expected: command exits 0.

- [ ] **Step 4: Run typecheck**

Run:

```bash
make typecheck
```

Expected: command exits 0.

- [ ] **Step 5: Run full local CI**

Run:

```bash
make ci-local
```

Expected: command exits 0.

- [ ] **Step 6: Rebuild and restart Docker**

Run:

```bash
make docker-build
make docker-down
make docker-up
```

Expected: all commands exit 0 and services start.

- [ ] **Step 7: Verify readiness and metrics on localhost:8011**

Run:

```bash
curl -fsS http://localhost:8011/ready
curl -fsS http://localhost:8011/metrics | rg "mcp_tool_calls_total|mcp_tool_latency_seconds"
```

Expected: `/ready` returns JSON with readiness true or explicitly healthy status, and `/metrics` contains both MCP metric names.

- [ ] **Step 8: Verify MCP schema surface in running container**

Run an MCP schema inspection command using the existing project harness if available. If no harness exists, run:

```bash
uv run python - <<'PY'
from pubtator_link.mcp.facade import create_pubtator_mcp

mcp = create_pubtator_mcp()
tools = mcp._tool_manager._tools
assert "pubtator.get_review_audit_trail" in tools
batch_required = tools["pubtator.retrieve_review_context_batch"].output_schema.get("required", [])
assert "results" not in batch_required
assert "prepare_mode" not in tools["pubtator.index_review_evidence"].parameters["properties"]
capabilities = mcp._resource_manager._resources["pubtator://capabilities"].fn()
assert "llm_driver_contract" in capabilities
print("mcp schema smoke ok")
PY
```

Expected: prints `mcp schema smoke ok`.

- [ ] **Step 9: Commit any formatter/doc changes**

If `make format` changed files:

```bash
git status --short
git add <changed files>
git commit -m "style: format llm mcp ergonomics changes"
```

If no files changed, do not create an empty commit.

- [ ] **Step 10: Ensure clean git status**

Run:

```bash
git status --short
```

Expected: no output.
