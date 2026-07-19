# MCP Payload Safety Grounding Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-03

## Purpose

Address the remaining high-priority gaps from the consolidated roadmap, the MCP
LLM speed/accuracy report, and the latest external reviewer feedback. The work
focuses on making PubTator-Link cheaper for LLMs to drive, safer for hosted
HTTP/MCP exposure, and more deterministic for tool-error recovery, while adding
one standard one-call grounding entry point.

## Goals

- Reduce default MCP response payload size without removing auditability from
  verbose or full modes.
- Make compact `search_literature` results cheaper by replacing full author
  arrays with a short author summary unless the caller opts into full metadata.
- Replace verbose `_meta.next_commands` argument blobs in default outputs with
  short next-tool hints and resource/workflow pointers.
- Add a minimum viable workflow snippet to `pubtator.diagnostics` so clients can
  bootstrap even when they miss server instructions.
- Add hosted HTTP/MCP safety controls: explicit CORS methods/headers, request
  size limits, and opt-in inbound rate limiting with stable error payloads.
- Replace string-inferred MCP error classification with typed service errors at
  the boundary where review schema, database, and upstream failures are raised.
- Add an additive one-call `pubtator.ground_question` workflow that chains
  search, index, inspect, and batch retrieval into a compact evidence pack.

## Non-Goals

- No clinical decision support or backend answer synthesis.
- No destructive cache or review-index delete surface.
- No broad tool renaming or migration to a single `pubtator.invoke(op=...)`
  surface.
- No OAuth 2.1, Dynamic Client Registration, OpenTelemetry, or full public
  deployment auth rollout in this slice.
- No semantic vector sidecar, hybrid retrieval reranker, or large ranking
  overhaul beyond the existing `ground_question` plan if implemented.
- No changes under `benchmarks/`.

## Current State

- Lean/full/readonly MCP profiles, runtime tool catalog generation, review
  resource templates, durable LLM review context, and `next_context_options`
  already exist.
- Compact review passage serialization already strips many null and diagnostic
  fields, and `search_literature` now defaults `include_citations` to `none`.
- `search_literature(metadata="basic")` can still merge full `authors` into
  compact results, creating avoidable token cost.
- Several `_meta.next_commands` payloads still include full argument blobs. This
  is useful for debugging but expensive for default LLM use.
- `pubtator.diagnostics` reports subsystem state and recovery messages, but it
  does not include the tiny canonical workflow sequence.
- `server_manager.py` still uses wildcard CORS methods and headers. There is no
  local HTTP/MCP request-size guard or inbound hosted rate limiter.
- `mcp/errors.py` still classifies some failures by matching raw exception
  strings and imports storage/transport exception types directly.
- `pubtator.review_quickstart` stages and inspects a review, but it does not
  return an evidence pack for a question in one call. The existing
  `docs/superpowers/specs/2026-05-03-mcp-ground-question-and-guideline-budget-design.md`
  already defines the desired additive `pubtator.ground_question` tool.

## Public Surface

### Compact Search Payloads

Add `first_author_et_al: str | None` to `SearchResult`.

For compact search responses:

- `authors` remains empty unless `metadata="full"` or `response_mode` is
  `standard`/`full`.
- `first_author_et_al` is populated from the first available author plus
  `et al.` when more authors are known.
- `citations` remains absent unless `include_citations` requests a format.
- Existing full metadata callers continue to receive the complete `authors`
  array.

### Lean Next-Step Metadata

Default MCP `_meta` should prefer short hints:

```json
{
  "next_tools": ["pubtator.preflight_review_sources", "pubtator.index_review_evidence"],
  "workflow": "search -> preflight -> index -> inspect -> retrieve",
  "details_resource": "pubtator://workflow-help"
}
```

Full argument blobs may remain available in explicit diagnostics/debug fields
or verbose modes, but they should not be included in compact/default responses
unless the response would be ambiguous without them.

### Diagnostics Workflow Snippet

`pubtator.diagnostics` adds a compact workflow block:

```json
{
  "minimum_workflow": {
    "grounded_review": [
      "pubtator.search_literature",
      "pubtator.preflight_review_sources",
      "pubtator.index_review_evidence",
      "pubtator.inspect_review_index",
      "pubtator.retrieve_review_context_batch"
    ],
    "one_call": "pubtator.ground_question",
    "workflow_resource": "pubtator://workflow-help"
  }
}
```

If `pubtator.ground_question` is not yet implemented, diagnostics should omit
`one_call` rather than advertise a missing tool.

### Hosted Safety Controls

Add configuration-backed controls that are permissive enough for local
development but safe by default for hosted HTTP mode:

- CORS methods and headers are explicit lists.
- POST request bodies over a configured byte limit return a stable 413 JSON
  error before route or MCP processing.
