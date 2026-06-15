# MCP LLM Performance And Maintainability Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the superseded May 2026 MCP/review-retrieval plans with one prioritized implementation path that improves LLM tool performance, payload economics, trust, maintainability, and retrieval quality without breaking the current deterministic PubTator-Link backend.

**Architecture:** Keep the current review-scoped re-RAG foundation as the source of truth: search/discovery feeds `index_review_evidence`, prepared passages feed `retrieve_review_context_batch`, and graph tools remain candidate-selection helpers rather than claim-grounding tools. First fix compact defaults, pagination, budget controls, metadata batching, and failure telemetry; then add optional dense retrieval as a disabled-by-default sidecar. Avoid backend LLM dependencies, preserve stable citation keys and cache keys, and keep full/debug response modes opt-in.

**Tech Stack:** Python 3.12, FastAPI/FastMCP, Pydantic v2, asyncpg/PostgreSQL, optional pgvector/Sentence Transformers for private deployments only, pytest, Ruff, mypy, existing Makefile targets.

---

## Superseded Inputs

This plan replaces these active docs. They should stay archived as superseded context and should not be executed literally:

- `docs/superpowers/plans/2026-04-30-pubtator-evidence-review-workflow.md`
- `docs/superpowers/plans/2026-05-03-hybrid-embedding-reranker-implementation.md`
- `docs/superpowers/plans/2026-05-03-mcp-ground-question-and-guideline-budget-implementation.md`
- `docs/superpowers/specs/2026-05-03-hybrid-embedding-reranker-design.md`
- `docs/superpowers/specs/2026-05-03-llm-first-literature-graph-redesign.md`
- `docs/superpowers/specs/2026-05-03-mcp-error-telemetry-and-quote-controls-design.md`
- `docs/superpowers/specs/2026-05-03-mcp-ground-question-and-guideline-budget-design.md`
- `docs/2026-05-03-mcp-llm-lean-speed-accuracy-report.md`
- `docs/2026-05-02-pubtator-link-consolidated-roadmap.md`
- MCP Evaluation v2 notes from two end-to-end runs.

## Verified Current State

- Shipped: review-scoped indexing and retrieval via `pubtator_link/models/review_rerag.py`, `pubtator_link/services/review_context_service.py`, `pubtator_link/repositories/review_rerag.py`, and `pubtator_link/mcp/tools/review.py`.
- Shipped: `ground_question`, stable citation keys, quote mode, compact search author summaries, `retrieve_review_context_batch(dry_run=True)`, review resources, graph candidate tools, and hosted research-use scoping.
- Partial: `inspect_review_index` has compact serialization but no pagination.
- Partial: `ground_question` exists but has no `verbosity` or `"auto"` budget arguments and hard-codes `max_response_chars=12000`.
- Partial: graph compact modes exist, but MCP adapters still default omitted `response_mode` to `"full"`, graph budgets are classified after serialization rather than enforced, and graph `cache_key` is modeled but usually `null`.
- Missing: persistent cross-worker MCP error telemetry, strict quote controls, internal PubMed metadata batching for large lists, optional dense embedding rerank, and standards workflow state.

## Best-Practice Basis

Use these principles while implementing:

- MCP tool lists should be deterministic and paginated where large; deterministic ordering improves client caching and prompt-cache behavior. See MCP tools and pagination specs.
- Tool schemas should be obvious, strict, and small enough for the model to choose correctly. Prefer fewer active tools, enums for invalid states, explicit parameter names, and code-side orchestration for operations that are always called together.
- Tool errors and truncation metadata should steer the model toward filters, pagination, or recovery calls instead of silent data loss.
- Safety and authorization boundaries must stay explicit; do not request secrets through MCP form inputs, and keep public tools research-use scoped.
- Evaluate with real transcript-style workflows. LLM ergonomics regressions are often response-shape regressions, not only test failures.

## Priority Order

