# Citation, Preflight, And Token Ergonomics Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

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
- Add per-PMID retrieval budget floors and status summaries.
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
- Search preflight guesses can be pessimistic versus indexing reality. PMIDs
  reported as `unknown` or `pmc_not_open_access` may still index as full text
  through a different resolver path.
- `inspect_review_index` sources lack citation-grade authors/journal/volume/
  issue/pages.
- Unknown `coverage_hint` entries add noise with little signal.
- `suggested_queries` are token slices, not semantic alternatives.
- `next_steps` only appears for zero-result queries, not high-drop queries.
- Repeated research-use text in every tool description wastes schema/context.

Documentation gaps to close in this slice:

- `stable_citation_key` must be documented as stable across repeated retrieval
  calls and review index snapshots for the same source passage identity. It is
  not a display citation number; consumers should use it as a durable join key
  and use `stable_citation_map` for render-time numbering.
- Section taxonomy must be documented as lowercase canonical names across search
  filters, review passage metadata, diagnostics, and examples. Inputs should be
  normalized before storage or matching so mixed-case upstream labels do not
  fragment retrieval.

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

### Preflight Signal Naming

Search-time coverage is a guess, not the final index outcome. Do not let the
field name imply stronger certainty.

Preferred public shape for search results:

```json
{
  "preflight_coverage_guess": "unknown",
  "preflight_coverage_reason": "pmc_not_open_access",
  "preflight_confidence": "low"
}
```

Compatibility:

- Keep `coverage_hint.expected_coverage` for one compatibility window if needed.
- Add structured deprecation metadata stating that search consumers should use
  `preflight_coverage_guess` for filtering decisions.
- `expected_coverage` remains acceptable on `preflight_review_sources` only if
  documentation makes clear it is pre-indexing evidence, not final index
  coverage.

Implementation should also tighten resolver parity where cheap:

- if PubTator/PMC preflight reports no open access but another configured
  indexing resolver can likely produce full text, return
  `preflight_coverage_guess="full_text"` or at least
  `preflight_confidence="low"` with a note,
- add regression PMIDs from the evaluation as fixtures where network mocking is
  possible: `33454820`, `37298536`, `37752496`, `39540697`, `40090944`.

### Preflight diagnostics

Add to `SearchResponse`:

```json
{
  "preflight_failure_reason": "timeout",
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

### Per-PMID Batch Budgeting

Add to `retrieve_review_context_batch`:

```json
{
  "min_passages_per_pmid": 1,
  "prioritize_pmids": ["37752496"]
}
```

Behavior:

- `min_passages_per_pmid` is independent from `min_passages_per_source`.
- The first pass should try to include at least this many passages per PMID
  before spending overflow budget.
- `prioritize_pmids` boosts central sources before general overflow allocation.
- Existing `max_total_passages`, `max_chars`, and `max_response_chars` remain
  hard caps. If caps prevent inclusion, the response must explain that in the
  per-PMID summary.

Add optional response field:

```json
{
  "pmid_status_summary": [
    {
      "pmid": "37752496",
      "coverage": "full_text",
      "passages_candidates": 4,
      "passages_returned": 1,
      "dropped_reasons": ["char_budget_exceeded"]
    }
  ]
}
```

This prevents consumers from reconstructing source representation by joining
`dropped[]`, `query_summaries[]`, and source budget summaries.

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

Capabilities and workflow help should promote `pubtator.find_entity_relations`
as an optional evidence-discovery step after `pubtator.search_biomedical_entities`
and before literature search when relation types can sharpen the query or
candidate PMID selection.

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
    "deprecated_fields": [
      {
        "field": "coverage_hint.expected_coverage",
        "status": "deprecated_for_search_filtering",
        "replacement": "preflight_coverage_guess"
      },
      {
        "field": "prepare_mode",
        "status": "deprecated",
        "replacement": "omit"
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
- Search preflight coverage is named as a guess or explicitly deprecated for
  filtering.
- Unknown coverage hints are omitted when non-informative.
- `inspect_review_index(include_metadata=true)` attaches citation metadata.
- `tail_preview` appears for truncated passages.
- `next_steps` appears for high-drop nonzero query summaries.
- Batch retrieval honors `min_passages_per_pmid` where budgets allow and returns
  `pmid_status_summary`.
- Capabilities expose one global notice and no repeated long safety sentence in
  every tool description.

## References

- NCBI E-utilities ESummary/EFetch metadata documentation:
  https://www.ncbi.nlm.nih.gov/books/NBK25499/
- MCP tools output schema guidance:
  https://modelcontextprotocol.io/specification/2025-11-25/server/tools
