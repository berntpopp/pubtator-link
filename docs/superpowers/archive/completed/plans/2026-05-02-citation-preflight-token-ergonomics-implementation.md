# Citation Preflight Token Ergonomics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make citation metadata, search preflight diagnostics, passage truncation, and MCP token ergonomics safer and easier for LLM consumers.

**Architecture:** Keep REST defaults backward compatible while changing MCP search defaults and shared response models. Add small deterministic helpers for preflight naming, high-drop guidance, per-PMID budget summaries, citation-key documentation, and canonical lowercase section taxonomy.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, MCP FastMCP, pytest, Ruff, mypy, uv, Makefile.

---

## File Structure

- Modify `pubtator_link/mcp/tools/literature.py` and `pubtator_link/mcp/service_adapters.py`: MCP `search_literature(metadata="basic")`.
- Modify `pubtator_link/models/responses.py` and `pubtator_link/services/search_shaping.py`: typed authors and preflight guess fields.
- Modify `pubtator_link/services/search_coverage.py` and `pubtator_link/services/source_preflight.py`: structured preflight failure diagnostics and non-informative hint omission.
- Modify `pubtator_link/models/review_rerag.py`, `pubtator_link/services/review_context/packing.py`, `pubtator_link/services/review_context/batch_budgeting.py`, and `pubtator_link/services/review_context/diagnostics.py`: tail previews, per-PMID batch floors, and high-drop guidance.
- Modify `pubtator_link/services/review_context_service.py`: inspect citation metadata using `PublicationMetadataService`.
- Modify `pubtator_link/mcp/resources.py`, `pubtator_link/mcp/metadata.py`, `pubtator_link/services/workflow_help.py`, and `docs/MCP_CONNECTION_GUIDE.md`: one global notice, schema policy, stable citation key semantics, relation discovery promotion, and section taxonomy.
- Test files: `tests/unit/test_search_shaping.py`, `tests/test_routes/test_search.py`, `tests/unit/test_source_preflight.py`, `tests/unit/test_review_context_service.py`, `tests/unit/test_review_context_batch_budgeting.py`, `tests/unit/test_review_context_packing.py`, `tests/unit/test_review_context_diagnostics.py`, `tests/unit/mcp/test_mcp_facade.py`, `tests/unit/test_workflow_help.py`.

### Task 1: MCP Search Metadata Default And Typed Authors

**Files:**
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/models/responses.py`
- Modify: `pubtator_link/services/search_shaping.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/test_search_shaping.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_mcp_search_literature_defaults_metadata_basic() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.search_literature"]

    assert tool.parameters["properties"]["metadata"]["default"] == "basic"


def test_search_result_authors_are_publication_author_shape() -> None:
    result = shaped_search_result(
        {"pmid": "1", "title": "T", "authors": [{"last_name": "Smith", "initials": "J"}]},
        metadata_by_pmid={},
    )

    assert result.authors[0].last_name == "Smith"
    assert result.model_dump()["authors"][0] == {"last_name": "Smith", "fore_name": None, "initials": "J"}
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/test_search_shaping.py -q`
Expected: FAIL because the MCP default is `none` and authors are `list[Any]`.

- [ ] **Step 3: Implement default and typing**

Change MCP tool and adapter default to:

```python
metadata: Literal["none", "basic", "full"] = "basic"
```

Change `SearchResult.authors` to `list[PublicationAuthor]` and normalize strings/dicts in `search_shaping.py` before model construction.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/test_search_shaping.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/tools/literature.py pubtator_link/mcp/service_adapters.py pubtator_link/models/responses.py pubtator_link/services/search_shaping.py tests/unit/mcp/test_mcp_facade.py tests/unit/test_search_shaping.py
git commit -m "feat: default MCP search to citation metadata"
```

### Task 2: Search Preflight Diagnostics And Guess Fields