1. **P0: Payload and latency controls.** Compact graph defaults, enforced graph budgets, cache keys, `inspect_review_index` pagination, auto response budgets, and PubMed metadata batching.
2. **P1: Trust and retry correctness.** Persistent sanitized MCP error telemetry, quote controls with exact offsets, and accurate idempotence annotations.
3. **P2: Retrieval quality.** Deterministic score breakdowns, source-aware ranking, and optional dense rerank with lexical fallback.
4. **P3: Review workflow state.** Protocol/screening/extraction/risk-of-bias state only after the LLM/tool ergonomics surface is stable.
5. **P3: Runtime docs and evals.** Generated catalog/error references and transcript regression cases.

---

## Task 1: Make Graph Tools Compact-First And Budgeted

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/literature_graph_compact.py`
- Modify: `pubtator_link/services/citation_graph.py`
- Modify: `pubtator_link/services/topic_literature_map.py`
- Modify: `pubtator_link/services/related_evidence.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/test_citation_graph_service.py`
- Test: `tests/unit/test_topic_literature_map_service.py`
- Test: `tests/unit/test_related_evidence_service.py`

- [ ] **Step 1: Write failing MCP default tests**

Add tests proving these adapter calls default to compact when `response_mode` is omitted:

```python
await get_publication_citation_graph_impl(service=service, pmid="123")
await find_related_evidence_candidates_impl(service=service, pmid="123")
await build_topic_literature_map_impl(service=service, query="MEFV")
```

Expected assertions:

```python
assert service.request.response_mode == "compact"
assert "response_mode_deprecation" not in result.get("_meta", {}).get("warnings", [])
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q -k "citation_graph or related_evidence or topic_literature_map"
```

Expected: FAIL because the adapters currently use `response_mode or "full"`.

- [ ] **Step 3: Change MCP graph defaults**

In `pubtator_link/mcp/service_adapters.py`, set omitted graph `response_mode` to `"compact"` for all three graph adapters. Remove the deprecation warning path after tests prove callers can still request `"full"` explicitly.

In `pubtator_link/mcp/tools/publications.py`, change graph tool signatures from:

```python
response_mode: LiteratureGraphResponseModeArg | None = None
```

to:

```python
response_mode: LiteratureGraphResponseModeArg = "compact"
```

- [ ] **Step 4: Enforce compact graph budgets**

Add a helper in `pubtator_link/services/literature_graph_compact.py` that takes a serialized response and a per-mode budget, then drops deterministic optional fields before the response leaves the service.

Required behavior:

- Compact target is 12 KB for normal graph candidate use.
- `nodes_edges` target is 40 KB.
- Drop order for compact topic maps: demoted candidate details beyond cap, lowest-ranked optional candidate explanations, paper-record summary arrays, then low-value provider detail.
- Drop order for compact citation graphs: unresolved DOI-only candidate details beyond cap, lowest-ranked optional explanations, provider-detail repetition.
- Set `_meta.truncated=True`, `_meta.omitted_counts`, and `_meta.budget_advice` when any drop happens.

- [ ] **Step 5: Populate graph cache keys**

Use `stable_cache_key()` with each graph request's normalized payload:

```python
stable_cache_key("literature_graph", {"tool": tool_name, "request": request.model_dump(mode="json")})
```

Set `_meta.cache_key`, `_meta.snapshot_date`, and `_meta.source_versions`.

- [ ] **Step 6: Clean compact topic map shape**

Add a compact serializer for `TopicLiteratureMapResponse` so empty `nodes` and `edges` are omitted in compact mode. Replace compact summary paper-record arrays with count and PMID lists where the same data exists in `top_candidates`, `recommended_next_pmids`, `accessible_full_text_pmids`, or `closed_central_pmids`.

- [ ] **Step 7: Normalize graph score semantics**

In `RelatedEvidenceCandidate`, keep `normalized_neighbor_score` as the LLM-facing score. Either hide raw `score`/`pubmed_neighbor_score` in compact mode or add `score_units="pubmed_neighbor_raw_count"` plus a warning that raw values are ranking internals, not evidence quality.

- [ ] **Step 8: Run focused graph tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/test_citation_graph_service.py tests/unit/test_topic_literature_map_service.py tests/unit/test_related_evidence_service.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/publications.py pubtator_link/models/literature_graph.py pubtator_link/services/literature_graph_compact.py pubtator_link/services/citation_graph.py pubtator_link/services/topic_literature_map.py pubtator_link/services/related_evidence.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/test_citation_graph_service.py tests/unit/test_topic_literature_map_service.py tests/unit/test_related_evidence_service.py
git commit -m "feat: make literature graph tools compact-first"
```

