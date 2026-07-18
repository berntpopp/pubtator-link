# Review re-RAG Modularization Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-01

## Goal

Split review re-RAG internals into smaller, focused modules without changing
REST or MCP response behavior.

## Problem

Review re-RAG now works and is tested, but important logic is concentrated in a
few large modules:

- `pubtator_link/services/review_context_service.py`: 810 lines.
- `pubtator_link/repositories/review_rerag.py`: 776 lines.
- `pubtator_link/services/full_text_preparation.py`: 354 lines.

The main service mixes retrieval orchestration, reranking, passage packing,
batch budgeting, diagnostics, truncation, source-fair allocation, and response
assembly. The repository mixes SQL execution with row-to-model mapping. These
large files increase review cost, merge conflict risk, and LLM coding error
rate.

## Non-Goals

- Do not change REST endpoint paths or request/response schemas.
- Do not change public MCP tool names or schemas.
- Do not change ranking formulas.
- Do not change budget defaults.
- Do not change SQL queries except import paths needed for mapper extraction.
- Do not introduce embeddings or new external services.
- Do not require PostgreSQL for unit tests.

## Proposed Architecture

Keep `ReviewContextService` as the public service facade used by REST, MCP, and
dependency wiring. Extract pure or mostly-pure collaborators:

- `pubtator_link/services/review_context/ranking.py`
  - owns section/source priority constants and `rerank_key`.
- `pubtator_link/services/review_context/packing.py`
  - owns passage filtering, truncation, character budgets, citation passage
    conversion, and context budget totals.
- `pubtator_link/services/review_context/batch_budgeting.py`
  - owns query-fair, source-fair, and scarcity-first merged passage selection.
- `pubtator_link/services/review_context/diagnostics.py`
  - owns zero-result reason selection, next-step construction, query token
    handling, and diagnostics response assembly.
- `pubtator_link/repositories/review_rerag_mappers.py`
  - owns row-to-model conversion helpers currently at the bottom of
    `review_rerag.py`.

`ReviewContextService` should orchestrate:

1. build repository requests.
2. sort candidates using `ranking.rerank_key`.
3. call packing helpers for single-query retrieval.
4. call batch budgeting helpers for batch retrieval.
5. call diagnostics helpers when diagnostics are needed.
6. return existing Pydantic response models.

## Module Boundaries

### Ranking

`ranking.py` should have no repository, service, or FastAPI imports. It should
depend only on `ReviewPassageRow`.

Expected public function:

```python
def rerank_key(row: ReviewPassageRow) -> tuple[float, int, int, str, str]:
    return (
        -row.lexical_rank,
        SECTION_PRIORITY.get(row.section.strip().lower(), 100),
        SOURCE_PRIORITY.get(row.source_kind, 100),
        row.pmid or "",
        row.passage_id,
    )
```

### Packing

`packing.py` should contain deterministic, unit-testable functions for:

- section/table/reference inclusion decisions.
- oversized passage truncation around query-token matches.
- passage over-budget drop construction.
- selected passage conversion to `ContextPassage`.
- `ContextBudget` and text/token totals.

It may define small dataclasses for intermediate results, such as:

```python
@dataclass(frozen=True)
class PackedPassages:
    selected: list[ReviewPassageRow]
    dropped: list[DroppedPassage]
```

### Batch Budgeting

`batch_budgeting.py` should isolate the highest-risk logic in
`retrieve_context_batch()`:

- deduplication across per-query results.
- query-fair first pass.
- source-fair first pass.
- scarcity-first source ordering.
- global response budget enforcement.
- `SourceBudgetSummary` accounting.

It should accept already-built per-query `RetrieveReviewContextResponse`
objects and return merged passages, dropped passages, source summaries, and
budget data needed by `ReviewContextService`.

### Diagnostics

`diagnostics.py` should make zero-result and partial-result guidance testable
without constructing a full service. It should preserve current messages and
reason values:

- `no_indexed_passages`
- `filters_removed_all_candidates`
- `all_candidates_over_budget`
- `no_query_tokens`
- default query-relaxation guidance

### Repository Mappers

Move these helpers from `review_rerag.py` to
`review_rerag_mappers.py`:

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

Keep names private at first to reduce public API claims. Import them from
`review_rerag.py`.

## Public Contract

The following response models and observable behavior must remain unchanged:

- `RetrieveReviewContextResponse`
- `RetrieveReviewContextBatchResponse`
- `ContextPack`
- `ContextPassage`
- `ContextBudget`
- `RetrieveReviewDiagnostics`
- `ReviewQuerySummary`
- `SourceBudgetSummary`
- `ReviewIndexInspection`

Existing REST tests, MCP adapter tests, and review context service tests should
continue to pass unchanged.

## Error Handling

Error behavior should remain the responsibility of current service and route
layers:

- repository failures bubble up as they do today.
- route `handle_api_errors` behavior stays unchanged.
- diagnostics describe empty or over-budget retrieval states, not system
  exceptions.
- mapper functions should retain current behavior for missing optional fields.

## Testing

Use a characterization-first approach:

1. Keep existing `tests/unit/test_review_context_service.py` expectations
   unchanged.
2. Add small pure-unit tests for extracted helpers before moving logic.
3. Move logic behind the helper tests.
4. Re-run service tests after each extraction.

Focused tests:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
uv run pytest tests/unit/test_review_rerag_repository.py -q
uv run pytest tests/unit/test_review_rerag_models.py -q
```

Completion gate:

```bash
make ci-local
make test-cov
```

## Rollout

Implement in slices:

1. Extract repository mappers. This is low risk and reduces the repository file
   size without touching service behavior.
2. Extract ranking and packing helpers. These are mostly pure and already
   covered by service behavior tests.
3. Extract diagnostics helpers. Preserve messages and reason values exactly.
4. Extract batch budgeting. This is highest risk, so do it after smaller helper
   boundaries exist.
5. Clean up `ReviewContextService` imports and remove dead private methods.

Each slice should commit independently and pass focused tests.

## Risks And Mitigations

Risk: batch budgeting behavior changes during extraction.

Mitigation: leave batch extraction last, add focused helper tests for
query-fair, source-fair, scarcity-first, deduplication, and response-budget
drops before moving code.

Risk: pure helper modules duplicate model conversion logic.

Mitigation: move code rather than reimplementing it. Keep helper signatures
close to existing private method signatures.

Risk: too many tiny abstractions make the service harder to follow.

Mitigation: extract around real responsibilities only: ranking, packing,
diagnostics, batch budgeting, and repository mapping.

Risk: imports become cyclic.

Mitigation: helper modules must depend on models only. They must not import
`ReviewContextService`, FastAPI routes, MCP modules, or dependency wiring.

## Success Criteria

- `ReviewContextService` is an orchestration layer rather than the home of all
  retrieval mechanics.
- Repository SQL execution is separated from row mapping helpers.
- Existing REST and MCP response behavior is unchanged.
- New helper modules have focused unit tests.
- `make ci-local` passes.
- `make test-cov` passes at the enforced 80% threshold.
