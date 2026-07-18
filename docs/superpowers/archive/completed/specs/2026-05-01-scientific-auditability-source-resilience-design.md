# Scientific Auditability And Source Resilience Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-01

## Purpose

The next major PubTator-Link upgrade should improve scientific rigor and
auditability first, while also fixing the basic reliability and latency problems
that make audit trails incomplete or slow. The work should make source coverage
predictable before indexing, make fallback decisions explainable after indexing,
and let a reviewer or LLM client follow exact passages back to durable evidence.

This design is based on
`docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`
and keeps the existing `search -> index -> inspect -> retrieve` workflow.

## Goals

- Tell callers before indexing whether PMIDs are likely full text, abstract only,
  title only, unavailable, or unknown.
- Record every resolver attempt used during evidence preparation, including
  fallback source, terminal reason, retry count, status code, PMCID/DOI, and
  license/access hints when known.
- Add retry/backoff for idempotent upstream calls that support evidence
  discovery and preparation.
- Add bounded async parallelism for independent preflight and batch retrieval
  work, while preserving deterministic response ordering.
- Add exact passage lookup and neighboring-passage retrieval over the existing
  review index so audit trails can be followed without re-running search.
- Add an audit export foundation containing search, source, coverage, retrieval,
  passage ID, and citation-key metadata.
- Update the capability review after implementation and mark the completed
  roadmap items explicitly.

## Non-Goals

- Do not add default publisher page scraping or automatic arbitrary PDF
  extraction for hosted MCP behavior.
- Do not compute PRISMA compliance, GRADE certainty, clinical recommendations,
  or risk-of-bias judgments in the backend.
- Do not replace PubTator3 as the primary semantic source.
- Do not change existing public REST or MCP response fields incompatibly.
- Do not add broad systematic-review workflow management, collaboration, or UI
  features in this slice.

## Recommended Approach

Use a coverage-first audit foundation. Add explicit source-preflight models and
resolver-attempt models, then wire them into preparation, inspection, and later
audit export. Build retry/backoff at the HTTP/resolver layer so transient
failures are captured as evidence-source diagnostics instead of disappearing as
opaque failures. Add bounded concurrency only where source calls or retrieval
queries are independent, with deterministic output sorting by input order.

This approach is preferable to speed-first work because faster retrieval alone
does not explain why evidence is abstract-only or missing. It is also preferable
to schema-first work because precise output schemas should reflect the richer
audit fields introduced here.

## Architecture

### Source Preflight

Add a small source-preflight service that accepts PMIDs and returns one
`SourceCoverageHint` per PMID. It should call lawful APIs only:

1. PubTator full BioC availability probe where cheap enough.
2. PMC ID Converter for PMID to PMCID/DOI/MID metadata.
3. BioC-PMC availability probe for PMIDs/PMCIDs.
4. Optional PMC OAI-PMH metadata probe for license/reuse hints.
5. PubTator abstract/metadata fallback classification.

The preflight result is expected coverage, not a guarantee. Inspection after
indexing remains the source of actual coverage.

### Resolver Attempts

Represent every preparation attempt with a typed model such as
`ResolverAttemptSummary`. Existing `full_text_retrieval_attempts` should be
extended rather than replaced. Attempt rows should capture enough information to
answer: which source was tried, how many attempts were made, what failed or
succeeded, whether `Retry-After` was used, and why the cascade stopped.

### Retry And Backoff

Add a reusable retry policy for idempotent upstream calls. The first scope should
cover PubTator export, PMC ID Converter, BioC-PMC, PMC OAI-PMH, search,
autocomplete, and relations. Text annotation submit remains excluded unless a
later design handles idempotency uncertainty.

Retry status codes: `408`, `429`, `500`, `502`, `503`, `504`.

Use exponential backoff with full jitter, respect `Retry-After`, and expose
attempt metadata to resolver summaries when preparation or preflight depends on
the call.

### Bounded Parallelism

Use conservative semaphores per upstream class:

- PubTator API.
- PMC ID Converter.
- BioC-PMC.
- PMC OAI-PMH.
- Europe PMC if enabled later.

For `retrieve_review_context_batch`, run independent query retrieval concurrently
behind a low default concurrency limit and then merge in original query order.
For preflight, batch PMC ID Converter requests where supported and bound per-host
checks for BioC-PMC/OAI-PMH.

### Passage Addressability

Add repository methods and public tools for audit follow-up:

- `get_review_passages_by_id(review_id, passage_ids, max_chars_per_passage,
  include_metadata)`
- `get_neighboring_review_passages(review_id, passage_id, before, after,
  same_section, max_chars_per_passage)`

These methods read only from the existing review index. They must not perform new
network retrieval.

### Audit Bundle Foundation

Add an audit export service that can assemble a JSON bundle from persisted review
state. The first version should include review ID, preparation status, source
summaries, resolver attempts, coverage distribution, retrieval query metadata,
passage IDs, stable citation keys, and generated timestamp. Markdown export can
be a later task in the same plan if the JSON foundation is stable.

## Public Surface

Additive MCP/REST behavior is acceptable in this upgrade. Existing fields should
remain backward compatible.

New or extended public surfaces:

- `pubtator.preflight_review_sources`
- Optional `include_coverage_hints` on `pubtator.search_literature` if cheap
  search-result metadata supports it.
- Coverage summary fields on `pubtator.index_review_evidence` responses when a
  preflight was run.
- Additional inspection fields: `coverage_reason`, `pmcid`, `doi`,
  `license_or_access_hint`, `pmc_fallback_available`, and resolver attempts.
- `pubtator.get_review_passages_by_id`
- `pubtator.get_neighboring_review_passages`
- `pubtator.export_review_audit_bundle`

REST route equivalents may be added for parity if they follow the existing
review route style and preserve current routes.

## Data Model

Add model concepts:

- `CoverageReason`: enum-like string values such as `full_text_available`,
  `abstract_fallback_used`, `no_pmcid`, `pmc_not_open_access`,
  `license_reuse_unavailable`, `upstream_timeout`, `upstream_404`,
  `parser_unsupported`, `blocked_source`, and `unknown`.
- `SourceCoverageHint`: expected coverage, PMID, PMCID, DOI, fallback flags,
  license/access hint, reason, and attempts.
- `ResolverAttemptSummary`: source kind, status, attempt count, last status code,
  retry-after milliseconds, backoff milliseconds, terminal reason, elapsed
  milliseconds, URL/source ID, PMCID/DOI where known.
- `EvidenceTier`: passage-level tier derived from actual source kind and
  coverage, such as `PASSAGE_FULL_TEXT`, `PASSAGE_ABSTRACT`, `METADATA_TITLE`,
  `CURATED_FULL_TEXT`, and `UNVERIFIED_EXTERNAL`.
- `ReviewAuditBundle`: deterministic export structure for review source and
  retrieval provenance.

Persist new fields in existing review tables where practical. Add new tables only
for data with different cardinality, such as retrieval run audit rows.

## Error Handling

- Validation errors, `401`, `403`, and ordinary `404` responses should not be
  retried unless a specific resolver has a documented reason.
- Transient retry exhaustion should produce a terminal resolver reason and a
  failed or unknown coverage hint, not an uncategorized exception.
- Preflight failures should degrade per PMID. One bad PMID or one upstream error
  must not fail the whole batch if other PMIDs can be classified.
- Parallel retrieval failures should preserve query order and attach diagnostics
  to the failed query where possible.

## Testing Strategy

Use TDD per task. Prefer focused unit tests before implementation and `make
ci-local` before completion.

Key test areas:

- Preflight classifications: full-text likely, abstract-only likely, no PMCID,
  unavailable PMC, timeout, upstream 429/503, and unknown.
- Retry policy: `Retry-After`, jitter/backoff bounded by policy, retry
  exhaustion, success after retry, and non-retryable status.
- Preparation attempts: fallback order, actual coverage reason, attempt metadata,
  and inspection output.
- Batch retrieval concurrency: deterministic ordering, bounded scheduling, and
  unchanged merged context semantics.
- Passage addressability: exact lookup, not-found diagnostics, same-section
  neighbors, ordering, truncation, and metadata toggle.
- Audit bundle: stable JSON shape, coverage distribution, resolver attempts,
  retrieval queries, passage IDs, and citation keys.
- MCP facade/schema tests for all new tools.

## Rollout

Implement in small commits:

1. Models and schema extensions.
2. Retry policy and client coverage for existing PubTator calls.
3. Preflight clients/services.
4. Preparation resolver cascade and inspection fields.
5. Bounded batch retrieval concurrency.
6. Passage addressability.
7. Audit bundle export.
8. Documentation updates, including marking completed items in the review memo.

Run focused tests after each task and `make ci-local` at plan completion.