---

## Task 2: Add Compact Pagination To `inspect_review_index`

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/test_review_rerag_repository.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing pagination tests**

Add tests for:

- `InspectReviewIndexRequest(limit=10)` returns at most 10 `sources`.
- Response includes `next_cursor` when more sources remain.
- `cursor` loads the next page without repeating the first source.
- `response_mode="compact"` omits resolver traces and metadata.
- Totals and coverage summary remain global, not page-only.

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_reviews.py -q -k "inspect_review_index"
```

Expected: FAIL because `limit`, `cursor`, and `next_cursor` do not exist.

- [ ] **Step 3: Add cursor model fields**

Extend `InspectReviewIndexRequest`:

```python
limit: int = Field(default=50, ge=1, le=100)
cursor: str | None = None
```

Extend `InspectReviewIndexResponse`:

```python
next_cursor: str | None = None
page_source_count: int = 0
page_failed_source_count: int = 0
```

Use an opaque base64url JSON cursor:

```json
{"offset": 50}
```

Reject invalid cursors with a stable validation error.

- [ ] **Step 4: Add repository pagination**

Add optional `limit` and `offset` arguments to `list_review_sources()` and `list_review_failed_sources()` repository methods. Keep existing call sites equivalent by passing `None` where full lists are required for snapshots and diagnostics.

- [ ] **Step 5: Wire MCP and REST surfaces**

Expose `limit` and `cursor` in `inspect_review_index_impl`, the MCP tool, and REST route request parsing. Default MCP response mode remains `"compact"`.

- [ ] **Step 6: Add payload recovery hints**

When `next_cursor` is present, add `_meta.next_commands` guidance for the next `inspect_review_index` page. Do not include passage samples by default.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_reviews.py -q -k "inspect_review_index"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/repositories/review_rerag.py pubtator_link/services/review_context_service.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py pubtator_link/api/routes/reviews.py tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_reviews.py
git commit -m "feat: paginate review index inspection"
```

---

## Task 3: Add Auto Budgets And Verbosity For Review Retrieval

**Files:**
- Create: `pubtator_link/services/review_context/budgets.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/input_normalization.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Test: `tests/unit/test_review_context_budgets.py`
- Test: `tests/unit/mcp/test_mcp_input_normalization.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write budget helper tests**

Expected mapping:

```python
assert resolve_max_response_chars("auto", verbosity="lean") == 12000
assert resolve_max_response_chars("auto", verbosity="standard") == 24000
assert resolve_max_response_chars("auto", verbosity="full") == 60000
assert resolve_max_response_chars(36000, verbosity="lean") == 36000
```

- [ ] **Step 2: Run helper tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py -q
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement `budgets.py`**

Add:

```python
ReviewResponseVerbosity = Literal["lean", "standard", "full"]
MaxResponseChars = int | Literal["auto"]
AUTO_RESPONSE_BUDGETS = {"lean": 12000, "standard": 24000, "full": 60000}
```

`resolve_max_response_chars()` must reject integers outside the existing `2000..100000` range and reject non-`"auto"` strings.

- [ ] **Step 4: Expose on batch retrieval**

Add `verbosity` and `max_response_chars: int | Literal["auto"] = "auto"` to:

- `RetrieveReviewContextBatchRequest`
- `retrieve_review_context_batch_impl`
- `get_review_context_batch`
- normalization allow-list and enum casing tests

Resolve `"auto"` before constructing the Pydantic request model.

- [ ] **Step 5: Expose on `ground_question`**