**Files:**
- Modify: `pubtator_link/models/responses.py`
- Modify: `pubtator_link/services/search_coverage.py`
- Modify: `pubtator_link/services/source_preflight.py`
- Test: `tests/test_routes/test_search.py`
- Test: `tests/unit/test_source_preflight.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_search_preflight_failure_returns_structured_fields() -> None:
    response = SearchResponse(results=[], preflight_failure_reason="timeout")

    assert response.preflight_error_reason == "timeout"
    assert response.preflight_error_code == "coverage_preflight_timeout"


def test_unknown_noninformative_coverage_hint_is_omitted() -> None:
    result = SearchResult(pmid="1", title="T", coverage_hint={"expected_coverage": "unknown"})

    assert result.model_dump(exclude_none=True).get("coverage_hint") is None
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/test_routes/test_search.py tests/unit/test_source_preflight.py -q`
Expected: FAIL because structured fields and omission behavior are missing.

- [ ] **Step 3: Implement stable reasons**

Add compact literals `timeout`, `upstream_unavailable`, `converter_failed`, `internal_error` to `SearchResponse`. Map exceptions in `attach_preflight_coverage()` without failing search.

- [ ] **Step 4: Add guess fields**

Expose on `SearchResult`:

```python
preflight_coverage_guess: str | None = None
preflight_coverage_reason: str | None = None
preflight_confidence: Literal["high", "medium", "low"] | None = None
```

Keep `coverage_hint.expected_coverage` for compatibility, but omit `coverage_hint` when it contains only unknown/no-signal values.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_routes/test_search.py tests/unit/test_source_preflight.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/models/responses.py pubtator_link/services/search_coverage.py pubtator_link/services/source_preflight.py tests/test_routes/test_search.py tests/unit/test_source_preflight.py
git commit -m "feat: expose structured search preflight diagnostics"
```

### Task 3: Inspect Review Index Citation Metadata

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
@pytest.mark.asyncio
async def test_inspect_review_index_attaches_citation_metadata() -> None:
    service = ReviewContextService(FakeRepository(), metadata_service=FakeMetadataService())

    response = await service.inspect_review_index(
        "review-1",
        InspectReviewIndexRequest(include_metadata=True, metadata="basic"),
    )

    assert response.sources[0].citation_metadata.title == "Citation title"
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/test_routes/test_reviews.py -q`
Expected: FAIL because request fields and metadata are absent.

- [ ] **Step 3: Implement model and service support**

Add `include_metadata: bool = False`, `metadata: Literal["basic", "full"] = "basic"` to `InspectReviewIndexRequest`, and `citation_metadata: PublicationMetadata | None = None` to `ReviewSourceSummary`. In service, batch PMIDs from sources and call `PublicationMetadataService.get_metadata()`.

- [ ] **Step 4: Expose REST/MCP args**

Add `include_metadata` and `metadata` to REST query parameters and MCP tool signatures.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_context_service.py pubtator_link/api/routes/reviews.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/service_adapters.py tests/unit/test_review_context_service.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: attach citation metadata to review index inspection"
```

### Task 4: Tail Preview And High-Drop Guidance

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context/packing.py`
- Modify: `pubtator_link/services/review_context/diagnostics.py`
- Test: `tests/unit/test_review_context_packing.py`
- Test: `tests/unit/test_review_context_diagnostics.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_truncated_context_passage_includes_tail_preview() -> None:
    passage = context_passage_from_row(_row(text="A" * 260), citation_key="1", max_chars=80)

    assert passage.truncated is True
    assert passage.tail_preview == "A" * 120
    assert passage.next_window_token is None


def test_high_drop_nonzero_query_summary_has_next_steps() -> None:
    summary = query_summary(
        query="MEFV colchicine",
        candidates=[_candidate("1") for _ in range(10)],
        selected=[_candidate("1")],
        returned_count=1,
        dropped_count=9,
    )

    assert summary.next_steps
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_context_packing.py tests/unit/test_review_context_diagnostics.py -q`
Expected: FAIL because fields/guidance are missing.

- [ ] **Step 3: Add fields and deterministic guidance**

