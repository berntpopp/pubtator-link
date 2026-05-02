# LLM MCP Driver Ergonomics V2 Design

Date: 2026-05-02

## Purpose

Make PubTator-Link easier and safer for an LLM to drive during strict-citation
biomedical review workflows.

The preceding reliability slice fixed two active blockers:

- `retrieve_review_context_batch` no longer declares `results` as required when
  compact response serialization intentionally omits empty `results`.
- `index_review_evidence` accepts legacy `prepare_mode="selected"` while hiding
  the deprecated field from the public tool schema.

This design covers the remaining ergonomics work: discovery, recovery,
passage-level quote support, grounding confidence, progress reporting, preflight
coverage expectation, dropped-passage guidance, and copy-ready audit output.

## External Guidance

The design follows current MCP and FastMCP guidance:

- MCP client guidance recommends progressive tool discovery when full tool
  definitions consume meaningful context. It also recommends a layered catalog,
  inspect, execute pattern rather than forcing every full schema into prompt
  context up front.
- MCP tool definitions are discovered through `tools/list`, include unique names
  and JSON Schema input definitions, and report execution failures separately
  from protocol failures.
- MCP design principles prefer convergence, composability, graceful degradation,
  and stability over narrowly optimized new protocol concepts.
- FastMCP supports explicit output schemas, advisory tool annotations, component
  visibility, hidden parameters, and `Context.report_progress()` for long-running
  operations.

References:

- `https://modelcontextprotocol.io/docs/develop/clients/client-best-practices`
- `https://modelcontextprotocol.io/specification/2024-11-05/server/tools`
- `https://modelcontextprotocol.io/community/design-principles`
- `https://gofastmcp.com/servers/tools`
- `https://gofastmcp.com/v2/servers/progress`

## Goals

- Preserve the progressive-discovery-friendly tool surface while reducing the
  model's tool-selection friction.
- Make failed, empty, and over-budget retrievals self-correcting without requiring
  the model to inspect nested diagnostics by hand.
- Add citation-ready quote metadata so strict reports can quote snippets without
  recounting offsets.
- Add transparent passage-level grounding confidence that explains relevance
  without pretending to be clinical certainty.
- Add lightweight indexing progress notifications for wait-mode calls.
- Make source preflight distinguish weak guesses from likely post-index coverage.
- Make dropped-passage summaries recommend narrower section, PMID, and budget
  adjustments.
- Add a thin copy-ready audit-trail helper for the exact passages used in an
  answer.

## Non-Goals

- No backend LLM for query rewriting, reranking, or confidence scoring.
- No clinical decision support, diagnosis, treatment, triage, or patient
  management behavior.
- No destructive public MCP cache or database tools.
- No breaking rename of canonical `pubtator.*` tools.
- No forced eager-loading behavior in clients. The server can expose better
  driver contracts; it cannot control host-side deferred-tool policy.
- No new mega-tool that duplicates search, index, inspect, retrieve, and audit in
  one opaque call.

## Current State

Solved:

- Core review workflow tools exist and are registered.
- Capabilities and workflow help already advertise canonical workflows.
- Retrieval responses include stable passage IDs, stable citation keys, dropped
  candidates, budgets, query summaries, source budget summaries, and snapshot
  dates.
- `ContextPassage` already carries `start_char`, `end_char`, `truncated`, and
  `tail_preview`.
- Batch retrieval records audit events with the passage IDs returned.
- Exact passage lookup and full audit-bundle export tools already exist.
- Preflight already checks PMCID conversion, PMC BioC, optional Europe PMC, and
  PubTator abstract fallback.

Remaining gaps:

- `pubtator.get_server_capabilities` is helpful but not a compact inspectable
  driver contract for the core workflow. It lists tools and examples but does not
  expose a first-class core-tool schema bundle or detail levels.
- Recovery hints are nested in diagnostics and query summaries. A model must know
  where to look and manually translate them into next calls.
- There is no explicit `quote` object with returned-text and original-passage
  offset semantics.
- `PassageScore` exists but no single `confidence_for_grounding` object explains
  whether a passage is strong enough to cite for an answer.
- `index_review_evidence(wait_until_ready=True)` does not report MCP progress.
- `preflight_review_sources` still returns `expected_coverage="unknown"` in cases
  where a weaker but useful `expected_coverage_after_index` signal could help
  corpus selection.
- `dropped_summary` is currently a count-oriented stub for many over-budget
  paths; it does not suggest filters.
