# MCP Ground Question And Guideline Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source-aware guideline boosting, `pubtator.ground_question`, and auto response budgeting for the high-priority MCP grounding workflow.

**Architecture:** Keep search ranking in `services/search_shaping.py`, budget resolution in `services/review_context/budgets.py`, and MCP orchestration in `mcp/service_adapters.py` plus `mcp/tools/review.py`. The new composite tool reuses the existing search, index, and batch retrieval paths instead of creating a parallel review pipeline.

**Tech Stack:** Python 3.11, FastMCP, Pydantic v2, pytest, Ruff, mypy, existing Makefile targets.

---

## Working Rules

- Start from an isolated worktree/branch before implementation. Do not implement on `main` or `master`.
- Do not touch or commit anything under `benchmarks/`.
- Do not revert unrelated local changes.
- Keep cleanup limited to the files named in this plan.
- Use TDD: write each failing test first, run it, implement the minimum code, rerun it.
- Prefer focused pytest commands for red/green loops, then run Makefile verification targets before completion.

## Files

- Modify: `pubtator_link/services/search_shaping.py`
  - Add landmark/source-recommendation ranking signals and reasons.
- Modify: `tests/unit/test_search_shaping.py`
  - Cover source recommendations outranking adherence studies.
- Create: `pubtator_link/services/review_context/budgets.py`
  - Resolve `verbosity` and `max_response_chars="auto"` to bounded integer budgets.
- Create: `tests/unit/test_review_context_budgets.py`
  - Cover budget mapping, explicit integer override, and validation.
- Modify: `pubtator_link/mcp/input_normalization.py`
  - Preserve `"auto"` for `max_response_chars` during batch argument normalization.
- Modify: `tests/unit/mcp/test_mcp_input_normalization.py`
  - Cover `"auto"` normalization.
- Modify: `pubtator_link/mcp/service_adapters.py`
  - Resolve batch budgets before `RetrieveReviewContextBatchRequest`.
  - Add `ground_question_impl`.
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
  - Cover batch auto resolution and composite workflow call order.
- Modify: `pubtator_link/models/review_rerag.py`
  - Add `ReviewResponseVerbosity`, `MaxResponseChars`, and `GroundQuestionResponse`.
- Modify: `pubtator_link/mcp/tools/review.py`
  - Expose `verbosity` and `max_response_chars="auto"` on batch retrieval.
  - Register `pubtator.ground_question`.
- Modify: `tests/unit/mcp/test_mcp_facade.py`
  - Add the new tool to expected public tools and schema assertions.
- Modify: `pubtator_link/mcp/resources.py`
  - Add `pubtator.ground_question` to capability/workflow guidance.
- Modify: `pubtator_link/mcp/facade.py`
  - Prefer `ground_question` in server instructions while keeping explicit chain guidance.
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
  - Document the one-call path and auto budgeting.

## Task 0: Create Implementation Worktree

**Files:**
- No source files modified.

- [ ] **Step 1: Confirm current branch and dirty state**

Run:

```bash
git status --short --branch
```

Expected: branch and dirty files are visible. Do not clean or revert unrelated files.

- [ ] **Step 2: Create an isolated worktree**

Run:

```bash
git worktree add ../pubtator-link-ground-question -b codex/mcp-ground-question-guideline-budget
cd ../pubtator-link-ground-question
```

Expected: a new worktree on branch `codex/mcp-ground-question-guideline-budget`.

- [ ] **Step 3: Install dependencies if the worktree needs them**

Run:

```bash
make install
```

Expected: `uv sync --group dev` completes successfully.

## Task 1: Boost Source Guideline Recommendations

**Files:**
- Modify: `tests/unit/test_search_shaping.py`
- Modify: `pubtator_link/services/search_shaping.py`

- [ ] **Step 1: Write the failing ranking test**

Append this test to `tests/unit/test_search_shaping.py` near the existing guideline boost tests:

```python
def test_guideline_boost_prioritizes_source_recommendations_over_adherence_studies() -> None:
    from pubtator_link.services.search_shaping import selected_search_items

    items = [
        {
            "pmid": "adh1",
            "title": "Guideline adherence after EULAR recommendations in familial Mediterranean fever",
            "abstract": (
                "A cohort study measured adherence to EULAR recommendations and "
                "quality indicators after guideline publication."
            ),
            "publication_types": ["Journal Article"],
        },
        {
            "pmid": "27422211",
            "title": (
                "EULAR recommendations for the management of familial Mediterranean fever"
            ),
            "abstract": (
                "These evidence based recommendations were developed by EULAR for "
                "the management of familial Mediterranean fever."
            ),
            "publication_types": ["Practice Guideline"],
        },
        {
            "pmid": "adh2",
            "title": "Implementation of SHARE recommendations in autoinflammatory disease clinics",
            "abstract": (
                "This study evaluates implementation and adherence to SHARE guidance."
            ),
            "publication_types": ["Observational Study"],
        },
        {
            "pmid": "source-share",
            "title": (
                "Evidence-based recommendations for genetic diagnosis of familial "
                "Mediterranean fever from SHARE"
            ),
            "abstract": (
                "Hentgen and collaborators present SHARE recommendations for "
                "autoinflammatory diseases."
            ),
            "publication_types": ["Consensus Development Conference"],
        },
        {
            "pmid": "source-printo",
            "title": (
                "Eurofever/PRINTO recommendations for the management of "
                "autoinflammatory diseases"
            ),
            "abstract": (
                "The 2019 recommendations provide consensus guidance for clinical "
                "management and classification."
            ),
            "publication_types": ["Guideline"],
        },
    ]

    selected = selected_search_items(items, guideline_boost=True, limit=3)

    assert [item["pmid"] for item in selected] == [
        "27422211",
        "source-share",
        "source-printo",
    ]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py::test_guideline_boost_prioritizes_source_recommendations_over_adherence_studies -q
```

Expected: FAIL because the existing broad term scoring can rank adherence or implementation studies too highly.

- [ ] **Step 3: Implement source-guideline scoring**

In `pubtator_link/services/search_shaping.py`, replace the guideline constants and `_guideline_rank_features()` with this implementation:

```python
GUIDELINE_TERMS = ("recommendation", "guideline", "consensus", "eular", "pres", "share")
GUIDELINE_TYPES = (
    "guideline",
    "practice guideline",
    "consensus",
    "consensus development conference",
    "systematic review",
)
SOURCE_GUIDELINE_PMIDS = {
    "27422211": "ozen_2016_eular_fmf",
}
SOURCE_GUIDELINE_PATTERNS = (
    ("ozen_2016_eular_fmf", ("eular", "familial mediterranean fever", "recommendation")),
    ("hentgen_share", ("share", "recommendation", "autoinflammatory")),
    ("eurofever_printo_2019", ("eurofever", "printo", "recommendation")),
)
ADHERENCE_CONTEXT_TERMS = (
    "adherence",
    "implementation",
    "quality indicator",
    "quality indicators",
    "compliance",
)
SOURCE_RECOMMENDATION_TERMS = (
    "recommendations for",
    "evidence based recommendations",
    "evidence-based recommendations",
    "management of",
    "classification criteria",
    "clinical practice",
)
```

