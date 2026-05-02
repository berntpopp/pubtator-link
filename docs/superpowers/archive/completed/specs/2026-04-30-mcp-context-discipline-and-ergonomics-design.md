# MCP Context Discipline and Ergonomics Design

## Goal

Make PubTator-Link easier and safer for LLM clients to use as a primary
biomedical grounding MCP. The upgrade focuses on bounded outputs, clear
diagnostics, flat tool-call ergonomics, and better first-use guidance while
preserving existing REST and MCP contracts.

## Background

Claude's MCP review rated PubTator-Link highly for biomedical search, speed,
review-scoped retrieval, and citation traceability. The weak points were:

- `pubtator.retrieve_review_context_batch` can exceed the caller's expected
  context budget because it returns full per-query results plus a merged pack.
- `max_chars` currently budgets passage text, not serialized response size.
- large tables and long sections can dominate or empty compact retrieval.
- MCP tool inputs are wrapped as `{ "request": { ... } }`, which is harder for
  LLMs than flat arguments.
- string-encoded fields such as JSON filters and comma-separated sections push
  clients toward shell tooling such as `jq`.
- README and capability resources under-advertise prompts, compact passage
  tools, and review retrieval workflow details.

Claude Code documentation confirms that MCP tools are deferred by default and
that server instructions, concise tool descriptions, and selective always-load
metadata matter for tool discovery. The MCP specification supports structured
tool outputs via `structuredContent` and optional `outputSchema`; PubTator-Link
should keep returning normal dictionaries but shape them so clients can consume
the response directly without shell post-processing.

## Non-Goals

- Do not remove or rename existing public MCP tools.
- Do not expose destructive cache or database operations through public MCP.
- Do not make clinical recommendations. Keep the research-use limitation
  prominent.
- Do not require a PostgreSQL database for unit tests.
- Do not implement a new embedding model or replace PostgreSQL full-text search.

## Current Failure Mode

`ReviewContextService.retrieve_context_batch()` calls
`retrieve_context()` once per query, passing the full `max_chars` value each
time. It then returns:

- `results`: full per-query responses, each with passage text and diagnostics.
- `merged_context_pack`: deduplicated passages capped by `max_chars`.

This means `max_chars` caps only merged passage text. It does not cap the full
response. Diagnostics default to true for batch retrieval, so large reviews can
repeat indexed PMIDs, sections, and failure summaries for every query.

## Design Principles

1. **Bound the default payload.** Defaults should fit ordinary LLM context
   without file fallback.
2. **Preserve citation integrity.** Never silently truncate a passage without
   returning explicit boundary and truncation metadata.
3. **Prefer summaries by default.** Full per-query packs, full table text, and
   large diagnostics should be opt-in.
4. **Make MCP calls obvious.** Add flat v2 MCP tools with typed fields while
   keeping current wrapped tools for compatibility.
5. **Make zero-result states actionable.** Diagnostics should explain whether
   the problem is no index, filters, query tokens, over-budget passages, or
   source preparation failures.
6. **Avoid shell dependencies.** Responses should include useful compact
   summaries and output-path hints so browser and desktop clients do not need
   `jq`.

## Response Modes

Add a response mode to batch review retrieval:

```python
ReviewBatchResponseMode = Literal["compact", "merged_only", "full", "diagnostics"]
```

- `compact` is the default. Return the merged context pack with passage text,
  plus per-query summaries without passage text.
- `merged_only` returns only the merged context pack and minimal totals.
- `full` preserves the current behavior by returning full per-query responses
  plus the merged context pack.
- `diagnostics` returns no passage text. It returns per-query hit counts,
  candidate counts, selected counts, dropped counts, sections, source coverage,
  and suggested query rewrites.

Existing clients that do not pass `response_mode` receive the new safer
`compact` default. Clients needing the old payload shape can pass
`response_mode="full"`.

## Budget Metadata

Add budget metadata to review context responses:

```python
class ContextBudget(BaseModel):
    max_chars: int
    text_chars: int
    estimated_json_chars: int
    estimated_total_chars: int
    estimated_tokens: int
    truncated: bool = False
    dropped_count: int = 0
```

Each `ContextPassage` should include:

- `char_count`
- `truncated`
- `start_char`
- `end_char`
- `boundary`

Each `ContextPack` should include:

- `total_chars`
- `estimated_tokens`
- `budget`
- `dropped`

Token estimates use a simple conservative formula:

```python
estimated_tokens = max(1, math.ceil(estimated_total_chars / 3.6))
```

The exact estimate does not need tokenizer dependencies; it only needs to be
stable and conservative enough for client preflight decisions.

## Hard Payload Discipline

`max_chars` remains a passage-text budget for backward compatibility, but batch
responses also receive:

```python
max_response_chars: int = Field(default=24000, ge=2000, le=100000)
```

For `compact`, `merged_only`, and `diagnostics`, the service must keep estimated
serialized response size under `max_response_chars` when possible by:

1. omitting full per-query passage text,
2. limiting diagnostics lists to samples,
3. dropping lower-ranked merged passages,
4. truncating oversized passages only when `allow_truncated_passages=True`,
5. returning explicit dropped/truncated reasons.

For `full`, the service may exceed `max_response_chars` but must return
`budget.estimated_total_chars` and `budget.truncated=False` so clients can see
that the full mode was expensive.

## Oversized Passage Handling

Add:

```python
allow_truncated_passages: bool = True
max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)
```

When a selected passage is larger than `max_chars_per_passage`, create a bounded
excerpt around the query match rather than dropping it wholesale. The excerpt
must:

- preserve PMID, section, passage ID, and source metadata.
- include `start_char`, `end_char`, and `boundary`.
- set `truncated=True`.
- append no synthetic text inside `text`; instead, use metadata fields and drop
  reasons to indicate truncation.

The first implementation uses deterministic character windows around the first
query-token match. Later work can add table row grouping.

## Table and Reference Controls

Review retrieval should match publication passage controls:

```python
include_tables: bool = False
include_references: bool = False
table_mode: Literal["off", "preview", "full"] = "preview"
```

Default behavior:

- exclude reference sections.
- include tables only as bounded previews when they score highly.
- require `table_mode="full"` for full table text.

This protects common clinical-genetics evidence workflows from one long Delphi
table or supplement-like section consuming the whole response.

## Diagnostics

Add compact diagnostic summaries:

```python
class QueryDiagnosticsSummary(BaseModel):
    query: str
    query_tokens: list[str]
    candidate_count: int
    selected_count: int
    returned_count: int
    dropped_count: int
    top_sections: list[str]
    top_pmids: list[str]
    zero_result_reason: str | None = None
    suggested_queries: list[str]
```

Full diagnostics remain available for single-query retrieval and
`response_mode="full"`, but batch defaults should use summaries.

Zero-result reasons should distinguish:

- `review_not_indexed`
- `no_candidate_matches`
- `filters_excluded_all_candidates`
- `all_candidates_over_budget`
- `preparation_failed`

## Source Coverage

Extend `inspect_review_index` source summaries with:

```python
coverage: Literal["title_only", "abstract_only", "full_text", "curated_url", "unknown"]
```

The first version can infer coverage conservatively:

- `full_text` when source attempts include successful full-text preparation or
  sections beyond title/abstract exist.
- `abstract_only` when abstract passages exist but no full-text sections exist.
- `title_only` when only title-like text exists.
- `curated_url` for curated URL sources.
- `unknown` when source metadata is insufficient.

This helps LLMs drop metadata-only PMIDs before spending retrieval calls.

## Scoring Transparency

Add optional score metadata to returned passages:

```python
class PassageScore(BaseModel):
    lexical_rank: float
    section_boost: float
    entity_overlap: int
    pmid_filter_boost: float
    final_rank: float
```

