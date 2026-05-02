# Review Batch Budgeting Test Hardening Design

Date: 2026-05-01

## Goal

Broaden pure-unit coverage for review batch-budgeting behavior without changing
REST, MCP, or model behavior.

## Problem

Review batch retrieval now has a focused helper module:
`pubtator_link/services/review_context/batch_budgeting.py`. Current tests cover
duplicate passage drops, but the higher-risk behavior is broader:

- `source_fair` source representation.
- `scarcity_first` ordering by source coverage.
- response character budget drops.
- diagnostics-only response mode.
- source budget summary accounting.

These paths should be locked before future retrieval tuning.

## Non-Goals

- Do not change batch-budgeting algorithms.
- Do not change request defaults.
- Do not change response schemas.
- Do not introduce database or network requirements.
- Do not test through FastAPI or MCP for these pure helper cases.

## Proposed Design

Expand `tests/unit/test_review_context_batch_budgeting.py` with focused helper
tests around `merge_batch_context()`.

Test fixtures should remain small:

- `_passage(...)` creates `ContextPassage`.
- `_result(...)` creates `RetrieveReviewContextResponse`.
- helper arguments set only fields relevant to each scenario.

Add tests for:

1. `source_fair` includes first-pass representation from multiple sources
   before overflow.
2. `scarcity_first` prioritizes sources with scarcer coverage according to
   `SOURCE_COVERAGE_SCARCITY_PRIORITY`.
3. duplicate passage drops continue to include the duplicate passage ID.
4. `response_char_budget_exceeded` drops passages when estimated JSON response
   size exceeds `max_response_chars`.
5. diagnostics mode returns no merged passages but still produces per-query
   summaries.
6. source budget summaries count candidates, returned passages, dropped
   passages, and `first_pass_eligible`.

## Public Contract

`merge_batch_context()` should continue to return:

- `passages`
- `dropped`
- `query_summaries`
- `source_budget_summaries`
- `text_chars`
- `estimated_tokens`
- `budget_text_chars`

Drop reasons should remain stable:

- `duplicate_passage`
- `max_total_passages_exceeded`
- `char_budget_exceeded`
- `response_char_budget_exceeded`
- `source_budget_exceeded`

## Testing

Focused command:

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py -q
```

Completion gate:

```bash
make ci-local
make test-cov
```

## Rollout

1. Add one failing test for `source_fair`.
2. Implement only fixture/test adjustments needed; production behavior should
   already pass.
3. Add one failing test for `scarcity_first`.
4. Add response budget and diagnostics mode tests.
5. Add source budget summary accounting tests.
6. Run focused tests and full gates.

## Risks And Mitigations

Risk: tests duplicate implementation details too closely.

Mitigation: assert observable merged output, drop reasons, and summary counts
instead of private loop state.

Risk: character budget tests become brittle because `context_budget()` includes
JSON overhead estimates.

Mitigation: choose very small `max_response_chars` values so the expected drop
is unambiguous.