Add `verbosity` and `max_response_chars` to `ground_question_impl` and `ground_question`. Replace the hard-coded `max_response_chars=12000` with the shared helper.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "budget or ground_question or retrieve_review_context_batch"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/services/review_context/budgets.py pubtator_link/models/review_rerag.py pubtator_link/mcp/input_normalization.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py tests/unit/test_review_context_budgets.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add auto review response budgets"
```

---

## Task 4: Batch PubMed Metadata Internally And Degrade Gracefully

**Files:**
- Modify: `pubtator_link/services/publication_metadata.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/services/related_evidence.py`
- Modify: `pubtator_link/services/citation_graph.py`
- Test: `tests/unit/test_publication_metadata_service.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/test_related_evidence_service.py`

- [ ] **Step 1: Write failing batching tests**

Add tests proving:

- Internal metadata lookup accepts more than 100 PMIDs by chunking into PubMed-sized batches.
- One failed metadata batch yields warnings and still returns metadata from successful batches.
- `inspect_review_index(include_metadata=True)` with more than 100 sources does not raise a Pydantic validation error.
- `find_related_evidence_candidates` does not return bare PMIDs solely because there are more than 100 metadata candidates.

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_publication_metadata_service.py tests/unit/test_review_context_service.py tests/unit/test_related_evidence_service.py -q -k "metadata"
```

Expected: FAIL for large internal metadata lists.

- [ ] **Step 3: Add internal batched metadata helper**

Keep public `PublicationMetadataRequest.pmids` capped at 100 for API ergonomics. Add a service helper that accepts a sequence:

```python
async def get_metadata_batched(
    self,
    pmids: Sequence[str],
    *,
    include_mesh: bool,
    include_publication_types: bool,
    include_citations: IncludeCitations,
    include_coverage: bool,
) -> PublicationMetadataResponse:
```

Chunk by 100, preserve input order, deduplicate PMIDs, merge `failed_pmids`, and add provider warnings without raising for partial failure.

- [ ] **Step 4: Use the helper at internal call sites**

Use the helper in:

- `_search_metadata_by_pmid`
- `ReviewContextService._attach_source_metadata`
- `RelatedEvidenceService._metadata_candidates`
- citation graph source/candidate enrichment where a list can exceed one item

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_publication_metadata_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_review_context_service.py tests/unit/test_related_evidence_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/publication_metadata.py pubtator_link/mcp/service_adapters.py pubtator_link/services/review_context_service.py pubtator_link/services/related_evidence.py pubtator_link/services/citation_graph.py tests/unit/test_publication_metadata_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_review_context_service.py tests/unit/test_related_evidence_service.py
git commit -m "fix: batch PubMed metadata lookups internally"
```

---

## Task 5: Fix MCP Trust, Retry, And Quote Semantics

**Files:**
- Add: `pubtator_link/db/migrations/0005_mcp_tool_errors.sql`
- Add: `pubtator_link/services/mcp_error_telemetry.py`
- Modify: `pubtator_link/mcp/errors.py`
- Modify: `pubtator_link/services/diagnostics.py`
- Modify: `pubtator_link/mcp/annotations.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context/quotes.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/mcp/input_normalization.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/test_mcp_errors.py`
- Test: `tests/unit/test_diagnostics_service.py`
- Test: `tests/unit/test_review_context_quotes.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add persistent sanitized error telemetry tests**

Tests must prove:

- `record_mcp_error()` still records to bounded process memory.
- When a telemetry repository is configured, sanitized errors persist to `mcp_tool_errors`.
- Diagnostics merges persisted and in-memory errors and deduplicates stable duplicates.
- Persistence failures never make the original MCP tool failure worse.
- Stored `raw_message` is sanitized and capped; it must not contain request args, passage text, full user questions, or database host details.

- [ ] **Step 2: Add telemetry migration**

Create `0005_mcp_tool_errors.sql`:

```sql
create table if not exists mcp_tool_errors (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    tool_name text not null,
    error_code text not null,
    message text not null,
    raw_message text,
    request_id text,
    worker_id text
);

create index if not exists idx_mcp_tool_errors_created_at
    on mcp_tool_errors (created_at desc);
```