```python
def _guideline_rank_features(item: dict[str, Any]) -> dict[str, Any]:
    publication_types = [str(value).lower() for value in item.get("publication_types", [])]
    title = str(item.get("title") or "").lower()
    abstract = str(item.get("abstract") or "").lower()
    pmid = str(item.get("pmid") or "")
    searchable = f"{title} {abstract}"
    reasons: list[str] = []

    source_boost = 0
    known_source = SOURCE_GUIDELINE_PMIDS.get(pmid)
    if known_source is not None:
        source_boost += 12
        reasons.append(known_source)
    for reason, required_terms in SOURCE_GUIDELINE_PATTERNS:
        if all(term in searchable for term in required_terms):
            source_boost += 8
            reasons.append(reason)
    if any(term in title for term in SOURCE_RECOMMENDATION_TERMS):
        source_boost += 4
        reasons.append("source_recommendation_title")

    type_boost = 0
    for value in publication_types:
        for term in sorted(GUIDELINE_TYPES, key=len, reverse=True):
            if term in value:
                type_boost += 3
                reasons.append(term)
                break

    term_boost = 0
    for term in GUIDELINE_TERMS:
        if term in title or term in abstract:
            term_boost += 1
            reasons.append(term)

    adherence_penalty = 0
    if any(term in searchable for term in ADHERENCE_CONTEXT_TERMS):
        adherence_penalty = 3
        reasons.append("adherence_context_penalty")

    return {
        "guideline_boost": source_boost + type_boost + term_boost - adherence_penalty,
        "ranking_reasons": list(dict.fromkeys(reasons)),
    }
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py::test_guideline_boost_prioritizes_source_recommendations_over_adherence_studies -q
```

Expected: PASS.

- [ ] **Step 5: Run the search shaping unit tests**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/services/search_shaping.py tests/unit/test_search_shaping.py
git commit -m "feat: prioritize source guideline recommendations"
```

Expected: commit succeeds.

## Task 2: Add Auto Response Budget Resolution

**Files:**
- Create: `pubtator_link/services/review_context/budgets.py`
- Create: `tests/unit/test_review_context_budgets.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/input_normalization.py`
- Modify: `tests/unit/mcp/test_mcp_input_normalization.py`
- Modify: `pubtator_link/mcp/service_adapters.py`

- [ ] **Step 1: Write failing budget helper tests**

Create `tests/unit/test_review_context_budgets.py`:

```python
import pytest

from pubtator_link.services.review_context.budgets import resolve_max_response_chars


def test_resolve_max_response_chars_auto_uses_verbosity() -> None:
    assert resolve_max_response_chars("auto", verbosity="lean") == 12000
    assert resolve_max_response_chars("auto", verbosity="standard") == 24000
    assert resolve_max_response_chars("auto", verbosity="full") == 60000


def test_resolve_max_response_chars_integer_wins_over_verbosity() -> None:
    assert resolve_max_response_chars(36000, verbosity="lean") == 36000


def test_resolve_max_response_chars_rejects_out_of_range_integer() -> None:
    with pytest.raises(ValueError, match="between 2000 and 100000"):
        resolve_max_response_chars(1999, verbosity="standard")


def test_resolve_max_response_chars_rejects_invalid_auto_value() -> None:
    with pytest.raises(ValueError, match="max_response_chars"):
        resolve_max_response_chars("small", verbosity="standard")
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py -q
```

Expected: FAIL because `pubtator_link.services.review_context.budgets` does not exist.

- [ ] **Step 3: Implement the budget helper**

Create `pubtator_link/services/review_context/budgets.py`:

```python
from __future__ import annotations

from typing import Literal

ReviewResponseVerbosity = Literal["lean", "standard", "full"]
MaxResponseChars = int | Literal["auto"]

AUTO_RESPONSE_BUDGETS: dict[ReviewResponseVerbosity, int] = {
    "lean": 12000,
    "standard": 24000,
    "full": 60000,
}


def resolve_max_response_chars(
    max_response_chars: MaxResponseChars,
    *,
    verbosity: ReviewResponseVerbosity,
) -> int:
    if max_response_chars == "auto":
        return AUTO_RESPONSE_BUDGETS[verbosity]
    if not isinstance(max_response_chars, int):
        raise ValueError("max_response_chars must be an integer or 'auto'")
    if max_response_chars < 2000 or max_response_chars > 100000:
        raise ValueError("max_response_chars must be between 2000 and 100000")
    return max_response_chars
