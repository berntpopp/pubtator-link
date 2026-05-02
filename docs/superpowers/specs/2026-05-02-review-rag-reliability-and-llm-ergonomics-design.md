# Review RAG Reliability And LLM Ergonomics Design

Date: 2026-05-02

## Purpose

Make PubTator-Link review RAG harder to silently degrade and easier for LLM
clients to use well. The immediate trigger is a run where
`pubtator.index_review_evidence` failed with `review_index_unavailable`; the
fallback chain preserved workflow continuity, but the deliverable became
abstract-only across every source.

This design combines the highest-impact remaining fixes from the observability,
parallel-concurrency, and LLM-consumer reviews into one coherent reliability and
ergonomics slice.

## Goals

- Prevent silent review-RAG degradation when indexing or full-text preparation
  fails.
- Make degraded retrieval explicit and machine-readable.
- Let MCP clients surface useful diagnostics without requiring a second
  `pubtator.diagnostics` call.
- Try a bounded PMC/DOI/Europe PMC resolver chain before declaring a source
  `abstract_only`.
- Reduce default token waste in bulky publication/search outputs.
- Make review-oriented tools return citation-grade lines by default where the
  cost is small.
- Improve guideline retrieval for consensus/recommendation queries.
- Populate entity synonyms where source data or a cheap cached lookup supports
  it.
- Remove stale public guidance around historical `_v2` tool names and
  `prepare_mode`.

## Non-Goals

- No backend LLM or generated medical interpretation.
- No clinical decision support.
- No destructive hosted MCP operations.
- No distributed multi-worker rate limiting. That remains a separate deployment
  project.
- No full OpenTelemetry tracing rollout in this slice, though the error and
  diagnostics fields should be trace-friendly.

## Current State

Solved:

- The concrete `review_index_unavailable` outage from missing
  `review_session_sources` is fixed by migration
  `0003_review_session_sources_repair`.
- `/ready` now requires `review_session_sources`.
- MCP tool lifecycle logs and Prometheus metrics exist.
- `/metrics` exports MCP tool counters and latency histograms.
- `PubTatorResourcesMiddleware` avoids the prior `@app.middleware("http")`
  contextvars trap.
- `retrieve_review_context_batch` bounds query coroutine submission by
  `retrieval_concurrency`.
- `prepare_mode` is effectively `Literal["selected"]`; MCP schema policy marks
  it deprecated/omit.

Remaining gaps:

- `review_index_unavailable` still forces the LLM to infer fallback behavior
  from the error envelope and then manually call another tool.
- Error envelopes do not include a small diagnostics snapshot.
- Retrieval responses do not consistently expose a top-level degraded mode.
- Full-text preparation declares some PMIDs `abstract_only` after a narrow
  resolver path, even when PMCIDs, DOIs, or Europe PMC metadata might support
  section-level text.
- `get_publication_passages` can return bulky metadata without a dry-run or
  lean/default response mode.
- Some review-oriented search paths still default to no citation lines.
- Guideline ranking does not strongly prioritize true consensus/recommendation
  publication types and known guideline families.
- Entity autocomplete exposes `synonyms` but often returns an empty list.
- Current docs still contain some historical `_v2` and `prepare_mode` guidance
  that is easy to misread as active advice.

## Public Surface

### Degraded Mode

Add a common degraded-mode field to review retrieval and relevant fallback
responses:

```json
{
  "degraded_mode": null
}
```

Allowed values:

- `null`: normal result.
- `"abstract_only"`: result is grounded in abstracts/metadata because
  section-level/full-text passages are unavailable.
- `"metadata_only"`: result is grounded in title/metadata only.
- `"index_unavailable"`: review index could not be queried at all; fallback
  content came from non-index tools.

Rules:

- `degraded_mode` must be top-level on review retrieval responses.
- If mixed coverage exists, choose the most severe mode that affects any
  returned claim-bearing source and include per-source coverage details as
  today.
- When a fallback tool returns publication metadata/passages after
  `review_index_unavailable`, the MCP envelope should include
  `degraded_mode="index_unavailable"` unless the fallback produced usable
  section-level passages.

### Inline Diagnostics Snapshot

Extend `mcp_tool_error` payloads with an optional small
`diagnostics_snapshot`:

```json
{
  "error_code": "review_index_unavailable",
  "diagnostics_snapshot": {
    "database": {
      "status": "ready",
      "schema_current": true,
      "missing_tables": [],
      "missing_columns": []
    },
    "review_index": {
      "review_id": "fmf-vus",
      "session_id": "phase-1",
      "known_sources": 8,
      "prepared_sources": 3,
      "failed_sources": 5
    },
    "recovery_hint": "Retry index_review_evidence after migration or continue with abstract_only fallback."
  }
}
```

Constraints:

- Keep the snapshot under 2 KB.
- Do not include raw query text or user-submitted annotation text.
- Include only bounded counts, status strings, missing schema names, and
  recovery hints.
- Build from already-available app resources when possible; if resources are
  unavailable, omit the snapshot rather than blocking error handling.

### MCP-Native Degradation Notices

Where FastMCP `Context` can be added without breaking tool schemas, emit:

- `ctx.warning()` when a review tool falls back from index retrieval to
  abstracts/metadata.
- `ctx.notice()` when a resolver upgrades coverage, such as DOI or Europe PMC
  fallback producing section text.

MCP notices are additive. The machine-readable response fields remain the source
of truth.

### Internal Fallback From Index Failure

When `pubtator.index_review_evidence` fails with
`review_index_unavailable` after validating input PMIDs:

1. Return the structured error envelope as today.
2. Include `diagnostics_snapshot`.
3. Include `degraded_mode="index_unavailable"`.
4. Include `next_commands` pointing at the best fallback.
5. For hosted MCP calls where the tool implementation can safely produce a
   fallback payload without mutating state, internally call the same
   publication-passage fallback used by `next_commands` and include a compact
   `fallback_preview`.

`fallback_preview` must be bounded:

```json
{
  "fallback_preview": {
    "tool": "pubtator.get_publication_passages",
    "mode": "compact_passages",
    "source_count": 8,
    "degraded_mode": "abstract_only",
    "coverage_by_pmid": {
      "35042149": "abstract_only"
    }
  }
}
```

The preview should not include full passage text. It exists to keep the user and
LLM aware of the actual grounding quality.

## Source Coverage Resolver Chain

Before marking a PMID `abstract_only`, full-text preparation should try a
bounded resolver chain:

1. PubTator full BioC export.
2. PMC OA BioC when PMCID exists and reuse allows it.
3. Europe PMC JATS or equivalent structured full-text endpoint when PMCID/DOI
   is available.
4. DOI metadata/content negotiation for publisher landing metadata that can
   provide section-level abstract/full-text snippets.
5. PubTator abstract fallback.

Each attempt records:

- resolver name,
- normalized source identifier used,
- status,
- status code when applicable,
- retryable flag,
- terminal coverage reason.

Do not scrape arbitrary publisher HTML in this slice. DOI and Europe PMC
fallbacks should use structured or stable APIs only.

## Token And Citation Ergonomics

### `verbosity`

Add `verbosity: Literal["lean", "standard", "full"] = "standard"` to bulky
publication/search/passage responses where output size is currently hard to
control.

Recommended behavior:

- `lean`: omit empty/null fields, omit author subfields that are empty, omit
  `mesh_headings` unless populated, omit `text_hl` unless requested, include one
  compact citation line when available.
- `standard`: current useful fields, but still omit empty arrays/nulls where
  schema compatibility allows.
- `full`: current maximal response shape, preserving empty fields for clients
  that rely on stable keys.

Apply first to:

- `pubtator.search_literature`
- `pubtator.search_guidelines`
- `pubtator.get_publication_passages`
- `pubtator.get_publication_metadata`

REST routes may keep current defaults if backward compatibility requires it;
MCP tools should prefer `standard` or `lean` defaults.

### Citation Defaults

Review-oriented MCP tools should default to NLM citations when metadata is
available and the marginal token cost is low:

- `pubtator.search_guidelines`: keep `include_citations="nlm"`.
- `pubtator.search_literature`: change MCP default from `"none"` to `"nlm"` only
  when `metadata != "none"` or `review_oriented=true`.
- `pubtator.get_publication_passages`: include one compact NLM line per PMID in
  `standard` and `full` modes.

### Passage Cost Preview

Add `dry_run: bool = false` to `pubtator.get_publication_passages`.

When `dry_run=true`, return:

```json
{
  "dry_run": true,
  "pmid_count": 8,
  "estimated_chars": 14200,
  "estimated_tokens": 3600,
  "estimated_coverage": {
    "full_text": 3,
    "abstract_only": 5
  },
  "recommended_mode": "compact_passages"
}
```