This default migration is safe for plain PostgreSQL and must not depend on pgvector.

- [ ] **Step 3: Implement telemetry helper**

Add `pubtator_link/services/mcp_error_telemetry.py` with:

- sanitized record dataclass
- best-effort async writer
- recent read method
- retention cleanup method
- no dependency from low-level `mcp/errors.py` back into FastAPI dependencies

- [ ] **Step 4: Correct idempotence annotations**

Split `REVIEW_WRITE_ANNOTATIONS` into:

- idempotent for `index_review_evidence`
- non-idempotent for append-style calls such as `record_review_context`
- conditionally idempotent guidance for upserts that require caller-supplied IDs

Update tests that inspect MCP tool annotations.

- [ ] **Step 5: Add quote controls**

Add request fields:

```python
min_quote_chars: int | None = Field(default=None, ge=20, le=350)
require_claim_indicator: bool = False
claim_density_mode: Literal["off", "prefer", "require"] = "prefer"
```

Apply strict filtering only when `response_mode="quotes"`.

Required dropped reasons:

- `quote_below_min_chars`
- `claim_indicator_required`

All-dropped quote responses must return an empty `quotes` list plus a recovery hint that suggests lowering `min_quote_chars`, switching `claim_density_mode` to `"prefer"`, or using `response_mode="compact"`.

- [ ] **Step 6: Preserve quote offsets**

Extend `ReviewQuote` with returned and original offset fields copied from `PassageQuote` when available. Quote mode can keep `merged_context_pack.passages=[]`, but `quotes[]` must be exact-offset auditable without a follow-up call when the source passage had offsets.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_mcp_errors.py tests/unit/test_diagnostics_service.py tests/unit/test_review_context_quotes.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/db/migrations/0005_mcp_tool_errors.sql pubtator_link/services/mcp_error_telemetry.py pubtator_link/mcp/errors.py pubtator_link/services/diagnostics.py pubtator_link/mcp/annotations.py pubtator_link/mcp/tools/review.py pubtator_link/models/review_rerag.py pubtator_link/services/review_context/quotes.py pubtator_link/services/review_context_service.py pubtator_link/mcp/input_normalization.py pubtator_link/mcp/service_adapters.py tests/unit/test_mcp_errors.py tests/unit/test_diagnostics_service.py tests/unit/test_review_context_quotes.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: persist MCP errors and add quote controls"
```

---

## Task 6: Improve Retrieval Ranking Without Sacrificing Determinism

**Files:**
- Modify: `pubtator_link/services/review_context/ranking.py`
- Modify: `pubtator_link/services/review_context/packing.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Optional add: `pubtator_link/services/review_context/embeddings.py`
- Optional add: `pubtator_link/services/review_context/embedding_rerank.py`
- Optional add: `pubtator_link/services/review_context/embedding_backfill.py`
- Optional add: `pubtator_link/db/optional_migrations/pgvector_review_passage_embeddings.sql`
- Test: `tests/unit/test_review_context_ranking.py`
- Test: `tests/unit/test_review_context_service.py`
- Optional test: `tests/unit/test_review_context_embeddings.py`
- Optional test: `tests/unit/test_review_context_embedding_rerank.py`
- Optional test: `tests/unit/test_review_context_embedding_backfill.py`

- [ ] **Step 1: Centralize non-evidence section classification**

Add one classifier used by both ranking and packing:

```python
def is_non_evidence_section(section: str) -> bool:
    normalized = section.strip().casefold()
    return normalized in {"ref", "refs", "reference", "references", "abbr", "abbreviations"}
```

Tests must prove `REF`, `references`, and `ABBR` cannot be promoted above evidence sections by ranking changes.

- [ ] **Step 2: Add deterministic score breakdown**

Add an optional score object to returned context passages or diagnostics:

```python
{
  "lexical_score": float | None,
  "section_score": float,
  "source_coverage_score": float,
  "entity_overlap_score": float | None,
  "final_rank_reason": list[str]
}
```

This is explanatory only; it must not change the existing result shape in compact mode unless explicitly requested or already present in diagnostics.