- Inbound rate limiting is disabled or high-limit for local development and can
  be enabled for hosted HTTP/MCP mode by environment variables.
- Rate-limit failures return a stable 429 JSON error with `error_code`,
  `retryable`, and `retry_after_seconds` when available.

### Typed Error Mapping

Introduce a focused typed-error module for MCP/review-facing failures:

- `PubTatorLinkError`
- `ReviewSchemaStaleError`
- `ReviewIndexUnavailableError`
- `UpstreamUnavailableError`
- `ValidationFailureError`

MCP error mapping should classify these with `isinstance`. String matching can
remain only as a temporary legacy fallback for unexpected third-party errors.

### `pubtator.ground_question`

Implement the existing `ground_question` design as the one additive workflow
tool. It should:

- Register in `lean` and `full`, not in `readonly`.
- Use write/review annotations because it indexes review evidence.
- Return a typed compact composite result with selected PMIDs, coverage or
  preparation summary, retrieved context, and recovery hints.
- Reuse existing search, index, inspect, and batch retrieval services.
- Prefer compact outputs and bounded default budgets.

The existing ground-question spec remains the detailed source for this tool's
arguments and response shape. If conflicts arise, this spec takes precedence on
profile visibility and payload compactness.

## Architecture

Keep each concern in the existing boundary that already owns it:

- Search shaping: `pubtator_link/services/search_shaping.py`.
- Response models: `pubtator_link/models/responses.py` and
  `pubtator_link/models/review_rerag.py`.
- MCP orchestration and metadata shaping:
  `pubtator_link/mcp/service_adapters.py`.
- MCP registration/profile visibility:
  `pubtator_link/mcp/tools/review.py` and `pubtator_link/mcp/profiles.py`.
- Diagnostics: `pubtator_link/services/diagnostics.py`.
- HTTP middleware/config: `pubtator_link/server_manager.py` and
  `pubtator_link/config.py`.
- Typed errors: a new focused module at `pubtator_link/services/errors.py`,
  then boundary conversions in MCP service adapters and review services.

Do not introduce a new orchestration framework. Reuse existing Makefile,
FastMCP, Pydantic, and service patterns.

## Data Flow

Compact search:

1. Raw PubTator search result enters `shaped_search_result`.
2. Authors are normalized once.
3. Compact mode stores only `first_author_et_al`.
4. Full modes and full metadata retain `authors`.

Ground question:

1. Search literature with compact metadata and optional guideline boost.
2. Select unique PMIDs.
3. Index evidence under a deterministic or supplied `review_id`.
4. Inspect readiness and coverage.
5. Retrieve compact batch context when passages are ready.
6. Return partial success with recovery hints if search finds no PMIDs or
   indexing has not produced passages yet.

Hosted safety:

1. Request size middleware rejects oversized POST bodies before expensive work.
2. Rate limiter checks hosted HTTP/MCP requests before route execution.
3. CORS middleware exposes only configured methods and headers.

## Error Handling

- Tool-level user-correctable failures should remain structured tool errors,
  not raw transport failures.
- Oversized request and rate-limit failures return stable JSON responses.
- Typed review/upstream failures map to stable MCP `error_code` values.
- Legacy string matching remains as a fallback only where the source exception
  has not yet been converted to a typed error.
- Partial `ground_question` states are successful responses with explicit
  recovery hints when no external exception occurred.

## Testing

Use TDD for each track:

- Search shaping tests for compact author summary and full-author opt-in.
- MCP adapter/facade tests for lean `_meta` next-step hints and diagnostics
  workflow snippet.
- Route/middleware tests for CORS methods/headers, request-size rejection, and
  rate-limit rejection.
- Unit tests for typed error mapping and backward-compatible MCP error payloads.
- Service adapter/facade tests for `pubtator.ground_question` profile
  visibility, output schema, partial states, and happy path.
- Focused tests per task, then `make ci-local`.

## Compatibility

- Existing `authors` arrays remain available in standard/full search modes and
  full metadata.
- Existing `_meta.next_commands` consumers should still have a migration path
  through verbose/debug fields or resources, but compact defaults become lean.
- Existing explicit workflow tools remain callable.
- Existing `review_quickstart` remains in `full`; it is not renamed.
- Hosted safety controls are configurable so local development and stdio usage
  remain easy.

## Rollout

Implement in small commits:

1. Payload slimming and diagnostics workflow.
2. Hosted HTTP/MCP safety controls.
3. Typed service errors and MCP mapping.
4. `pubtator.ground_question` integration.
5. Documentation/status updates and final verification.

Run `make ci-local` before claiming completion. Rebuild and restart Docker on
the existing configured ports after implementation if the user wants the hosted
server refreshed.
