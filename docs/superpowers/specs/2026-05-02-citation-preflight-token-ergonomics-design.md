# Citation, Preflight, And Token Ergonomics Design

Date: 2026-05-02

## Purpose

Close the remaining LLM-consumer footguns around citation metadata, coverage
diagnostics, and context budget waste.

The prior metadata sprint added NCBI-backed publication metadata and
`search_literature(metadata="basic" | "full")`. This design makes that safer and
more discoverable while reducing repeated prompt/schema tokens.

## Goals

- Make citation-grade metadata easy to get without author fabrication risk.
- Add structured search preflight failure diagnostics.
- Enrich `inspect_review_index` with citation metadata.
- Add truncated-passage transparency.
- Improve zero-result and high-drop query guidance.
- Add dry-run/cost hints for search.
- Move repeated research-use wording to one global notice.
- Add structured deprecation/schema guidance to capabilities.

## Non-Goals

- No backend LLM for query rewriting.
- No destructive public MCP operations.
- No hidden clinical guidance. All outputs remain source-grounded literature
  metadata and passages.

## Current State

Solved or mostly solved:

- `pubtator.get_publication_metadata` exists.
- `search_literature(metadata="basic" | "full")` can populate authors, volume,
  issue, pages, DOI, PMCID, publication types, and citations.
- `pubtator.search_guidelines` exists and is advertised.
- `pubtator.export_review_audit_bundle` exists and is advertised.
- `stable_citation_key` and `stable_citation_map` exist.

Gaps:

- `metadata="none"` remains the MCP search default, so compact search can still
  return `authors=[]`.
- Search authors are typed as `list[Any]`; partial upstream author shapes can
  leak.
- `attach_preflight_coverage` collapses failures to one generic message.
- `inspect_review_index` sources lack citation-grade authors/journal/volume/
  issue/pages.
- Unknown `coverage_hint` entries add noise with little signal.
- `suggested_queries` are token slices, not semantic alternatives.
- `next_steps` only appears for zero-result queries, not high-drop queries.
- Repeated research-use text in every tool description wastes schema/context.

## Public Surface

### Metadata defaults

Change MCP `pubtator.search_literature` default:

```text
metadata = "basic"
```

Keep REST default as `metadata="none"` unless route compatibility requires no
extra network cost. Capabilities should state the difference.

Normalize search result authors to the existing `PublicationAuthor` shape or a
small search-specific author model. Do not keep `list[Any]`.

### `inspect_review_index` metadata

Add optional:

```json
{
  "include_metadata": true,
  "metadata": "basic"
}
```

When enabled, each source summary can include:

```json
{
  "citation_metadata": {
    "pmid": "40234174",
    "title": "...",
    "authors": [{"last_name": "Smith", "initials": "J"}],
    "journal": "...",
    "pub_year": 2024,
    "volume": "12",
    "issue": "3",
    "pages": "1-9",
    "doi": "10.x/y",
    "pmcid": "PMC..."
  }
}
```

Use the existing `PublicationMetadataService`; do not duplicate NCBI parsing.

### Preflight diagnostics

Add to `SearchResponse`:

```json
{
  "preflight_error_reason": "timeout",
  "preflight_error_code": "coverage_preflight_timeout"
}
```

Allowed reasons should be compact and stable:

- `timeout`
- `upstream_unavailable`
- `converter_failed`
- `internal_error`

Search should still succeed when coverage preflight fails.

### Coverage hint compression

For search hits:

- Omit `coverage_hint` when `expected_coverage="unknown"` and there is no PMCID,
  DOI, fallback flag, note, or resolver attempt.
- Keep a response-level `source_versions["coverage_preflight"]`.
- Consider a response-level `coverage_summary` only when useful.

### Truncated passage transparency

Add to `ContextPassage`:

```json
{
  "tail_preview": "next ~120 chars after the returned window",
  "next_window_token": "opaque token or null"
}
```

Minimum viable slice:

- `tail_preview` only, computed from source text after `end_char`.
- `next_window_token` can be deferred unless paging is implemented.

### Query guidance

Improve `suggested_queries` deterministically:

- strip section words and boilerplate,
- preserve recognized biomedical entities and short gene symbols such as `MEFV`,
- add synonym/alias expansions when available from PubTator entity lookup or
  request `entity_ids`,
- add guideline-oriented variants when guideline terms are present,
- add `next_steps` when `dropped_count` is high, not only when returned count is
  zero.

No backend LLM calls.

### Dry run for search

Add:

```json
{
  "dry_run": true
}
```

For `search_literature`, dry run returns normalized query, merged filters,
expected coverage/metadata cost flags, and whether extra upstream calls would be
made. It should not call PubTator search unless a real estimate requires it; if
that is too weak, name it `estimate_only`.

## Token Ergonomics

Move long safety wording out of every individual tool description.

Keep one global notice in:

- server instructions / MCP metadata,
- `pubtator.get_server_capabilities.notice`,
- `pubtator.workflow_help.notice`.

Tool descriptions should state only when to use the tool and key arguments.
Example:

```text
Search PubMed literature through PubTator3. Use metadata='basic' for citation
screening and coverage='preflight' before indexing.
```

Do not append the full "Research use only; not for diagnosis..." sentence to
every tool schema. This keeps safety policy visible while reducing repeated MCP
context tokens.

## Structured Schema Guidance

Add to capabilities:

```json
{
  "schema_policy": {
    "argument_style": "flat",
    "deprecated_shapes": [
      {
        "shape": "request_envelope",
        "status": "unsupported",
        "replacement": "flat_top_level_arguments"
      }
    ],
    "deprecated_tools": []
  }
}
```

This replaces natural-language-only warnings like "no `_v2`" or "do not use
request envelopes".

## Testing

Required tests:

- MCP schema default for search metadata is `basic`.
- Search result authors are typed and stable.
- Preflight failure returns structured error fields and still succeeds.
- Unknown coverage hints are omitted when non-informative.
- `inspect_review_index(include_metadata=true)` attaches citation metadata.
- `tail_preview` appears for truncated passages.
- `next_steps` appears for high-drop nonzero query summaries.
- Capabilities expose one global notice and no repeated long safety sentence in
  every tool description.

## References

- NCBI E-utilities ESummary/EFetch metadata documentation:
  https://www.ncbi.nlm.nih.gov/books/NBK25499/
- MCP tools output schema guidance:
  https://modelcontextprotocol.io/specification/2025-11-25/server/tools