- [ ] **Step 3: Add metadata/query expansion before dense retrieval**

For review retrieval, add bounded query expansion from known entity IDs, MeSH headings, publication types, and exact PMID filters when already available. Keep the expansion deterministic and visible in diagnostics.

- [ ] **Step 4: Implement optional dense rerank sidecar**

Dense rerank is disabled by default. It must not require pgvector, Torch, Sentence Transformers, or optional migrations during default startup or `make ci-local`.

Rules:

- Keep Postgres FTS as recall.
- Fetch top lexical candidates, usually 50 to 80.
- Sort candidates with existing `rerank_key()` and assign ordinal lexical positions.
- Compute dense positions only for candidates with current embeddings.
- Fuse with RRF using ordinal positions, not `ReviewPassageRow.lexical_rank` because that field is a float SQL score.
- Tie-break with existing section/source/PMID/passage ordering.
- If provider, model, dimension, table, or query embedding is unavailable, fall back to lexical ranking with diagnostics.

- [ ] **Step 5: Keep pgvector optional**

Do not place `create extension vector` in an always-applied default migration. Use one of these patterns:

- optional migration folder plus explicit command, or
- runtime table creation only when `PUBTATOR_LINK_REVIEW_EMBEDDING_RERANK_ENABLED=true` and pgvector is available.

Default Docker and default CI must work on plain PostgreSQL.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_ranking.py tests/unit/test_review_context_service.py tests/unit/test_review_context_embeddings.py tests/unit/test_review_context_embedding_rerank.py tests/unit/test_review_context_embedding_backfill.py -q
```

Expected: PASS. If optional embedding tests are not added in the same slice, run the ranking and service tests only.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/services/review_context/ranking.py pubtator_link/services/review_context/packing.py pubtator_link/models/review_rerag.py pubtator_link/services/review_context_service.py tests/unit/test_review_context_ranking.py tests/unit/test_review_context_service.py
git commit -m "feat: improve deterministic review retrieval ranking"
```

If optional dense files are included:

```bash
git add pubtator_link/services/review_context/embeddings.py pubtator_link/services/review_context/embedding_rerank.py pubtator_link/services/review_context/embedding_backfill.py pubtator_link/db/optional_migrations/pgvector_review_passage_embeddings.sql tests/unit/test_review_context_embeddings.py tests/unit/test_review_context_embedding_rerank.py tests/unit/test_review_context_embedding_backfill.py
git commit -m "feat: add optional review embedding rerank sidecar"
```

---

## Task 7: Add Standards Workflow State After Tool Ergonomics Stabilize

**Files:**
- Add: `pubtator_link/models/review_workflow.py`
- Add: `pubtator_link/services/review_workflow.py`
- Add: `pubtator_link/db/migrations/0006_review_workflow_state.sql`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Test: `tests/unit/test_review_workflow_models.py`
- Test: `tests/unit/test_review_workflow_service.py`
- Test: `tests/unit/test_review_rerag_repository.py`
- Test: `tests/test_routes/test_reviews.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add protocol and question models**

Add PICO/PECO/PICOTS-compatible structured fields without forcing one standard:

```python
class ReviewProtocol(BaseModel):
    review_id: str
    objective: str
    population: str | None = None
    exposure_or_intervention: str | None = None
    comparator: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    study_designs: list[str] = Field(default_factory=list)
    created_by: str | None = None
```

- [ ] **Step 2: Add screening decision state**

Store reviewer/agent decisions as user-supplied facts, not backend judgments. Include `pmid`, `decision`, `reason`, `passage_ids`, `created_by`, and timestamps.

- [ ] **Step 3: Add extraction and risk-of-bias state**

Add structured extraction rows and risk-of-bias rows. Do not compute RoB; only store user/agent-supplied assessments and provenance.

- [ ] **Step 4: Add PRISMA-style counts**

Expose counts derived from search, staged candidates, indexed sources, screening decisions, and failed sources.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_workflow_models.py tests/unit/test_review_workflow_service.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/models/review_workflow.py pubtator_link/services/review_workflow.py pubtator_link/db/migrations/0006_review_workflow_state.sql pubtator_link/repositories/review_rerag.py pubtator_link/api/routes/reviews.py pubtator_link/mcp/tools/review.py tests/unit/test_review_workflow_models.py tests/unit/test_review_workflow_service.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add review workflow state"
```