- The existing audit bundle is comprehensive but heavy. There is no thin helper
  that returns a copy-ready block for selected passage IDs.

## Design Principles

1. **Driver contract over eager loading.** Keep progressive discovery viable.
   Improve `get_server_capabilities` and `workflow_help` so a model can identify
   the canonical workflow in one compact call and inspect only the core schemas it
   needs.
2. **Top-level recovery, nested evidence.** Recovery should be visible at the
   response top level for empty or degraded outcomes. Detailed diagnostics remain
   nested for audit and debugging.
3. **Transparent confidence only.** Grounding confidence must be a deterministic
   relevance/auditability signal derived from retrieval facts. It is not medical
   certainty and must not be named or documented as such.
4. **Offsets must declare their basis.** Returned snippets may be truncated
   windows. Quote offsets must say whether they refer to returned text or original
   passage text.
5. **Progress is additive.** Progress notifications should help long-running
   wait-mode indexing without changing polling-based clients.
6. **Prefer small typed helpers over new broad tools.** Add one thin audit-trail
   helper because it removes repeated manual assembly. Do not add broad workflow
   orchestration.

## Public Surface

### Driver Contract

Extend `pubtator.get_server_capabilities` and `pubtator://capabilities` with a
new `llm_driver_contract` object:

```json
{
  "version": "2026-05-02",
  "recommended_entrypoint": "pubtator.workflow_help",
  "discovery_policy": {
    "strategy": "progressive_discovery",
    "rationale": "Full tool schemas are large; inspect core workflow tools as needed."
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
    "pubtator.get_review_audit_trail"
  ],
  "detail_levels": ["catalog", "schemas", "examples"],
  "schema_bundle": {
    "pubtator.index_review_evidence": {
      "input_schema": {},
      "output_schema": {}
    }
  },
  "response_contracts": {
    "recovery": "Top-level recovery hints appear when calls return no passages, degraded evidence, or major dropped-passage pressure.",
    "quote": "Context passages include optional quote offsets for returned text and original passage text.",
    "confidence_for_grounding": "Deterministic retrieval confidence for source grounding, not clinical certainty."
  }
}
```

The schema bundle should include only the core workflow by default. Avoid
embedding every advanced/admin schema in the capabilities payload.

### Top-Level Recovery

Add a shared model:

```json
{
  "reason": "all_candidates_over_budget",
  "message": "Candidates matched but were excluded by response budget.",
  "next_steps": ["increase_budget", "filter_sections", "filter_pmids"],
  "suggested_queries": ["mefv colchicine response"],
  "suggested_filters": {
    "sections": ["abstract", "results", "discussion"],
    "pmids": ["40234174", "26802180"]
  },
  "budget_advice": {
    "increase_max_chars_to": 18000,
    "increase_max_response_chars_to": 36000,
    "lower_max_passages_per_query_to": 4
  }
}
```

Add `recovery: RecoveryHint | None` to:

- `RetrieveReviewContextResponse`
- `RetrieveReviewContextBatchResponse`
- `ContextPack` when the recovery applies only to a merged pack

Rules:

- Populate top-level recovery when no passages are returned.
- Populate top-level recovery when dropped passages are at least three times the
  returned count and at least three passages were dropped.
- Preserve existing diagnostics fields for compatibility.
- Recovery must be deterministic and bounded. No unbounded PMID lists or raw
  passage text.

### Quote Metadata

Add:

```json
{
  "text": "returned quote text",
  "returned_start_offset": 0,
  "returned_end_offset": 120,
  "passage_start_char": 305,
  "passage_end_char": 425,
  "offset_basis": "returned_text_and_original_passage"
}
```

to `ContextPassage.quote`.

Semantics:

- `text` is a citation-safe excerpt from the returned `ContextPassage.text`, not
  raw upstream full text.
- `returned_start_offset` and `returned_end_offset` are offsets into the returned
  `ContextPassage.text`.
- `passage_start_char` and `passage_end_char` are offsets into the stored
  original review passage text.
- Quote text should default to the first sentence-like span or a compact window
  around the query token match, capped by a fixed character limit.
- The existing `start_char` and `end_char` remain the returned window bounds for
  the entire returned passage.

### Grounding Confidence

Add `confidence_for_grounding` to `ContextPassage`:

```json
{
  "level": "high",
  "score": 0.84,
  "factors": {
    "lexical_match": 0.9,
    "section_weight": 0.8,
    "entity_overlap": 1.0,
    "coverage_weight": 1.0,
    "truncation_penalty": 0.0
  },
  "match_mode": "strict_and_relaxed",
  "explanation": "High lexical match in abstract/results full-text passage with entity overlap."
}
```

Allowed levels:

- `high`
- `moderate`
- `low`
- `unknown`

The score must be deterministic and derived from existing fields where possible:

- `PassageScore.final_rank` and lexical rank,
- section boost,
- entity overlap,
- PMID filter boost,
- source coverage/tier,
- truncation status,
- strict/relaxed match mode from diagnostics.

Do not use this field for clinical evidence certainty. Keep existing
`add_evidence_certainty` as the user-supplied GRADE-style judgment path.

### Indexing Progress

For `pubtator.index_review_evidence`, use FastMCP `Context.report_progress()` when
`ctx` is present and the caller sets `wait_until_ready=True`.

Emit bounded stages:

- after enqueue/deduplication,
- while waiting for queued/running counts to change,
- when the requested wait condition is reached,
- when timeout occurs.

The response shape remains unchanged except for optional progress metadata if a
small response-level `progress_summary` is useful for clients that do not display
notifications.

### Preflight Expected Coverage After Index

Extend `SourceCoverageHint` with:

```json
{
  "expected_coverage_after_index": "abstract_only",
  "expected_coverage_confidence": "moderate",
  "coverage_resolution_stage": "preflight_resolver_chain"
}
```

Semantics:

- `expected_coverage` remains the immediate preflight result for backward
  compatibility.
- `expected_coverage_after_index` is the best deterministic expectation after the
  indexer tries its configured resolver chain.
- Confidence values are `high`, `moderate`, `low`, `unknown`.
- For `pmc_not_open_access`, check configured fallback resolvers before returning
  `unknown` when cheap probes are available.
- If no resolver evidence is available, keep `unknown` and explain the reason in
  notes and resolver attempts.

### Dropped-Passage Guidance

Replace the count-only `dropped_summary` shape with a typed or documented object
that remains JSON-compatible:

```json
{
  "total_dropped": 12,
  "visible_dropped": 10,
  "truncated_count": 2,
  "by_reason": {
    "char_budget_exceeded": 8,
    "duplicate_passage": 4
  },
  "suggested_filters": {
    "sections": ["abstract", "results", "discussion"],
    "pmids": ["40234174", "26802180"]
  },
  "budget_advice": {
    "increase_max_chars_to": 18000,
    "increase_max_response_chars_to": 36000
  }
}
```

Guidance should be derived from dropped and returned candidate metadata:

- Prefer sections with high returned-or-candidate density.
- Prefer PMIDs with many candidate passages and low returned count.
- Suggest increasing budgets only when dropped reasons are budget-related.
- Keep all lists short and stable.

### Thin Audit Trail Helper

Add `pubtator.get_review_audit_trail`:

Input:

```json
{
  "review_id": "fmf-colchicine-guidelines",
  "passage_ids": ["PMID:40234174:abstract:0"],
  "session_id": null,
  "max_chars_per_passage": 500,
  "format": "structured"
}
```

Output:

```json
{
  "success": true,
  "review_id": "fmf-colchicine-guidelines",
  "session_id": null,
  "items": [
    {
      "pmid": "40234174",
      "pmcid": "PMC...",
      "passage_id": "PMID:40234174:abstract:0",
      "stable_citation_key": "c_abc123",
      "section": "abstract",
      "quote": "First compact excerpt...",
      "char_count": 320
    }
  ],
  "not_found": [],
  "audit_block": "- c_abc123 PMID 40234174 PMID:40234174:abstract:0 abstract: First compact excerpt..."
}
```

This helper should reuse existing review passage lookup logic. It should not
duplicate the full audit bundle service and should not call upstream APIs.

## Architecture

### Models

Modify `pubtator_link/models/review_rerag.py`:

- add `RecoveryHint`, `RecoverySuggestedFilters`, and optional budget advice
  models,
- add `PassageQuote`,
- add `GroundingConfidence`,
- add `progress_summary` only if implementation needs a persisted response hint,
- add `ReviewAuditTrailItem` and `ReviewAuditTrailResponse`,
- extend `SourceCoverageHint`,
- extend retrieval responses with `recovery`.

Keep all additions backward-compatible and optional except for the new
audit-trail response model.

