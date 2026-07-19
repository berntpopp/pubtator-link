# MCP Ground Question And Guideline Budget Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-03

## Purpose

Make the documented PubTator-Link grounding workflow easier for LLM clients to
use correctly in one call while improving guideline source recall and response
budget ergonomics. The first implementation slice covers only the high-priority
bundle: guideline corpus coverage, a composite `pubtator.ground_question` MCP
tool, and auto response budgeting.

## Goals

- Ensure known source recommendations for familial Mediterranean fever and
  autoinflammatory disease guideline queries rank above guideline-adherence
  studies when `guideline_boost=true`.
- Add `pubtator.ground_question(question, max_pmids=8)` as a one-call MCP entry
  point for the canonical `search_literature -> index_review_evidence ->
  retrieve_review_context_batch` workflow.
- Add response budget ergonomics so callers can pass
  `max_response_chars="auto"` or a `verbosity` enum (`lean`, `standard`,
  `full`) instead of tuning character budgets manually.
- Preserve the existing explicit workflow tools and their current defaults.

## Non-Goals

- No backend LLM answer generation or clinical interpretation.
- No clinical decision support.
- No benchmark changes and no committed files under `benchmarks/`.
- No streaming retrieval, typed service-exception rollout, OpenTelemetry
  rollout, resource-template work, metadata enrichment, or token-shape cleanup
  outside the high-priority bundle.
- No hidden destructive cache or review-index operations.

## Current State

- `pubtator.search_literature` accepts `guideline_boost`, and
  `search_guidelines` wraps it with guideline publication-type filters.
- Current guideline ranking uses publication type plus broad terms such as
  `guideline`, `consensus`, `eular`, `pres`, and `share`.
- That ranking can prefer guideline-adherence or implementation studies over
  source recommendations when those papers contain many broad guideline terms.
- `review_quickstart` exists, but it stages candidates and inspects readiness;
  it does not retrieve grounded passages for the question in one call.
- `retrieve_review_context_batch` accepts numeric `max_response_chars` only.

## Public Surface

### Guideline Ranking

`guideline_boost=true` continues to be an optional search-time reranking hint.
Its scoring becomes more transparent and source-recommendation aware.

Add explicit source-guideline signals for known families:

- `EULAR` recommendations and the Ozen 2016 FMF recommendation family.
- `SHARE` recommendations and the Hentgen SHARE recommendation family.
- `Eurofever/PRINTO` recommendations, including the 2019 classification and
  management recommendation family.

The implementation should not hard-code exact PMIDs as the only signal. It may
use title, abstract, publication type, journal metadata, and PMID bonuses for
known landmark records when present. Source recommendation cues should outrank
guideline-adherence cues. Ranking reasons must expose which source-guideline
signals fired.

### `pubtator.ground_question`

Add an MCP tool:

```python
pubtator.ground_question(
    question: str,
    max_pmids: int = 8,
    review_id: str | None = None,
    entity_ids: list[str] | None = None,
    guideline_boost: bool = True,
    wait_until_ready: bool = True,
    timeout_ms: int = 30000,
    verbosity: Literal["lean", "standard", "full"] = "standard",
    max_response_chars: int | Literal["auto"] = "auto",
)
```

The tool should:

1. Search literature with `response_mode="standard"`, `include_citations="nlm"`,
   `metadata="basic"`, and `guideline_boost` passed through.
2. Select up to `max_pmids` unique PMIDs from the search results.
3. Derive a stable review id when the caller does not supply one.
4. Call `index_review_evidence` with `wait_until_ready=true` by default and a
   bounded timeout.
5. Call `retrieve_review_context_batch` with the original question as the first
   query and compact response mode.
6. Return a typed composite response containing search metadata, selected PMIDs,
   preparation status, retrieved merged context, recovery hints, and
   `next_commands`.

If no PMIDs are found, return success with an empty selected set, no indexing
attempt, no retrieval attempt, and next commands that suggest a refined
`search_literature` call.

If indexing times out or no passages are ready, return the search and index
status plus a `next_commands` entry for `inspect_review_index` and
`retrieve_review_context_batch`. Do not fabricate grounded passages.

### Auto Response Budget

Add a shared helper for review batch retrieval budgets. The helper maps:

- `lean` to `12000`
- `standard` to `24000`
- `full` to `60000`

When `max_response_chars="auto"`, the helper uses the value implied by
`verbosity`. When callers pass an integer, the explicit integer wins and
`verbosity` still controls future response-shaping defaults. Keep existing
numeric validation limits.

Expose `verbosity` and `"auto"` on `retrieve_review_context_batch` and use the
same helper in `ground_question`.

## Architecture

Keep the implementation inside the existing MCP and review RAG boundaries:

- Search reranking stays in `pubtator_link/services/search_shaping.py`.
- Composite tool orchestration lives in `pubtator_link/mcp/service_adapters.py`
  and `pubtator_link/mcp/tools/review.py`, matching existing MCP tool patterns.
- New request/response models live in `pubtator_link/models/review_rerag.py`.
- Budget resolution lives in a small helper module under
  `pubtator_link/services/review_context/` so model validation, service
  adapters, and future callers share one mapping.

## Error Handling

- Use existing `run_mcp_tool` wrapping for MCP error envelopes.
- Validate empty questions and invalid limits through Pydantic/FastMCP schema
  constraints where possible.
- Treat upstream search failures, index failures, and retrieval failures as real
  tool failures; do not silently return partial success after an exception.
- Treat no search hits, no selected PMIDs, indexing timeout, and no ready
  passages as successful partial workflow states with explicit recovery fields.

## Testing

Use TDD for each implementation task:

- Unit tests for guideline source recommendation ranking.
- Unit tests for auto budget resolution and input normalization.
- MCP facade/schema tests for `pubtator.ground_question`, `verbosity`, and
  `max_response_chars="auto"`.
- Service adapter tests with fake clients/services proving the composite call
  order and partial-state behavior.
- Focused verification with the exact tests in the implementation plan, then
  `make ci-local` before completion.

## Compatibility

- Existing `retrieve_review_context_batch(max_response_chars=<int>)` callers
  continue to work.
- Existing explicit workflow tools remain documented and callable.
- `review_quickstart` remains available for session staging; it is not renamed
  or repurposed.
- The new composite tool is additive and does not change hosted MCP read/write
  annotations for existing tools.