```

- [ ] **Step 4: Export shared type aliases from review models**

In `pubtator_link/models/review_rerag.py`, add these aliases near the existing review response mode aliases:

```python
ReviewResponseVerbosity = Literal["lean", "standard", "full"]
MaxResponseChars = int | Literal["auto"]
```

Keep `RetrieveReviewContextBatchRequest.max_response_chars` as `int`; adapters resolve `"auto"` before constructing the Pydantic request.

- [ ] **Step 5: Preserve auto in input normalization**

In `pubtator_link/mcp/input_normalization.py`, ensure `max_response_chars` is allowed to remain `"auto"` before model validation. Add this test to `tests/unit/mcp/test_mcp_input_normalization.py`:

```python
def test_retrieve_review_context_batch_normalization_preserves_auto_budget() -> None:
    from pubtator_link.mcp.input_normalization import normalize_retrieve_review_context_batch_args

    normalized, warnings = normalize_retrieve_review_context_batch_args(
        {
            "queries": ["colchicine fmf"],
            "max_response_chars": "auto",
        }
    )

    assert normalized["max_response_chars"] == "auto"
    assert warnings == []
```

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_input_normalization.py::test_retrieve_review_context_batch_normalization_preserves_auto_budget -q
```

Expected: FAIL if normalization coerces or rejects `"auto"`.

Update the normalization logic so the `max_response_chars` field accepts `"auto"` exactly and still validates numeric aliases as before.

- [ ] **Step 6: Resolve auto in the batch MCP adapter**

Add this import in `pubtator_link/mcp/service_adapters.py`:

```python
from pubtator_link.services.review_context.budgets import resolve_max_response_chars
```

Update `retrieve_review_context_batch_impl()` signature:

```python
    max_response_chars: MaxResponseChars = "auto",
    verbosity: ReviewResponseVerbosity = "standard",
```

Add `verbosity` to the raw `args` dictionary and resolve the model request value:

```python
    resolved_max_response_chars = resolve_max_response_chars(
        normalized_args["max_response_chars"],
        verbosity=normalized_args.get("verbosity", "standard"),
    )
```

Use `resolved_max_response_chars` in `request_args["max_response_chars"]`.

- [ ] **Step 7: Write and run the adapter test**

Add this test to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_resolves_auto_budget() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class Service:
        request = None

        async def retrieve_context_batch(self, review_id, request):
            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(question="", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
            )

    service = Service()

    await retrieve_review_context_batch_impl(
        service=service,
        review_id="r1",
        queries=["MEFV"],
        max_response_chars="auto",
        verbosity="full",
    )

    assert service.request.max_response_chars == 60000
```

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py tests/unit/mcp/test_mcp_input_normalization.py::test_retrieve_review_context_batch_normalization_preserves_auto_budget tests/unit/mcp/test_mcp_service_adapters.py::test_retrieve_review_context_batch_adapter_resolves_auto_budget -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add pubtator_link/services/review_context/budgets.py tests/unit/test_review_context_budgets.py pubtator_link/models/review_rerag.py pubtator_link/mcp/input_normalization.py tests/unit/mcp/test_mcp_input_normalization.py pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: add auto review response budgets"
```

Expected: commit succeeds.

## Task 3: Add Ground Question Models And Adapter

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing composite adapter tests**

