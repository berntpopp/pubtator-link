# Research MCP Grounding Upgrade Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

## Purpose

Upgrade PubTator-Link from a useful biomedical MCP server into a more discoverable, context-safe research grounding server for LLM clients. The target is to raise the Claude Code user assessment toward 4/5 or better across discoverability, usability, speed, and understandability for publication-grounded literature work.

The server remains deterministic. It does not synthesize conclusions, make clinical recommendations, compute evidence certainty, or call an LLM. It should make it easy for an LLM or human reviewer to discover the right tools, inspect what evidence is indexed, retrieve compact citable passages, and avoid accidentally pulling multi-megabyte full-text payloads into context.

## Current Problems

The existing MCP surface works but has avoidable friction:

- Claude Code defers MCP tool schemas by default, so server instructions must tell the model when to search for PubTator-Link tools.
- The initial server instructions name PubTator-Link generally but do not list the major capabilities or the preferred research workflow.
- `fetch_publication_annotations(full=true)` can return very large BioC JSON payloads. This is useful for explicit full export, but it is a foot-gun for routine “give me abstracts/passages” workflows.
- Review RAG retrieval can return zero passages without telling the caller whether the review was not indexed, the PMID failed, the section filters were too narrow, or the query phrasing missed.
- There is no MCP tool for inspecting what is currently in a review index: PMIDs, sections, passage counts, failures, or source attempts.
- Query reformulation is serial. An LLM has to call retrieve repeatedly when it wants to try several keyword variants.

## External Guidance

Claude Code MCP behavior affects the design:

- Tool Search is enabled by default, so tool definitions are deferred and discovered on demand.
- Server instructions help Claude decide when to search for a server's tools.
- Claude Code truncates server instructions and tool descriptions at 2 KB, so critical guidance must appear early and stay concise.
- Claude Code warns or persists large MCP outputs; servers should paginate, filter, or expose compact tools for large data.
- MCP resources and prompts are useful secondary discovery surfaces, but model-controlled tools remain the reliable path for action.

Sources used:

- Claude Code MCP docs: `https://code.claude.com/docs/en/mcp`
- MCP schema/specification: `https://modelcontextprotocol.io/specification/2025-06-18/schema`
- Anthropic remote MCP best-practice guidance: `https://support.anthropic.com/en/articles/11596040-best-practices-for-building-remote-mcp-servers`

## Design Goals

1. Make the server self-advertising at session start.
2. Make compact publication grounding the default path, not full raw export.
3. Make review index state inspectable before and after retrieval.
4. Make zero-result retrieval responses actionable.
5. Support batched query variants to reduce serial trial-and-error.
6. Preserve existing tool contracts unless a new purpose-built tool is safer.
7. Keep research-use and clinical non-use limitations prominent.

## Non-Goals

- No backend LLM synthesis.
- No diagnosis, treatment, triage, patient management, or clinical decision support.
- No vector database or embedding dependency in this upgrade.
- No replacement of raw BioC export; full export remains available for callers that explicitly need it.
- No authorization model beyond the existing trusted single-tenant POC boundary.

## Proposed MCP Workflow

The server instructions should teach this default workflow:

1. Use `pubtator.search_literature` to find candidate PMIDs.
2. Use `pubtator.index_review_evidence` for a stable `review_id`.
3. Use `pubtator.inspect_review_index` to verify indexed PMIDs, sections, passage counts, and failures.
4. Use `pubtator.retrieve_review_context` or `pubtator.retrieve_review_context_batch` for compact citable passages.
5. Use `pubtator.get_publication_passages` for explicit compact section retrieval.
6. Use `pubtator.fetch_publication_annotations(full=true)` only when raw full BioC JSON is intentionally needed.

The first sentence of the MCP server instructions should be a capability map:

```text
PubTator-Link grounds biomedical literature work: search PubMed/PubTator, fetch compact passages or raw BioC, inspect review indexes, retrieve review-scoped RAG context, find entity relations, and submit/get text annotations.
```

The next sentences should instruct:

- For grounded answers, prefer `search -> index -> inspect -> retrieve`.
- For large full text, prefer compact passage tools before raw full export.
- If retrieval returns zero passages, inspect the review index and retry with shorter keyword queries or PMID filters.

## New Tool: `pubtator.get_publication_passages`

Purpose: Return compact, sectioned publication passages without forcing the LLM to parse raw BioC JSON.

