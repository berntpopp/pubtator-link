# MCP Error Telemetry and Quote Controls Design

## Goal

Make `pubtator.diagnostics` truthful across multi-worker deployments and give
LLM consumers explicit controls for substantive quote-mode evidence retrieval.

## Scope

This design covers two follow-up areas:

1. Cross-worker MCP error telemetry for recent tool failures.
2. Quote-mode retrieval controls for filtering short or non-claim evidence.

This design does not add embedding reranking, `coverage="evidence_only"` search
filtering, `inspect_review_index` claim-density statistics, or response-mode
capability documentation. Those remain separate follow-ups.

## Current State

MCP tool errors are recorded in `_RECENT_MCP_ERRORS`, an in-process Python list in
`pubtator_link/mcp/errors.py`. `DiagnosticsService` reads that list directly. In
a multi-worker deployment, a failed tool call and a later diagnostics call can
land on different workers, so `recent_mcp_errors.count` can be `0` even though a
workflow-breaking MCP error just happened.

Quote-mode retrieval currently has deterministic claim-density ranking, but the
caller cannot require substantive quotes. It can still return short quotes or
background sentences if they survive candidate selection and budgets. Existing
compact mode should remain broad context; quote mode is the right surface for
strict citable-evidence controls.

## Design Summary

Use Postgres-backed telemetry whenever the review database is configured and
reachable. Keep the current in-memory ring buffer as a fallback for local,
database-free operation and for failures while writing telemetry. Diagnostics
will merge persisted and in-memory entries, deduplicate by stable fields, and
return the latest bounded set.

Add quote-focused retrieval controls to `RetrieveReviewContextBatchRequest`:

- `min_quote_chars: int | None = None`
- `require_claim_indicator: bool = False`
- `claim_density_mode: Literal["off", "prefer", "require"] = "prefer"`

Strict filtering applies only when `response_mode="quotes"`. Compact and full
responses keep their broader context behavior.

## Error Telemetry

### Data Model

Add a migration-managed table:

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

All text fields remain bounded before insertion:

- `tool_name`: 200 chars
- `error_code`: 100 chars
- `message`: sanitized and 500 chars
- `raw_message`: sanitized only for storage safety and 500 chars
- `request_id`: 100 chars or null
- `worker_id`: 100 chars or null

No request arguments, PMIDs, full passage text, or user questions are stored in
this table.

### Write Path

`record_mcp_error()` keeps its public API but delegates to a telemetry helper.
The helper:

1. Always records to the existing in-memory ring buffer.
2. If the review database is configured, schedules or performs a best-effort
   Postgres insert.
3. Never raises back into the tool failure path if telemetry persistence fails.

The implementation should avoid creating a hard dependency from import-time MCP
error helpers to FastAPI dependency wiring. A small repository/helper module can
take a database URL or pool provider and degrade cleanly when unavailable.

### Read Path

`DiagnosticsService.get_diagnostics()` reads recent MCP errors from Postgres when
available, then merges in the in-memory fallback. It returns the same public
shape:

```json
{
  "recent_mcp_errors": {
    "count": 2,
    "latest": [
      {
        "timestamp": "...",
        "tool_name": "pubtator.retrieve_review_context_batch",
        "error_code": "output_validation_failed",
        "message": "The tool response did not match its declared MCP output schema.",
        "raw_message": "Output validation error: 'explanation' is a required property"
      }
    ]
  }
}
```

Diagnostics status becomes `degraded` when recent persisted review/MCP retrieval
errors exist, matching the current in-memory behavior.

### Retention

Reads are bounded to the latest 10 entries by default. A cleanup helper should
delete entries older than 7 days or keep the latest 500 rows, whichever preserves
more recent troubleshooting signal. Cleanup can run opportunistically after
writes; it must be best-effort and never block tool error responses.

## Quote Controls

### Request Fields

Add fields to `RetrieveReviewContextBatchRequest`:

```python
min_quote_chars: int | None = Field(default=None, ge=20, le=350)
require_claim_indicator: bool = False
claim_density_mode: Literal["off", "prefer", "require"] = "prefer"
```

Expose the same fields through:

- MCP tool signature for `pubtator.retrieve_review_context_batch`
- `retrieve_review_context_batch_impl`
- MCP input normalization for enum casing
- REST route request body automatically through the Pydantic model

### Claim Indicator

A quote has a claim indicator when its quote text or passage text contains at
least one deterministic signal:

- recommendation/guideline terms: `recommend`, `guideline`, `should`, `must`
- treatment/action terms: `therapy`, `treatment`, `dose`, `started`, `adjusted`
- comparison/effect terms: `compared`, `versus`, `higher`, `lower`, `increased`,
  `decreased`, `associated`, `response`, `remission`
- quantitative/statistical terms: digits, `%`, `p=`, `p <`, `CI`, `OR`, `HR`,
  `RR`

The signal is not a clinical truth judgment. It is a deterministic filter for
substantive evidence-like language.

### Filtering Behavior

Filtering applies only in `response_mode="quotes"`:

- `claim_density_mode="off"`: do not boost or filter by claim density.
- `claim_density_mode="prefer"`: preserve current claim-density ranking boost.
- `claim_density_mode="require"`: drop quotes without a claim indicator.
- `require_claim_indicator=True`: equivalent to strict claim filtering even if
  `claim_density_mode` is `"prefer"`.
- `min_quote_chars=N`: drop quotes shorter than `N` after quote extraction.

Dropped quotes should be counted in existing `dropped` and `dropped_summary`
structures with stable reasons:

- `quote_below_min_chars`
- `claim_indicator_required`

If all candidates are dropped by these filters, the response should not fail.
It should return an empty `quotes` list, diagnostics/dropped summary, and a
recovery hint suggesting lower `min_quote_chars`, `claim_density_mode="prefer"`,
or broader sections/query terms.

### Response Shape

No new top-level response array is introduced. Quote mode remains:

- `quotes[]` is canonical evidence text.
- `merged_context_pack.passages` remains empty.
- `merged_context_pack.stable_citation_map` maps quote stable keys to passage
  IDs.
- `dropped_summary` explains strict quote filtering when applicable.

## Error Handling

Telemetry write failures are intentionally swallowed after logging at debug or
warning level. A broken telemetry table must not make all MCP tools fail.

Quote filters must be transparent. Strict filters produce structured dropped
reasons and recovery guidance rather than generic validation errors.

Invalid request values are Pydantic or MCP normalization errors:

- `min_quote_chars < 20` or `> 350` is invalid.
- `claim_density_mode` accepts only `off`, `prefer`, or `require`.

## Testing Strategy

Use TDD for each behavior:

- Repository tests for inserting and reading `mcp_tool_errors`.
- Diagnostics tests proving persisted errors are visible without relying on
  in-memory state.
- Fallback tests proving diagnostics still works when telemetry persistence is
  unavailable.
- Model and MCP schema tests for new quote-control fields.
- Batch budgeting tests proving strict quote filters drop short or non-claim
  quotes with stable reasons.
- Service tests proving all-dropped quote responses include recovery guidance.
- Existing `make ci-local` remains the required final gate.

## Rollout

The default behavior remains backward compatible:

- Error telemetry becomes more reliable but keeps the same diagnostics JSON
  shape.
- Quote retrieval defaults to `claim_density_mode="prefer"`, matching the current
  heuristic boost.
- Strict quote filtering is opt-in.

Docker smoke after implementation should verify:

1. A forced MCP tool error appears in `pubtator.diagnostics` after a separate MCP
   call.
2. `retrieve_review_context_batch(response_mode="quotes",
   require_claim_indicator=True)` returns only claim-indicator quotes or explains
   why none were returned.