Add these tests to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_ground_question_impl_chains_search_index_and_retrieve() -> None:
    from pubtator_link.mcp.service_adapters import ground_question_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        IndexReviewEvidenceResponse,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class Client:
        async def search_publications(self, text, page, sort, filters, sections):
            return {
                "count": 2,
                "page_size": 20,
                "results": [
                    {
                        "pmid": "27422211",
                        "title": "EULAR recommendations for familial Mediterranean fever",
                        "abstract": "Recommendations for management.",
                        "publication_types": ["Practice Guideline"],
                    },
                    {
                        "pmid": "123",
                        "title": "Colchicine in FMF",
                        "abstract": "Treatment evidence.",
                        "publication_types": ["Journal Article"],
                    },
                ],
            }

    class Queue:
        repository = object()

    class IndexService:
        request = None

        async def index_review_evidence(self, review_id, request):
            self.request = request
            return IndexReviewEvidenceResponse(
                review_id=review_id,
                preparation_status=PreparationStatus(complete=2),
            )

    class ContextService:
        request = None

        async def retrieve_context_batch(self, review_id, request):
            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(
                    question=request.queries[0],
                    passages=[],
                    citation_map={},
                ),
                preparation_status=PreparationStatus(complete=2),
            )

    index_service = IndexService()
    context_service = ContextService()

    result = await ground_question_impl(
        client=Client(),
        queue=Queue(),
        context_service=context_service,
        review_indexing_service_factory=lambda queue: index_service,
        question="What is first line FMF treatment?",
        max_pmids=8,
        review_id="fmf-review",
        entity_ids=None,
        guideline_boost=True,
        wait_until_ready=True,
        timeout_ms=30000,
        verbosity="standard",
        max_response_chars="auto",
    )

    assert result["success"] is True
    assert result["review_id"] == "fmf-review"
    assert result["selected_pmids"] == ["27422211", "123"]
    assert index_service.request.pmids == ["27422211", "123"]
    assert index_service.request.wait_for_completion is True
    assert context_service.request.queries == ["What is first line FMF treatment?"]
    assert context_service.request.max_response_chars == 24000
    assert result["retrieval"]["merged_context_pack"]["question"] == "What is first line FMF treatment?"


@pytest.mark.asyncio
async def test_ground_question_impl_returns_partial_state_when_search_has_no_pmids() -> None:
    from pubtator_link.mcp.service_adapters import ground_question_impl

    class Client:
        async def search_publications(self, text, page, sort, filters, sections):
            return {"count": 0, "page_size": 20, "results": []}

    class Queue:
        repository = object()

    class ContextService:
        async def retrieve_context_batch(self, review_id, request):
            raise AssertionError("retrieval should not run without PMIDs")

    result = await ground_question_impl(
        client=Client(),
        queue=Queue(),
        context_service=ContextService(),
        question="no result topic",
    )

    assert result["success"] is True
    assert result["selected_pmids"] == []
    assert result["indexing"] is None
    assert result["retrieval"] is None
    assert result["ready_to_retrieve"] is False
    assert result["next_commands"][0]["tool"] == "pubtator.search_literature"
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_ground_question_impl_chains_search_index_and_retrieve tests/unit/mcp/test_mcp_service_adapters.py::test_ground_question_impl_returns_partial_state_when_search_has_no_pmids -q
```

Expected: FAIL because `ground_question_impl` does not exist.

- [ ] **Step 3: Add composite response model**

In `pubtator_link/models/review_rerag.py`, add this model near `ReviewQuickstartResponse`:

```python
class GroundQuestionResponse(BaseModel):
    """Composite response for one-call question grounding."""

    success: bool = True
    review_id: str
    question: str
    selected_pmids: list[str] = Field(default_factory=list)
    search: dict[str, Any] = Field(default_factory=dict)
    indexing: dict[str, Any] | None = None
    retrieval: dict[str, Any] | None = None
    preparation_status: PreparationStatus = Field(default_factory=PreparationStatus)
    ready_to_retrieve: bool = False
    next_commands: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement `ground_question_impl`**

In `pubtator_link/mcp/service_adapters.py`, import the model and helper types:

```python
from pubtator_link.models.review_rerag import (
    BudgetStrategy,
    GroundQuestionResponse,
    IndexReviewEvidenceRequest,
    InspectReviewIndexRequest,
    MaxResponseChars,
    McpReviewAuditBundleResponse,
    PrepareMode,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextRequest,
    ReviewAuditTrailResponse,
    ReviewBatchResponseMode,
    ReviewQuickstartResponse,
    ReviewResponseVerbosity,
    ReviewTableMode,
    SampleSectionPolicy,
    StageResearchSessionRequest,
    UpsertEvidenceCertaintyRequest,
)
```

Add this function near `review_quickstart_impl()`:

```python
async def ground_question_impl(
    *,
    client: PubTator3Client,
    queue: ReviewPreparationQueue,
    context_service: ReviewContextService,
    question: str,
    max_pmids: int = 8,
    review_id: str | None = None,
    entity_ids: list[str] | None = None,
    guideline_boost: bool = True,
    wait_until_ready: bool = True,
    timeout_ms: int = 30000,
    verbosity: ReviewResponseVerbosity = "standard",
    max_response_chars: MaxResponseChars = "auto",
    review_indexing_service_factory: Any = ReviewIndexingService,
) -> dict[str, Any]:
    normalized_question = question.strip()
    selected_review_id = review_id or _quickstart_review_id(normalized_question)
    search_result = await search_literature_impl(
        client=client,
        text=normalized_question,
        page=1,
        sort="score desc",
        publication_types=None,
        year_min=None,
        year_max=None,
        sections=None,
        response_mode="standard",
        include_citations="nlm",
        text_hl_format="plain",
        limit=max_pmids,
        entity_ids=entity_ids,
        guideline_boost=guideline_boost,
        coverage="none",
        preflight_service=None,
        metadata="basic",
        metadata_service=None,
    )
    results = search_result.get("results", [])
    selected_pmids = [
        str(item["pmid"])
        for item in results
        if isinstance(item, dict) and item.get("pmid")
    ]
    selected_pmids = list(dict.fromkeys(selected_pmids))[:max_pmids]
    if not selected_pmids:
        response = GroundQuestionResponse(
            review_id=selected_review_id,
            question=normalized_question,
            selected_pmids=[],
            search=search_result,
            ready_to_retrieve=False,
            next_commands=[
                {
                    "tool": "pubtator.search_literature",
                    "arguments": {
                        "text": normalized_question,
                        "guideline_boost": guideline_boost,
                        "limit": max_pmids,
                    },
                }
            ],
            warnings=["search returned no PMIDs to index"],
        )
        return response.model_dump(mode="json")

    indexing_service = review_indexing_service_factory(queue)
    index_response = await indexing_service.index_review_evidence(
        selected_review_id,
        IndexReviewEvidenceRequest(
            pmids=selected_pmids,
            wait_for_completion=wait_until_ready,
            wait_for_status="complete_or_partial" if wait_until_ready else None,
            timeout_ms=timeout_ms,
        ),
    )
    indexing = index_response.model_dump(mode="json")
    preparation_status = index_response.preparation_status
    ready_to_retrieve = preparation_status.complete > 0 or preparation_status.partial > 0
    retrieval: dict[str, Any] | None = None
    warnings: list[str] = []
    if ready_to_retrieve:
        resolved_budget = resolve_max_response_chars(max_response_chars, verbosity=verbosity)
        retrieval_response = await context_service.retrieve_context_batch(
            review_id=selected_review_id,
            request=RetrieveReviewContextBatchRequest(
                queries=[normalized_question],
                pmids=selected_pmids,
                response_mode="compact",
                max_response_chars=resolved_budget,
                budget_strategy="query_fair",
            ),
        )
        retrieval = retrieval_response.model_dump(mode="json")
    else:
        warnings.append("indexing completed without ready passages; inspect the review index")

    response = GroundQuestionResponse(
        review_id=selected_review_id,
        question=normalized_question,
        selected_pmids=selected_pmids,
        search=search_result,
        indexing=indexing,
        retrieval=retrieval,
        preparation_status=preparation_status,
        ready_to_retrieve=ready_to_retrieve,
        next_commands=[
            {
                "tool": "pubtator.inspect_review_index",
                "arguments": {"review_id": selected_review_id, "pmids": selected_pmids},
            },
            {
                "tool": "pubtator.retrieve_review_context_batch",
                "arguments": {
                    "review_id": selected_review_id,
                    "queries": [normalized_question],
                    "pmids": selected_pmids,
                    "max_response_chars": max_response_chars,
                    "verbosity": verbosity,
                },
            },
        ],
        warnings=warnings,
    )
    return response.model_dump(mode="json")
```