Request fields:

- `pmids: list[str]` required, 1-25.
- `sections: list[str]` optional. Values are case-insensitive and normalized. Examples: `abstract`, `intro`, `methods`, `results`, `discussion`, `conclusion`, `table`.
- `mode: "abstracts" | "compact_passages" | "section_text"` default `compact_passages`.
- `full: bool` default `false`. When `true`, fetch full PubTator BioC before compacting.
- `max_passages_per_pmid: int` default 6, range 1-30.
- `max_chars: int` default 12000, range 1000-50000.
- `include_tables: bool` default `true`.
- `include_references: bool` default `false`.

Response fields:

- `success: true`
- `pmids: list[str]`
- `mode`
- `passages: list[PublicationPassage]`
- `dropped: list[PassageDropReason]`
- `context_estimate`

`PublicationPassage`:

- `passage_id`
- `pmid`
- `pmcid`
- `section`
- `text`
- `char_count`
- `source: "pubtator_abstract" | "pubtator_full_bioc"`

Behavior:

- Never returns raw BioC documents.
- Preserves stable passage IDs compatible with review RAG where possible.
- Drops references by default.
- Enforces `max_chars` by dropping passages, not truncating mid-passage.
- Returns `dropped` reasons such as `char_budget_exceeded`, `section_filtered`, or `reference_excluded`.

## New Tool: `pubtator.estimate_publication_context`

Purpose: Let the LLM decide whether a fetch will fit before asking for it.

Request fields:

- Same filter fields as `get_publication_passages`, without `max_chars`.

Response fields:

- `success: true`
- `pmids`
- `estimated_passages`
- `estimated_chars`
- `sections_by_pmid`
- `recommended_mode`
- `warning: str | None`

Behavior:

- Uses PubTator passage metadata when possible.
- For full text, may perform a metadata/full fetch internally but returns only counts and section labels.
- Warns when estimated output exceeds 10000 tokens or 25000 tokens equivalent.

## New Tool: `pubtator.inspect_review_index`

Purpose: Explain what the review RAG index contains and why retrieval might be empty.

Request fields:

- `review_id: str`
- `pmids: list[str]` optional.
- `include_passage_samples: bool` default `false`.
- `sample_per_pmid: int` default 2, range 1-5.

Response fields:

- `success: true`
- `review_id`
- `preparation_status`
- `sources: list[ReviewSourceSummary]`
- `totals`
- `failed_sources`

`ReviewSourceSummary`:

- `source_id`
- `pmid`
- `source_kind`
- `job_status`
- `error`
- `attempt_statuses`
- `sections`
- `passage_count`
- `char_count`
- `sample_passages`

Behavior:

- Includes failed PMID/source IDs and reasons when available.
- Distinguishes “not indexed,” “indexed but no matching query,” and “failed preparation.”
- Supports the core LLM question: “What can I ask this index?”

## Retrieval Diagnostics

Extend `RetrieveReviewContextResponse` with optional `diagnostics`.

Fields:

- `query`
- `query_tokens`
- `query_mode: "strict" | "relaxed" | "strict_and_relaxed"`
- `candidate_count`
- `selected_count`
- `available_sections`
- `indexed_pmids`
- `failed_sources`
- `filter_summary`
- `suggested_queries`
- `message`

Behavior:

- Always include diagnostics for zero-passage responses.
- Include diagnostics for non-zero responses when requested by `include_diagnostics=true`.
- Suggested queries are deterministic keyword variants derived from the original question and indexed section vocabulary. They are not LLM-generated.

Example zero-result message:

```json
{
  "message": "No passages selected. Review rev_123 has 8 indexed PMIDs and sections ABSTRACT, TABLE, DISCUSS. Try shorter keyword queries or remove section filters.",
  "suggested_queries": ["colchicine dose children", "heterozygous MEFV phenotype", "clinical diagnosis FMF"]
}
```

## Batch Retrieval

Add `pubtator.retrieve_review_context_batch`.

Request fields:

- `review_id`
- `queries: list[str]` required, 1-10.
- Shared filters: `pmids`, `entity_ids`, `sections`.
- Shared packing controls: `max_passages_per_query`, `max_total_passages`, `max_chars`.
- `deduplicate_passages: bool` default `true`.
- `include_diagnostics: bool` default `true`.

Response fields:

- `success`
- `review_id`
- `results: list[RetrieveReviewContextResponse]`
- `merged_context_pack`
- `preparation_status`