---

## Task 8: Update Runtime Docs, Catalogs, And Evals

**Files:**
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/catalog.py`
- Test: `tests/unit/mcp/test_mcp_tool_catalog.py`
- Test: `tests/unit/mcp/test_mcp_resources.py`
- Add or modify: `tests/evals/` only if this repo already has eval patterns; otherwise keep eval fixtures under `tests/unit/mcp/`.

- [ ] **Step 1: Document stable citation and cache semantics**

Document:

- `stable_citation_key` is derived from stable passage identity, not from rank.
- `cache_key` is deterministic for request identity, not proof that upstream live corpus has frozen.
- `corpus_snapshot_date` and `index_snapshot_date` are the reproducibility date anchors.
- Graph relatedness is candidate discovery, not evidence quality.

- [ ] **Step 2: Update output cheatsheets**

Add `cache_key`, `next_cursor`, `omitted_counts`, `budget_advice`, quote offset fields, and strict quote dropped reasons to resources/catalog entries.

- [ ] **Step 3: Add transcript-style regression fixtures**

Create compact fixtures for:

- graph discovery -> index -> retrieve
- `inspect_review_index` pagination
- `ground_question` lean/standard/full budgets
- metadata batching with partial failure
- strict quote mode with all-dropped recovery
- MCP error telemetry visible in diagnostics

- [ ] **Step 4: Run docs-adjacent tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_tool_catalog.py tests/unit/mcp/test_mcp_resources.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/MCP_CONNECTION_GUIDE.md pubtator_link/mcp/resources.py pubtator_link/mcp/catalog.py tests/unit/mcp/test_mcp_tool_catalog.py tests/unit/mcp/test_mcp_resources.py tests/unit/mcp/test_mcp_facade.py
git commit -m "docs: document MCP reproducibility and payload contracts"
```

---

## Final Verification

- [ ] **Step 1: Run focused verification for the completed task**

Use the exact focused command listed in that task.

- [ ] **Step 2: Run full local CI before completion claims**

Run:

```bash
make ci-local
```

Expected: format, lint, typecheck, and tests all pass.

- [ ] **Step 3: Check active docs**

Run:

```bash
find docs/superpowers/plans docs/superpowers/specs -maxdepth 1 -type f | sort
```

Expected: this consolidated plan is the only active plan for the superseded MCP/review-retrieval work. Old docs are under superseded archive paths.

## Self-Review Checklist

- [ ] MCP graph tools default to compact and full/debug output is explicit.
- [ ] Large list-like outputs have cursor or bounded pagination.
- [ ] Response budgets are predictive where possible and honest when truncation happens.
- [ ] Graph and retrieval responses expose stable cache keys and snapshot dates.
- [ ] PubMed metadata calls batch internally and degrade with warnings.
- [ ] Tool errors are persisted across workers when the database is configured and sanitized before storage.
- [ ] MCP annotations accurately distinguish idempotent and append-style writes.
- [ ] Quote mode can require substantive claim-like quotes and expose exact offsets.
- [ ] Dense retrieval is optional, disabled by default, and never breaks plain Postgres startup.
- [ ] `make ci-local` passes before any completion claim.

## External References

- MCP tools specification: <https://modelcontextprotocol.io/specification/draft/server/tools>
- MCP pagination specification: <https://modelcontextprotocol.io/specification/draft/server/utilities/pagination>
- MCP security best practices: <https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>
- OpenAI function calling best practices: <https://developers.openai.com/api/docs/guides/function-calling>
- Anthropic tool-design guidance: <https://www.anthropic.com/engineering/writing-tools-for-agents>
- Anthropic multi-agent research lessons: <https://www.anthropic.com/engineering/multi-agent-research-system>