### Retrieval Services

Modify `pubtator_link/services/review_context/packing.py`:

- create quote metadata from the same excerpt window used to build
  `ContextPassage.text`,
- preserve original-passage offsets,
- compute passage confidence from deterministic ranking/coverage factors.

Modify `pubtator_link/services/review_context/diagnostics.py`:

- centralize recovery-hint construction for single-query and batch-query paths,
- promote selected nested diagnostics into top-level recovery without removing
  existing fields.

Modify `pubtator_link/services/review_context/batch_budgeting.py`:

- build structured dropped summaries,
- compute section and PMID filter suggestions,
- compute bounded budget advice.

Modify `pubtator_link/services/review_context_service.py`:

- attach recovery to single and batch responses,
- add a thin audit-trail service method using `get_passages_by_id`,
- keep existing audit-bundle export unchanged.

### Source Preflight

Modify `pubtator_link/services/source_preflight.py`:

- compute `expected_coverage_after_index`,
- attach confidence and resolution stage,
- reduce avoidable `unknown` outcomes where existing resolver probes provide a
  deterministic abstract/full-text expectation.

### MCP Tools

Modify `pubtator_link/mcp/tools/review.py`:

- report progress for wait-mode indexing with `ctx.report_progress()`,
- register `pubtator.get_review_audit_trail`,
- add output schema for the new audit-trail response.

Modify `pubtator_link/mcp/service_adapters.py`:

- add `get_review_audit_trail_impl`,
- preserve flat top-level arguments,
- keep resolver traces hidden by default.

Modify `pubtator_link/mcp/resources.py` and
`pubtator_link/services/workflow_help.py`:

- expose `llm_driver_contract`,
- document recovery, quote, confidence, dropped-summary, and audit-trail fields,
- keep deprecated `prepare_mode` guidance.

### REST Routes

If useful for parity, add a REST endpoint:

```text
POST /api/reviews/{review_id}/audit-trail
```

This is optional for the implementation plan. MCP support is the primary
requirement.

## Testing Strategy

Use TDD task by task.

Unit tests:

- model serialization for optional recovery, quote, confidence, and audit-trail
  models,
- context-packing quote offsets for truncated and non-truncated passages,
- grounding confidence factor calculation,
- recovery promotion for zero-result and over-budget retrieval,
- dropped-summary suggestions by section and PMID,
- source preflight `expected_coverage_after_index`,
- audit-trail service behavior with found and missing passage IDs,
- MCP facade registration and output schemas,
- capabilities/workflow-help documentation of the driver contract.

Integration/route tests:

- MCP HTTP protocol smoke for the new audit-trail tool if the existing test
  harness supports it,
- optional REST audit-trail route if added.

Verification:

- focused `uv run pytest ... -q` per task,
- `make format`,
- `make lint`,
- `make typecheck`,
- `make test`,
- final `make ci-local`.

## Documentation

Update:

- `docs/MCP_CONNECTION_GUIDE.md`,
- `docs/2026-05-02-pubtator-link-observability-implementation-guide.md`,
- `docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md`.

The docs should state which of the original ten evaluation recommendations are
implemented, partially implemented, or intentionally not implemented.

## Rollout And Compatibility

- All new response fields are additive.
- Existing consumers can ignore `recovery`, `quote`, `confidence_for_grounding`,
  and enhanced `dropped_summary`.
- `prepare_mode` remains hidden from the schema and accepted only for legacy
  compatibility while the FastMCP shim exists.
- New audit-trail tool is read-only and non-destructive.
- Progress notifications are best-effort. Clients that ignore MCP progress still
  receive normal tool responses.

## Acceptance Criteria

- `retrieve_review_context_batch` remains schema-valid in compact mode.
- `index_review_evidence` still accepts legacy `prepare_mode="selected"` without
  exposing it in public schemas.
- Capabilities expose a compact `llm_driver_contract` with core workflow schema
  detail.
- Empty and high-drop retrievals include top-level `recovery`.
- Returned passages include optional `quote` and `confidence_for_grounding`.
- Batch dropped summaries include reason counts and bounded filter/budget advice.
- Preflight responses include `expected_coverage_after_index` and confidence.
- Wait-mode indexing emits progress when `ctx` is available.
- `pubtator.get_review_audit_trail` returns selected passage audit items and a
  copy-ready audit block.
- Public docs map all ten evaluation recommendations to implementation status.
- `make ci-local` passes before completion.