No passage text should be returned in dry-run mode.

## Search Quality

### Guideline Ranking

When `guideline_boost=true`, add a transparent ranking boost for:

- publication types containing guideline, consensus, recommendation, practice
  guideline, systematic review, meta-analysis,
- title/abstract terms: EULAR, ACR, SHARE, Eurofever, consensus,
  recommendation, guideline, management,
- exact phrase matches for user guideline queries.

Keep ranking explainable by adding a compact `ranking_reasons` list only when
`verbosity != "lean"` or diagnostics are requested.

Regression target:

- Query: `Ozen EULAR recommendations management familial Mediterranean fever 2016`
- Expected: Ozen 2016 EULAR recommendations should rank on the first page when
  available from upstream search results or metadata expansion.

### Entity Synonyms

Populate `synonyms` in `search_biomedical_entities` from:

1. PubTator autocomplete response fields when present.
2. Existing `match` text when it explicitly says "Matched on synonyms ...".
3. Optional cached secondary lookup for high-value biomedical entities when the
   autocomplete response is empty.

Keep synonyms bounded:

- max 10 strings per entity,
- strip markup,
- deduplicate case-insensitively,
- do not add inferred synonyms unless the source is explicit.

## Cleanup

- Remove active `_v2` warnings from instructions where no `_v2` tools are
  exposed.
- Keep one short compatibility note in `docs/MCP_CONNECTION_GUIDE.md`:
  reconnect/refresh client caches if old `_v2` aliases appear.
- Remove `prepare_mode` from examples except historical specs/plans.
- Keep schema policy marking `prepare_mode` deprecated until the next minor
  release.

## Tests

Add focused tests before implementation:

- Error envelope includes `diagnostics_snapshot` for
  `review_index_unavailable` when diagnostics are available.
- Error envelope omits `diagnostics_snapshot` rather than failing if resources
  are unavailable.
- Review retrieval/fallback responses expose correct `degraded_mode`.
- `get_publication_passages(dry_run=true)` returns budget/coverage estimates and
  no passage text.
- Resolver chain records each attempted resolver and stops after first
  section-level success.
- `verbosity="lean"` omits empty/null bulky fields.
- Review-oriented MCP citation defaults include NLM citation lines.
- Guideline boost ranks the Ozen EULAR FMF query ahead of general reviews when
  fixture data contains both.
- Entity synonym extraction strips markup and deduplicates synonyms.
- Active docs/resources do not advertise `_v2` aliases or `prepare_mode`
  examples outside compatibility notes.

## Rollout

Implement in five tasks:

1. **Diagnostics and degradation contract**
   - Add response/error fields and tests.
   - Add bounded diagnostics snapshot helpers.
   - Add MCP notices where tool context is available.

2. **Coverage resolver chain**
   - Add structured fallback attempts and coverage reasons.
   - Use Europe PMC/DOI structured paths before abstract fallback.

3. **Payload and citation ergonomics**
   - Add `verbosity`.
   - Add passage dry-run.
   - Normalize review citation defaults.

4. **Search quality**
   - Add guideline ranking reasons and boosts.
   - Populate bounded entity synonyms.

5. **Cleanup and docs**
   - Remove stale `_v2` and `prepare_mode` guidance.
   - Update capabilities and MCP connection guide.
   - Run `make ci-local`, rebuild Docker, and verify `/ready` and `/metrics`.

## Risks

- Internal fallback previews could grow too large. Keep them count-only unless
  the caller explicitly asks for passage text.
- DOI/publisher paths can become brittle. Restrict this slice to structured,
  stable APIs and keep attempt telemetry explicit.
- Changing MCP defaults can increase token use. Pair citation defaults with
  `verbosity` and dry-run so clients can control budgets.
- Entity synonyms can introduce noisy aliases. Use only explicit upstream or
  curated source fields, never model-inferred synonyms.

## Success Criteria

- A future `review_index_unavailable` run tells the user and LLM exactly what
  degraded mode was used and why.
- The LLM does not need a separate diagnostics call to understand a review index
  failure.
- More PMID sources reach `[PASSAGE]` instead of `[METADATA]` through structured
  PMC/DOI/Europe PMC fallback.
- Default MCP outputs are materially smaller in `lean` mode while preserving
  citation-grade lines for review workflows.
- Guideline-specific searches reliably prioritize consensus/recommendation
  papers.
- `make ci-local` passes and Docker can be rebuilt/restarted cleanly.