Behavior:

- Runs retrieval for multiple query variants.
- Merges selected passages deterministically.
- Deduplicates by passage ID.
- Keeps per-query diagnostics so the LLM can learn which query worked.

## API Shape

Add REST equivalents under `/api/reviews` and `/api/publications` where useful:

- `POST /api/publications/passages`
- `POST /api/publications/context-estimate`
- `GET /api/reviews/{review_id}/index`
- `POST /api/reviews/{review_id}/context/batch`

MCP tools should call service adapters over the same internal service layer as REST routes.

## Repository Additions

Add repository methods for index inspection:

- `list_review_sources(review_id, pmids=None) -> list[ReviewSourceSummary]`
- `list_review_failed_sources(review_id) -> list[FailedSourceSummary]`
- `review_index_totals(review_id) -> ReviewIndexTotals`

Implementation may use SQL joins over:

- `review_preparation_jobs`
- `full_text_retrieval_attempts`
- `review_passages`

No schema migration is required for this upgrade.

## Publication Passage Service

Create a small service responsible for compacting PubTator BioC responses:

- Fetches PubTator BioC JSON using existing `PubTator3Client`.
- Normalizes section labels with the same rules as review RAG.
- Filters by sections and reference/table flags.
- Estimates and enforces character budgets.
- Produces compact passages and drop reasons.

This avoids putting compaction logic inside MCP adapters.

## MCP Discoverability Requirements

Server instructions must:

- Fit under 2 KB.
- Put the capability map in the first sentence.
- Mention `get_server_capabilities`.
- Mention the preferred workflow: `search -> index -> inspect -> retrieve`.
- Warn that raw full BioC can be large and compact passage tools are safer.

Tool descriptions must:

- Start with “Use this when…”
- Include the primary input fields in prose.
- Include the output shape in prose when it matters.
- Distinguish similar tools:
  - `fetch_publication_annotations`: raw PubTator export.
  - `get_publication_passages`: compact passage retrieval.
  - `retrieve_review_context`: indexed review RAG.
  - `inspect_review_index`: index status/contents/debugging.

Capabilities resource must include:

- `recommended_workflows`
- `tool_groups`
- `large_output_guidance`
- `review_rerag` workflow and limitations

## Error Handling

- Compact passage tools return partial results per PMID when one PMID fails.
- Index inspection includes failure reasons instead of hiding them behind aggregate counts.
- Retrieval zero-results are successful responses with diagnostics, not errors.
- Database failures remain API errors.
- PubTator upstream failures include concise per-PMID failure entries.

## Testing Strategy

Unit tests:

- Server instructions contain the capability map and workflow guidance within 2 KB.
- Tool descriptions include expected “Use this when” triggers.
- Compact publication passage service filters sections, excludes references by default, includes tables by default, and enforces `max_chars`.
- Context estimate returns section counts and warning for large outputs.
- Review index inspection maps repository rows to source summaries.
- Retrieval diagnostics are present for zero-result responses.
- Batch retrieval deduplicates passage IDs and preserves per-query diagnostics.

Route tests:

- Publication passages endpoint returns compact passages without raw BioC.
- Review index endpoint returns failed source reasons.
- Batch context endpoint returns merged context and per-query diagnostics.

MCP tests:

- New tools are registered with expected names.
- `review_rerag_workflow` prompt remains registered.
- Capabilities resource advertises workflows and tool groups.

Integration tests:

- Existing Docker PostgreSQL schema test remains passing.
- Repository index inspection SQL works against PostgreSQL when `PUBTATOR_LINK_TEST_DATABASE_URL` is set.

## Success Criteria

The upgrade is complete when:

- A Claude Code user can infer the research workflow from the initial MCP instructions.
- An LLM can ask “what is indexed?” and receive PMIDs, sections, counts, and failures.
- Full-text grounding workflows can use compact passage tools without hitting large-output persistence for ordinary 5-10 PMID tasks.
- Zero RAG hits return actionable diagnostics and suggested deterministic query variants.
- Batch retrieval reduces repeated serial reformulation.
- `make ci-local` passes.

## Deferred Work

- Embedding or hybrid vector retrieval.
- Stored audit snapshots of context packs.
- Per-client custom MCP server profiles.
- Authentication and multi-tenant authorization.
- Full PRISMA/RoB/GRADE review workflow.