- [ ] **Step 5: Run adapter tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_ground_question_impl_chains_search_index_and_retrieve tests/unit/mcp/test_mcp_service_adapters.py::test_ground_question_impl_returns_partial_state_when_search_has_no_pmids -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: add ground question MCP adapter"
```

Expected: commit succeeds.

## Task 4: Register MCP Tool And Public Schemas

**Files:**
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`

- [ ] **Step 1: Write failing facade/schema tests**

In `tests/unit/mcp/test_mcp_facade.py`, add `"pubtator.ground_question"` to `EXPECTED_PUBLIC_TOOL_NAMES`.

Add these tests:

```python
def test_ground_question_schema_exposes_one_call_grounding_arguments() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.ground_question"]
    properties = tool.parameters["properties"]

    assert properties["max_pmids"]["default"] == 8
    assert properties["guideline_boost"]["default"] is True
    assert properties["wait_until_ready"]["default"] is True
    assert properties["verbosity"]["default"] == "standard"
    assert "auto" in _schema_enum_values(properties["max_response_chars"])


def test_retrieve_review_context_batch_schema_exposes_auto_budget_and_verbosity() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    properties = create_pubtator_mcp()._tool_manager._tools[
        "pubtator.retrieve_review_context_batch"
    ].parameters["properties"]

    assert properties["verbosity"]["default"] == "standard"
    assert "auto" in _schema_enum_values(properties["max_response_chars"])
```

Add `pubtator.ground_question` to the `expected` mapping in
`test_high_use_mcp_tools_expose_specific_output_schemas()`:

```python
        "pubtator.ground_question": {
            "success",
            "review_id",
            "selected_pmids",
            "retrieval",
        },
```

- [ ] **Step 2: Run schema tests and verify they fail**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py::test_inspection_managers_are_installed_by_compat_module tests/unit/mcp/test_mcp_facade.py::test_ground_question_schema_exposes_one_call_grounding_arguments tests/unit/mcp/test_mcp_facade.py::test_retrieve_review_context_batch_schema_exposes_auto_budget_and_verbosity tests/unit/mcp/test_mcp_facade.py::test_high_use_mcp_tools_expose_specific_output_schemas -q
```

Expected: FAIL because the new tool and schema fields are not registered yet.

- [ ] **Step 3: Register the MCP tool and batch schema fields**

In `pubtator_link/mcp/tools/review.py`, import the new adapter and model:

```python
    ground_question_impl,
```

```python
    GroundQuestionResponse,
    MaxResponseChars,
    ReviewResponseVerbosity,
```

Update `retrieve_review_context_batch()` signature:

```python
        max_response_chars: MaxResponseChars = "auto",
        verbosity: ReviewResponseVerbosity = "standard",