The current rank can be exposed without changing retrieval behavior. The goal
is to help consumers explain why passages were selected, not to implement a new
ranker in this upgrade.

## Flat MCP Tools

Keep existing wrapped tools. Add flat aliases for high-use workflows:

- `pubtator.search_literature_v2`
- `pubtator.search_biomedical_entities_v2`
- `pubtator.get_publication_passages_v2`
- `pubtator.inspect_review_index_v2`
- `pubtator.retrieve_review_context_v2`
- `pubtator.retrieve_review_context_batch_v2`

These tools should accept flat arguments and build internal request models in
adapters. Example:

```python
async def retrieve_review_context_batch_v2(
    review_id: str,
    queries: list[str],
    pmids: list[str] | None = None,
    sections: list[str] | None = None,
    response_mode: ReviewBatchResponseMode = "compact",
    max_chars: int = 12000,
    max_response_chars: int = 24000,
    include_tables: bool = False,
) -> dict[str, Any]:
    ...
```

The existing wrapped tools remain documented as compatibility tools. New docs
should teach v2 tools first.

## Structured Inputs

Replace MCP-only string-encoded inputs in v2 tools:

- `filters: dict[str, Any] | None` instead of JSON string where FastMCP schema
  support allows it.
- `sections: list[str]` instead of comma-separated sections.
- `bioconcepts: list[Bioconcept] | Literal["all"]` for annotation.

If `dict[str, Any]` produces poor schema output in FastMCP, defer filters-v2 and
document typed alternatives for common fields rather than exposing a loose JSON
string.

## Discoverability

Update server instructions to put critical routing terms early:

- PubMed
- PubTator
- biomedical literature
- clinical genetics
- PMID
- compact passages
- review RAG
- evidence grounding

Add Claude-specific always-load metadata only to one small discovery tool if
FastMCP supports `_meta` cleanly:

- `pubtator.get_server_capabilities`

Do not always-load the full server by default.

Update `pubtator://capabilities` with:

- `sample_calls`
- `output_cheatsheet`
- `budgeting_defaults`
- `recommended_modes`

Update README and `docs/MCP_CONNECTION_GUIDE.md` to document:

- v2 flat tools as preferred for LLM clients.
- compact/default batch behavior.
- `response_mode` choices.
- when to request `full`.
- how to avoid raw BioC except intentionally.

## REST Equivalents

Update existing REST request/response models for review context endpoints. Do
not create duplicate REST routes unless the request shape must differ. REST
clients can use the same JSON models and `response_mode`.

## Backward Compatibility

- Existing tools keep their names and accepted fields.
- Existing response fields remain present unless clients opt into a summary-only
  mode.
- New fields are additive.
- Batch default becomes compact. This is a behavior change, but not a schema
  break. Clients that need old full per-query payloads pass `response_mode`.

## Testing Strategy

Unit tests should cover:

- batch default omits per-query passage text.
- `response_mode="full"` preserves full per-query passages.
- `response_mode="diagnostics"` returns no passage text.
- `max_response_chars` drops lower-ranked passages and reports reasons.
- oversized passages are excerpted with `truncated=True`.
- table defaults avoid full table text.
- source coverage inference.
- flat v2 MCP tool registration and adapter calls.
- capabilities resource includes sample calls and output cheat sheet.

Route tests should cover REST request/response shape for new fields.

MCP tests should inspect registered tool schemas enough to prove v2 tools expose
flat arguments and current compatibility tools remain present.

## Acceptance Criteria

- A default batch retrieval response is compact and does not repeat full
  per-query passage text.
- A caller can request diagnostics-only batch retrieval and receive actionable
  query refinement data without passage text.
- Oversized passages no longer disappear silently; they are either bounded
  excerpts or explicit drops.
- Review retrieval defaults protect context from long table/reference sections.
- Flat v2 MCP tools are discoverable and do not require `{request: {...}}`.
- Docs teach the v2 workflow and context-management modes.
- `make ci-local` passes.

