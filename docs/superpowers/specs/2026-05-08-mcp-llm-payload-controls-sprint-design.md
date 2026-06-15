# MCP LLM Payload Controls Sprint Design

## Purpose

This spec defines the first sprint for MCP-facing payload controls in PubTator-Link. The sprint implemented the top three priorities from `docs/superpowers/plans/2026-05-08-mcp-llm-performance-maintainability-consolidation.md`:

1. Make literature graph MCP tools compact-first and budgeted.
2. Add compact pagination to `inspect_review_index`.
3. Add auto budgets and verbosity controls for `retrieve_review_context_batch` and `ground_question`.

Implementation status: shipped in commit `974cf47` (`feat: implement mcp payload controls sprint`) with documentation archived in commit `f5fe75c`.

Post-sprint update: optional embedding rerank was later rebased and merged to `main`
in commit `eb3c47d`. Dense rerank is no longer a future implementation item;
it is now an optional, disabled-by-default feature that still needs stabilization
and evaluation work after the remaining payload and trust gaps.

Fresh verification after implementation:

- `make format`
- `make lint`
- `make typecheck`
- `make ci-local`

Result after the dense-rerank merge: `make ci-local` passed with 999 tests
passing and 2 skipped integration database tests.

## Best-Practice Basis

The design follows current primary-source guidance:

- MCP pagination uses opaque cursor tokens, optional `nextCursor`, stable cursors, and graceful invalid-cursor handling. Source: [MCP Pagination](https://modelcontextprotocol.io/specification/draft/server/utilities/pagination).
- MCP tools are model-controlled and can return structured content; output schemas help clients and LLMs validate and parse results. Source: [MCP Tools spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).
- Large tool definitions and intermediate tool results consume context, increase latency, and degrade model performance; clients and servers should minimize loaded tool/result context. Source: [MCP client best practices](https://modelcontextprotocol.io/docs/develop/clients/client-best-practices).
- Function/tool definitions and tool outputs count against model context; strict schemas and small, clear tool surfaces improve reliability. Source: [OpenAI function calling guide](https://developers.openai.com/api/docs/guides/function-calling).
- Prompt caching depends on exact repeated prefixes, including identical tools and static content. Deterministic shapes and cache keys help downstream clients reason about reuse. Source: [OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).
- Tool use adds input and result tokens. Source: [Anthropic tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview).

## Goals

- MCP graph tools default to compact LLM-friendly payloads while keeping full/detail modes available through explicit `response_mode="full"` or `response_mode="nodes_edges"`.
- Compact graph responses enforce response budgets, report truncation honestly, include deterministic request signatures, and hide or explain empty `nodes` / `edges`.
- DOI-only unresolved graph entries collapse into counts in compact mode.
- `inspect_review_index` supports compact pagination with `limit`, `cursor`, `next_cursor`, global totals, page counts, omission counts, and recovery hints.
- `retrieve_review_context_batch` and `ground_question` accept `verbosity` and `max_response_chars="auto"` through a shared budget resolver.
- Explicit numeric budgets continue to work unchanged.
- Tests cover MCP adapters, service behavior, route behavior where applicable, and backward compatibility.

## Non-Goals

- Dense reranker implementation as part of the first payload-controls sprint. It was merged
  later as optional post-sprint work.
- Error telemetry and quote controls beyond payload warnings already needed for this sprint.
- Workflow-state/session model changes.
- Streaming progress.
- Public hosted destructive cache operations.
- Changing graph tools from candidate-selection helpers into claim-grounding tools.

## Next Sprint Priority

The next sprint should stay aligned with the consolidation plan, but the priority order changes now that compact defaults, graph budgets, inspect pagination, auto review budgets, and optional dense rerank have shipped.

### P0: Batch PubMed Metadata Internally

This is the recommended next sprint. It is the only remaining P0 payload/latency item from the consolidation plan and it directly protects the just-shipped compact workflows from large-list failures.

Scope:

- Keep public `PublicationMetadataRequest.pmids` capped at 100 for API ergonomics.
- Add an internal metadata batching helper that accepts larger PMID lists, chunks them into PubMed-sized requests, preserves input order, deduplicates IDs, merges partial failures, and reports provider warnings.
- Use the helper at internal call sites that can naturally exceed 100 PMIDs:
  - review index metadata attachment
  - related-evidence candidate enrichment
  - citation graph enrichment where list size can grow
  - MCP adapter/service paths that currently risk forwarding oversized metadata requests
- Ensure one failed metadata batch does not drop successful batches.
- Preserve REST compatibility and existing explicit metadata request validation.

Acceptance criteria:

- `inspect_review_index(include_metadata=True)` works for indexes with more than 100 sources.
- Related evidence and graph compact responses do not degrade to bare PMIDs solely because candidate metadata exceeded a public request cap.
- Partial PubMed metadata failures surface as warnings, not all-or-nothing failures.
- Focused metadata, review-context, related-evidence, citation-graph, and MCP adapter tests pass.
- `make ci-local` passes before completion.

### P1: Trust, Retry, And Quote Semantics

After metadata batching, implement the trust/retry sprint. This is the next highest user-facing reliability risk because it affects how LLM clients recover from failures and cite evidence.

Scope:

- Persist sanitized MCP tool error telemetry with bounded retention.
- Keep in-memory error diagnostics as a fallback and merge persisted plus in-memory diagnostics.
- Correct MCP idempotence annotations for write-like review tools.
- Add quote controls for `response_mode="quotes"`:
  - `min_quote_chars`
  - `require_claim_indicator`
  - `claim_density_mode`
- Preserve exact quote offsets in returned quote payloads when source passages have offsets.
- Return recovery hints when strict quote filters drop all candidate quotes.

Acceptance criteria:

- Telemetry persistence never makes an original tool failure worse.
- Sanitized persisted errors do not include request args, passage text, full user questions, or database host details.
- Quote mode can return exact-offset auditable quotes without requiring a follow-up passage call when offsets are available.
- All-dropped quote responses explain how to recover.
- `make ci-local` passes before completion.

### P2: Dense Rerank Stabilization And Deterministic Retrieval Quality

Optional dense rerank is merged, disabled by default, and covered by diagnostics/fallback tests. After metadata batching and trust controls, stabilize retrieval quality by evaluating the merged dense path, tightening deterministic guardrails, and exposing clearer diagnostics rather than adding another retrieval architecture.

Scope:

- Centralize non-evidence section classification for ranking and packing.
- Add optional deterministic score breakdown diagnostics.
- Add bounded deterministic metadata/query expansion.
- Evaluate the merged dense rerank path with transcript-style review retrieval cases.
- Keep dense rerank disabled by default unless explicitly configured.
- Preserve lexical fallback when embeddings, pgvector, provider setup, or query embedding fails.

Acceptance criteria:

- Default CI passes without requiring Sentence Transformers model downloads.
- Non-evidence sections such as references and abbreviations cannot be promoted above evidence sections by ranking changes.
- Dense rerank diagnostics clearly report fallback reasons.
- Dense-rerank evaluation cases show whether the optional path improves or harms review retrieval quality before it is recommended for routine use.

## Current Post-Merge Findings For Next Sprint

- `PublicationMetadataRequest.pmids` remains capped at 100, which is correct for public REST/MCP ergonomics.
- `PublicationMetadataService` has only `get_metadata(request)`, so there is no shared internal helper for larger PMID lists.
- `ReviewContextService._attach_source_metadata()` can still forward all page source PMIDs in one capped request when `inspect_review_index(include_metadata=True)` is used.
- `TopicLiteratureMapService._metadata_papers()` still forwards `list(pmids)` directly to `PublicationMetadataRequest`.
- `RelatedEvidenceService._metadata_candidates()` already chunks PMIDs locally, but this is ad hoc and should be replaced by the shared helper.
- Citation graph source metadata calls are single-PMID today, but candidate enrichment or future graph expansions should use the same helper if they can exceed one public request.
- Persistent MCP error telemetry is not implemented as a database-backed service.
- Quote mode exists, but the planned strict quote controls (`min_quote_chars`, `require_claim_indicator`, and `claim_density_mode`) are not exposed as request fields.

## Historical Codebase Findings Before Sprint 1

### Graph Tools

- MCP graph adapters currently coerce omitted `response_mode` to `"full"`:
  - `get_publication_citation_graph_impl()` in `pubtator_link/mcp/service_adapters.py`.
  - `find_related_evidence_candidates_impl()` in `pubtator_link/mcp/service_adapters.py`.
  - `build_topic_literature_map_impl()` in `pubtator_link/mcp/service_adapters.py`.
- MCP tool signatures in `pubtator_link/mcp/tools/publications.py` expose `response_mode: LiteratureGraphResponseModeArg | None = None`, which enables the adapter full-mode fallback.
- REST/model defaults are not uniform:
  - `PublicationCitationGraphRequest.response_mode` defaults to `"full"`.
  - `TopicLiteratureMapRequest.response_mode` defaults to `"full"`.
  - `RelatedEvidenceCandidatesRequest.response_mode` defaults to `"compact"`.
- `LiteratureGraphResponseMeta` already models `truncated`, `omitted_counts`, `budget_advice`, `cache_key`, `snapshot_date`, `source_versions`, and `ranking_version`, but the graph services do not populate provenance/snapshot/version fields. This sprint adds `request_signature` as the canonical request provenance field and keeps `cache_key` as a backward-compatible alias where the existing model still exposes it.
- `pubtator_link/services/literature_graph_compact.py` defines `COMPACT_BUDGET_BYTES = 12 * 1024` and `NODES_EDGES_BUDGET_BYTES = 40 * 1024`, but these are used for response size classification rather than budget enforcement.
- Citation compact mode already empties full lanes, collapses DOI-only unresolved candidates to `omitted_counts["doi_only_unresolved"]`, and the citation response serializer omits empty `references`, `cited_by`, `metadata_only`, `nodes`, and `edges`.
- Topic compact mode empties `nodes` and `edges` but still serializes them as empty arrays. It can also expose DOI-only unresolved papers through compact summary paper arrays.
- Related evidence compact mode is mostly a metadata flag; it does not report max-result truncation through `_meta.truncated` or `_meta.omitted_counts`.

### `inspect_review_index`

- `InspectReviewIndexRequest` contains `session_id`, `pmids`, `response_mode`, sample controls, and metadata controls. It has no `limit` or `cursor`.
- `InspectReviewIndexResponse` contains `sources`, `failed_sources`, `totals`, `coverage_summary`, and `index_snapshot_date`. It has no pagination fields.
- Compact serialization already removes source `resolver_attempts`, `sample_passages`, `citation_metadata`, and `None` values.
- `ReviewContextService.inspect_review_index()` loads all sources and failed sources through repository methods.
- `PostgresReviewReragRepository.list_review_sources()` and `list_review_failed_sources()` order by `source_id` and return all matching rows.
- REST `GET /api/reviews/{review_id}/index` defaults `response_mode="full"`.
- MCP `inspect_review_index` defaults `response_mode="compact"`.

### Retrieval Budgets

- `retrieve_review_context_batch` already supports numeric `max_response_chars` and numeric budget auto-fit when the MCP adapter receives omitted budgets.
- Batch budget constants are duplicated in `pubtator_link/mcp/service_adapters.py` and `pubtator_link/services/review_context_service.py`.
- `RetrieveReviewContextBatchRequest.max_response_chars` is currently numeric with default `48000`.
- `ground_question` has no budget or verbosity arguments. It hard-codes downstream retrieval to `max_total_passages=8`, `max_response_chars=12000`, and `response_mode="compact"`.
- Review batch responses already report budget pressure through `ContextBudget`, `SourceDroppedSummary`, `RecoveryBudgetAdvice`, passage truncation flags, and `next_context_options`.

## Design Options Considered

### Option A: Compact-first only at MCP adapters

Only change MCP defaults while leaving service/model behavior intact. This is least risky for REST clients and direct service callers, but it does not enforce graph payload budgets or populate deterministic request signature metadata.

### Option B: Service-level compact contracts with MCP compact defaults

Change MCP defaults to compact and enforce compact response budgets in the services. REST defaults stay backward-compatible, while direct callers can explicitly opt into compact budgeted behavior. This is the recommended option.

### Option C: Global compact defaults across REST, models, and MCP

Change all graph request defaults to compact. This maximizes LLM friendliness but risks breaking REST callers and route tests that rely on full graph topology by omission.

## Public API And Input Changes

### Graph MCP Tools

MCP tool signatures change from nullable response mode to compact defaults:

- `get_publication_citation_graph(response_mode="compact")`
- `find_related_evidence_candidates(response_mode="compact")`
- `build_topic_literature_map(response_mode="compact")`

Explicit `response_mode="full"` and `response_mode="nodes_edges"` remain available.

REST graph routes keep existing request model defaults for this sprint:

- Citation graph REST remains full by omission.
- Topic map REST remains full by omission.
- Related evidence REST keeps its existing compact request default.

### `inspect_review_index`

Add request fields:

```python
limit: int | None = Field(default=None, ge=1, le=100)
cursor: str | None = None
```

Add response fields:

```python
next_cursor: str | None = None
page_source_count: int = 0
page_failed_source_count: int = 0
omitted_counts: dict[str, int] = Field(default_factory=dict)
```

MCP exposes flat `limit` and `cursor` arguments. MCP compact mode should default `limit=50` when omitted. REST exposes optional `limit` and `cursor` query parameters, but REST full mode remains unpaginated when `limit` is omitted.

When `next_cursor` is present, the MCP adapter adds `_meta.next_commands` with the next `inspect_review_index` call.

Pagination is best-effort under concurrent writes. The offset cursor is deterministic for a stable review index, but a source inserted or deleted while a client is paging can cause skipped or repeated rows. Clients that need monotonic inspection should restart pagination from the first page after indexing has settled.

### Review Retrieval And Grounding

Add shared types:

```python
ReviewResponseVerbosity = Literal["lean", "standard", "full"]
MaxResponseChars = int | Literal["auto"]
```

Add request/model or MCP fields:

- `RetrieveReviewContextBatchRequest.verbosity: ReviewResponseVerbosity = "standard"`
- `RetrieveReviewContextBatchRequest.max_response_chars: int | Literal["auto"] = 48000`
- `get_review_context_batch(verbosity="standard", max_response_chars="auto")`
- `ground_question(verbosity="lean", max_response_chars="auto")`

`response_mode` controls shape; `verbosity` controls budget. For example, `response_mode="compact"` with `verbosity="full"` still returns the compact-shaped response, but the auto response budget resolves to 60000 characters. This lets clients ask for a compact schema with fewer budget drops without switching to full per-query payloads.

The defaults intentionally differ: `ground_question` defaults to `verbosity="lean"` to preserve its current one-call 12000-character cost profile, while `retrieve_review_context_batch` defaults to `verbosity="standard"` because it is the explicit retrieval tool and currently defaults to larger review-context budgets.

Auto response budget mapping:

```python
{"lean": 12000, "standard": 24000, "full": 60000}
```

Explicit numeric `max_response_chars` remains valid in the existing `2000..100000` range. `"auto"` is case-insensitive at MCP boundaries; the normalizer canonicalizes `"Auto"` and `"AUTO"` to `"auto"` before budget resolution.

## Backward Compatibility

- No tool names are changed.
- No existing explicit `response_mode`, numeric budget, PMID, query, or review ID argument changes meaning.
- Graph full/detail behavior remains available by explicit opt-in.
- REST graph defaults remain stable.
- REST `inspect_review_index` remains full and unpaginated when `limit` is omitted.
- REST `retrieve_review_context_batch` keeps the existing numeric model default of `48000` when `max_response_chars` is omitted. REST callers opt into auto budgets by sending `"max_response_chars": "auto"`.
- `inspect_review_index` response fields are additive.
- Existing compact source serialization remains, with pagination fields added.
- `ground_question` default `verbosity="lean"` and `max_response_chars="auto"` resolves to the current hard-coded 12000 response budget.
- Existing numeric `retrieve_review_context_batch(max_response_chars=48000)` continues to produce a caller-provided 48000 budget.

## Payload Budget And Truncation Rules

### Graph Budgets

- Compact graph budget: 12 KiB serialized JSON.
- `nodes_edges` budget: 40 KiB serialized JSON.
- Full mode: no new sprint budget enforcement.
- Byte accounting uses deterministic wire-like JSON serialization with aliases and compact separators. Pydantic responses are counted through `model_dump_json(by_alias=True)`; plain mappings are counted only after `model_dump(mode="json")`-compatible conversion. The helper must not use `default=str`, because silent coercion hides serialization bugs.
- Truncation must happen in deterministic order and set:
  - `_meta.truncated = True`
  - `_meta.omitted_counts`
  - `_meta.budget_advice`

### Compact Graph Shape Rules

- Compact citation graph:
  - Hide `references`, `cited_by`, `metadata_only`, `nodes`, and `edges` when empty.
  - Collapse DOI-only unresolved references/citations into `unresolved_doi_count` and `_meta.omitted_counts["doi_only_unresolved"]`.
  - If optional candidate detail must be dropped, drop lowest-ranked candidate explanations before dropping candidate identifiers.
  - Prefer preserving `candidate_pmids`, `actionable_pmid_count`, `metadata_only_count`, and `compact_status`.
  - Include `_meta.next_commands` entries that reproduce the same request with `response_mode="full"` and `response_mode="nodes_edges"` so an LLM can drill down without reconstructing arguments.

- Compact topic map:
  - Omit empty `nodes` and `edges`.
  - Replace redundant summary paper arrays with counts and PMID lists when the same information is available in `top_candidates`, `recommended_next_pmids`, `accessible_full_text_pmids`, or `closed_central_pmids`.
  - Filter DOI-only unresolved papers out of compact summary arrays and count them in `omitted_counts["doi_only_unresolved"]`.
  - Drop demoted candidate detail before top candidate identifiers.
  - Include `_meta.next_commands` entries that reproduce the same request with `response_mode="full"` and `response_mode="nodes_edges"`.

- Compact related evidence:
  - Keep `normalized_neighbor_score` as the LLM-facing score.
  - Hide raw `score` / `pubmed_neighbor_score` in compact mode or annotate them with `score_units="pubmed_neighbor_raw_count"` and a warning that raw values are ranking internals.
  - Report result-limit truncation in `_meta.omitted_counts["candidates"]` when the service sees more candidates than it returns.
  - Include a `_meta.next_commands` entry that reproduces the same request with `response_mode="full"`.

Serialization-only pruning such as omitting empty compact arrays belongs in Pydantic response serializers. Content selection, truncation, and budget accounting remain service responsibilities.

### Review Retrieval Budgets

- `max_response_chars="auto"` resolves through the shared budget resolver.
- Explicit numeric budgets bypass auto mapping and are labeled caller-provided.
- Existing `SourceDroppedSummary`, `ContextBudget`, and `RecoveryBudgetAdvice` remain the response-level budget feedback mechanisms.
- Normalization warnings continue to use `_meta.normalized_arguments`.

## Pagination And Cursor Contract

`inspect_review_index` pagination uses an opaque base64url JSON cursor:

```json
{
  "v": 1,
  "scope_hash": "12-char-scope-hash",
  "source_offset": 50,
  "failed_source_offset": 50
}
```

Scope hash input:

```json
{
  "review_id": "...",
  "session_id": "...",
  "pmids": ["..."]
}
```

Rules:

- Clients must treat `cursor` as opaque.
- `scope_hash` uses a 12-hex-character SHA-256 prefix. That is 48 bits, which is sufficient for inspect-scope identity and keeps cursors short.
- The same `limit` applies to `sources` and `failed_sources`.
- `next_cursor` is returned when either list has more rows.
- `sources` and `failed_sources` are page-local.
- `totals`, `preparation_status`, and `coverage_summary` are global for the inspect scope.
- `page_source_count` and `page_failed_source_count` report page-local counts.
- `omitted_counts["sources"]` and `omitted_counts["failed_sources"]` report remaining rows outside the current page when a limit is active.
- Invalid cursor encoding, version, negative offsets, or scope hash mismatch raises a stable validation error with recovery guidance to restart pagination without `cursor`.
- When one side is exhausted, the service stops querying that side on later pages and advances only the side that still has remaining rows.

## Request Signature And Reproducibility Behavior

Graph services populate request provenance metadata for deterministic inputs:

```python
request_signature = stable_cache_key(
    "literature_graph",
    {"tool": tool_name, "request": request.model_dump(mode="json")},
)
```

Required `_meta` fields:

- `request_signature`: deterministic request provenance key.
- `cache_key`: backward-compatible alias with the same value while the existing graph meta model still exposes this field.
- `snapshot_date`: `corpus_snapshot_date()` for live upstream corpus snapshots.
- `source_versions`: at least the graph contract version and live provider names involved in the request.

The request signature is not a response replay key and does not guarantee that live upstream provider results are byte-identical forever. `snapshot_date` and `source_versions` make that limitation explicit.

## Test Strategy

### Graph Tests

- MCP adapter tests prove omitted graph response modes now become `"compact"` and no deprecation warning is emitted.
- MCP schema/catalog tests prove graph tool defaults are compact and full mode is documented as opt-in.
- Service tests prove compact graph responses populate `request_signature`, the compatibility `cache_key`, `snapshot_date`, `source_versions`, `_meta.next_commands`, and budget/truncation metadata.
- Citation graph tests cover DOI-only unresolved collapse and explicit full mode compatibility.
- Topic map tests cover omitted empty `nodes` / `edges`, compact summary DOI-only filtering, budget truncation, and request signature metadata.
- Related evidence tests cover compact score semantics and omitted candidate counts.
- Route tests pin REST graph defaults where they must remain full.

### `inspect_review_index` Tests

- Model/service tests cover `limit`, cursor round-trip, `next_cursor`, page-local counts, global totals, global coverage summary, and omission counts.
- Repository tests cover deterministic pagination order for sources and failed sources.
- MCP adapter tests cover flat `limit` / `cursor` wiring and `_meta.next_commands`.
- MCP schema tests cover optional pagination args.
- REST route tests cover optional query params and stable full-mode behavior when omitted.

### Retrieval Budget Tests

- New `tests/unit/test_review_context_budgets.py` covers auto mapping, explicit integer pass-through, range validation, invalid string validation, and budget source classification.
- MCP input normalization tests cover `verbosity` enum casing and case-insensitive `"auto"`.
- MCP adapter tests cover batch auto budgets, explicit numeric budgets, and `ground_question` lean/standard/full resolution.
- MCP schema tests cover new `verbosity` and `max_response_chars` union/defaults.
- Route/service tests cover REST batch acceptance of `"auto"` where the Pydantic request model is used.

### Final Verification

The implementation plan must require:

```bash
make ci-local
```

before claiming sprint completion.

## Rollout Risks

- MCP graph default changes may surprise clients relying on full arrays by omission. Mitigation: explicit `response_mode="full"` remains supported and REST defaults stay stable.
- Budget enforcement can hide useful candidate details. Mitigation: deterministic drop order, honest `omitted_counts`, `truncated`, and `budget_advice`.
- DOI-only collapse can hide unresolved identifiers. Mitigation: counts remain visible and compact responses explain unresolved DOI collapse.
- Cursor pagination can shift if the index changes during paging. Mitigation: scope hash validation, deterministic ordering, and recovery guidance to restart pagination.
- Request signatures can be misread as response replay keys if surfaced without context. Mitigation: name and document them as request provenance keys with live snapshot metadata, and keep `cache_key` only as a compatibility alias.
- Lower auto budgets may increase truncation. Mitigation: explicit numeric budgets continue to work and budget advice points callers to larger budgets or narrower filters.

## Self-Review

- Unresolved-marker scan: no incomplete requirements remain.
- Internal consistency: REST defaults are preserved where compatibility requires it; MCP defaults are compact-first where LLM payload economics require it.
- Scope check: the sprint is limited to graph payload controls, `inspect_review_index` pagination, and review retrieval budget controls.
- Ambiguity check: cursor format, budget mappings, compatibility boundaries, and test ownership are explicit.