Add `tail_preview: str | None = None` and `next_window_token: str | None = None` to `ContextPassage`. In packing, when truncating, take `row.text[end_char:end_char + 120].strip()` as preview. In diagnostics, add next steps when `dropped_count >= returned_count * 3 and dropped_count >= 3`.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/test_review_context_packing.py tests/unit/test_review_context_diagnostics.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_context/packing.py pubtator_link/services/review_context/diagnostics.py tests/unit/test_review_context_packing.py tests/unit/test_review_context_diagnostics.py
git commit -m "feat: surface truncation and high-drop guidance"
```

### Task 5: Per-PMID Batch Budgeting

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context/batch_budgeting.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_batch_budgeting_honors_min_passages_per_pmid() -> None:
    merged = merge_batch_context(
        [_response_with_pmids(["1", "1", "2"])],
        max_total_passages=2,
        min_passages_per_pmid=1,
    )

    assert {passage.pmid for passage in merged.passages} == {"1", "2"}


def test_batch_response_includes_pmid_status_summary() -> None:
    response = _batch_response()

    assert response.pmid_status_summary[0].pmid == "1"
    assert response.pmid_status_summary[0].passages_returned >= 0
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/test_routes/test_reviews.py -q`
Expected: FAIL because request/response fields are absent.

- [ ] **Step 3: Implement models and packing**

Add request fields:

```python
min_passages_per_pmid: int = Field(default=0, ge=0, le=10)
prioritize_pmids: list[str] = Field(default_factory=list)
```

Add `PmidStatusSummary` and `pmid_status_summary` to batch response. In `merge_batch_context`, first select prioritized PMIDs, then ensure one pass per PMID up to `min_passages_per_pmid`, then spend overflow by existing strategy.

- [ ] **Step 4: Expose MCP/REST args**

Add args to batch retrieval adapters and route models.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_context/batch_budgeting.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/service_adapters.py tests/unit/test_review_context_batch_budgeting.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: add per-PMID batch retrieval budgeting"
```

### Task 6: Capabilities Token Ergonomics

**Files:**
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/metadata.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/test_workflow_help.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_capabilities_document_schema_policy_and_stable_citation_semantics() -> None:
    capabilities = get_capabilities_resource()

    assert capabilities["search_defaults"]["metadata"] == "basic"
    assert capabilities["schema_policy"]["argument_style"] == "flat"
    assert capabilities["citation_keys"]["stable_citation_key"].startswith("Stable across")
    assert capabilities["section_taxonomy"]["canonical_case"] == "lowercase"


def test_tool_descriptions_do_not_repeat_long_research_notice() -> None:
    mcp = create_pubtator_mcp()
    repeated = [
        tool.description
        for tool in mcp._tool_manager._tools.values()
        if tool.description and "not for diagnosis, treatment, triage" in tool.description
    ]

    assert repeated == []
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py -q`
Expected: FAIL because policy fields and description cleanup are incomplete.

- [ ] **Step 3: Update capabilities/workflow**

Add `schema_policy`, `citation_keys`, `section_taxonomy`, `notice`, and relation-discovery workflow step. Keep the full research-use notice only in server instructions/capabilities/workflow help notice.

- [ ] **Step 4: Update docs**

In `docs/MCP_CONNECTION_GUIDE.md`, state that `stable_citation_key` is stable across repeated retrieval calls and review index snapshots for the same passage identity.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/mcp/resources.py pubtator_link/mcp/metadata.py pubtator_link/services/workflow_help.py docs/MCP_CONNECTION_GUIDE.md tests/unit/mcp/test_mcp_facade.py tests/unit/test_workflow_help.py
git commit -m "docs: improve MCP citation and schema ergonomics"
```

### Task 7: Final Verification

- [ ] **Step 1: Run formatting**

Run: `make format`
Expected: exit 0.

- [ ] **Step 2: Run local CI**

Run: `make ci-local`
Expected: exit 0.

## Self-Review

Spec coverage:
- MCP metadata default and typed authors: Task 1.
- Preflight diagnostics and guess naming: Task 2.
- Inspect metadata: Task 3.
- Tail preview and high-drop guidance: Task 4.
- Per-PMID batch budgeting and status summary: Task 5.
- Global notice, schema policy, stable citation key semantics, section taxonomy, and relation discovery promotion: Task 6.

Placeholder scan: no placeholder terms or unspecified test commands remain.

Type consistency: `PublicationAuthor`, `preflight_coverage_guess`, `tail_preview`, `min_passages_per_pmid`, and `pmid_status_summary` are named consistently across model/service/API tasks.