```

Pass `verbosity=verbosity` to `retrieve_review_context_batch_impl()`.

Register `ground_question` near `review_quickstart`:

```python
    @mcp.tool(
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
        timeout_ms: Annotated[int, Field(ge=0, le=120_000)] = 30000,
        verbosity: ReviewResponseVerbosity = "standard",
        max_response_chars: MaxResponseChars = "auto",
    ) -> dict[str, Any]:
        """Use this one-call entry point to ground a biomedical question by searching literature, indexing selected PMIDs, and retrieving compact review context."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            queue = await get_review_queue()
            context_service = await get_review_context_service()
            return await ground_question_impl(
                client=client,
                queue=queue,
                context_service=context_service,
                question=question,
                max_pmids=max_pmids,
                review_id=review_id,
                entity_ids=entity_ids,
                guideline_boost=guideline_boost,
                wait_until_ready=wait_until_ready,
                timeout_ms=timeout_ms,
                verbosity=verbosity,
                max_response_chars=max_response_chars,
            )

        return await run_mcp_tool("pubtator.ground_question", call)
```

- [ ] **Step 4: Update capabilities and docs**

In `pubtator_link/mcp/facade.py`, adjust the instructions sentence to mention the one-call path:

```python
"For grounded answers, prefer pubtator.ground_question when a one-call workflow is suitable; otherwise use search -> preflight -> index -> inspect -> retrieve. "
```

In `pubtator_link/mcp/resources.py`, add `pubtator.ground_question` to the review/grounding workflow capability list where `search_literature`, `index_review_evidence`, and `retrieve_review_context_batch` are already documented.

In `docs/MCP_CONNECTION_GUIDE.md`, add a short section:

```markdown
### One-call grounding

Use `pubtator.ground_question` when the caller wants the standard search,
index, and batch retrieval workflow in one tool call. It selects up to
`max_pmids` PMIDs, waits briefly for preparation by default, and returns the
same retrieval payload shape used by `pubtator.retrieve_review_context_batch`.
Use the explicit tools when you need manual corpus curation or staged review
session control.
```

- [ ] **Step 5: Run schema and docs-adjacent tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/integration/test_mcp_http_protocol.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/mcp/tools/review.py tests/unit/mcp/test_mcp_facade.py pubtator_link/mcp/facade.py pubtator_link/mcp/resources.py docs/MCP_CONNECTION_GUIDE.md
git commit -m "feat: expose ground question MCP tool"
```

Expected: commit succeeds.

## Task 5: Focused Verification

**Files:**
- No new implementation files unless a focused failure reveals a bug in a touched file.

- [ ] **Step 1: Run focused verification**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py tests/unit/test_review_context_budgets.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/integration/test_mcp_http_protocol.py -q
```

Expected: PASS.

- [ ] **Step 2: Run formatter and lint**

Run:

```bash
make format
make lint
```

Expected: both commands complete successfully. Commit formatting-only changes if Ruff rewrites files.

- [ ] **Step 3: Run type checking**

Run:

```bash
make typecheck-fast
```

Expected: PASS. If `dmypy` crashes, the Makefile target falls back according to the repo policy.

- [ ] **Step 4: Run full local CI**

Run:

```bash
make ci-local
```

Expected: PASS.

- [ ] **Step 5: Final commit if verification changed files**

Run:

```bash
git status --short
```

Expected: no unexpected changes. If formatting or docs verification changed only touched files, commit them:

```bash
git add pubtator_link/services/search_shaping.py pubtator_link/services/review_context/budgets.py pubtator_link/models/review_rerag.py pubtator_link/mcp/input_normalization.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/facade.py pubtator_link/mcp/resources.py tests/unit/test_search_shaping.py tests/unit/test_review_context_budgets.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py docs/MCP_CONNECTION_GUIDE.md
git commit -m "chore: verify ground question workflow"
```

Expected: commit only if there are staged touched-file changes.

## Review Checklist

- `guideline_boost=true` ranks source recommendations ahead of adherence and implementation studies.
- `pubtator.ground_question` appears in MCP tool listings and has a specific output schema.
- `retrieve_review_context_batch` accepts `max_response_chars="auto"` and `verbosity`.
- Explicit numeric `max_response_chars` values still work.
- No files under `benchmarks/` are staged or committed.
- Focused verification and `make ci-local` pass before claiming completion.

