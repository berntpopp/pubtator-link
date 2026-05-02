# Remaining Scientific Review Roadmap Design

Date: 2026-05-01

## Purpose

This design specifies the remaining roadmap items from
`docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`
after the scientific-auditability and source-resilience foundation. The current
foundation already includes source preflight, resolver attempts, retry/backoff,
bounded retrieval and preflight concurrency, passage addressability, and audit
bundle export. The next work should make the existing public surfaces easier for
MCP clients to validate, make review indexes operationally manageable, and add
stored scientific judgments without claiming to compute them.

## Goals

- Add precise typed MCP output schemas for high-use tools while preserving
  response JSON compatibility.
- Add review index inventory and TTL cleanup so local and hosted deployments can
  understand and manage stored indexes.
- Add GRADE-style evidence certainty storage for user/client-supplied judgments
  linked to prepared passages.
- Add optional Europe PMC fallback behind explicit configuration, rate limits,
  and open-access constraints.
- Remove public `candidate_fast` prepare mode for now because it has no real
  behavior. Reintroduce a fast-candidate workflow later only with explicit search
  candidate inputs and measurable semantics.

## Non-Goals

- Do not implement product code in this planning slice.
- Do not change existing REST response shapes incompatibly.
- Do not compute GRADE certainty, risk of bias, or clinical recommendations in
  the backend.
- Do not enable Europe PMC fallback by default.
- Do not expose destructive review index deletion on hosted/public deployments
  by default.
- Do not add publisher scraping or arbitrary web full-text discovery.

## Recommended Sequencing

### Phase 1: Typed MCP Output Schemas And Review Index Lifecycle

Start with typed MCP output schemas for high-use tools, then add review index
inventory and TTL cleanup. These changes improve client reliability and hosted
operability without changing how evidence is retrieved or interpreted.

Phase 1 should be one implementation plan because typed inventory tools and
schema tests share the MCP facade and model/test surfaces.

### Phase 2: GRADE-Style Evidence Certainty Storage

Add storage and public surfaces for user/client-supplied certainty judgments
after Phase 1. This is a scientific data-model change and should be separate
from operational lifecycle work.

### Phase 3: Europe PMC Fallback And `candidate_fast` Public Cleanup

Add optional Europe PMC fallback only after the resolver/audit foundation and
lifecycle cleanup are stable. In the same phase, remove `candidate_fast` from
public API schemas and docs. The removal is intentionally paired with fallback
work because both touch preparation source policy and public preparation
semantics.

## Roadmap Item 1: Typed MCP Output Schemas

### User-Facing Behavior

MCP clients should see concrete output schemas for high-use tools instead of
generic object responses. Tool call JSON values remain backward compatible:
existing keys and nested shapes stay the same, while schemas become
discoverable and machine-verifiable.

Prioritized tools:

- `pubtator.search_literature`
- `pubtator.preflight_review_sources`
- `pubtator.index_review_evidence`
- `pubtator.inspect_review_index`
- `pubtator.retrieve_review_context`
- `pubtator.retrieve_review_context_batch`
- `pubtator.get_review_passages_by_id`
- `pubtator.get_neighboring_review_passages`
- `pubtator.export_review_audit_bundle`

### REST/MCP Surface Changes

REST routes already use typed `response_model` declarations for review routes and
should remain unchanged except where new lifecycle or certainty routes are
introduced later. MCP tool functions should return Pydantic response models or
use explicit FastMCP output-schema registration while keeping flat input
arguments.

`export_review_audit_bundle` currently wraps the bundle as
`{"success": true, "audit_bundle": ...}` in MCP while the REST route returns the
bundle itself. Add a typed MCP wrapper model for that shape instead of changing
the JSON.

### Model/Schema Changes

Add MCP-specific wrapper response models only where MCP intentionally differs
from REST. Reuse existing models from `pubtator_link/models/review_rerag.py` for
review tools. Add literature response models for `search_literature` if the
current service adapter still returns raw dictionaries from PubTator.

Expected model additions:

- `McpReviewAuditBundleResponse`
- `SearchLiteratureResponse`
- `SearchLiteratureResult`
- `SearchLiteratureMetadata`

### Migration And Backward Compatibility

No database migration is required. Existing MCP JSON responses must remain
compatible. If FastMCP serializes returned Pydantic models directly, verify that
date/time, enum, and nested model output match the previous `model_dump()` JSON
mode where clients depend on strings.

### Tests Required

- MCP facade tests proving high-use tools expose non-generic output schemas.
- Adapter tests proving returned values match the current JSON keys.
- Snapshot-style schema assertions for key nested properties such as
  `preparation_status`, `sources`, `merged_context_pack`, `passages`,
  `coverage_hints`, and `audit_bundle`.
- Regression tests that flat input schemas do not reintroduce `request`
  envelopes.

### Verification Commands

- `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py -q`
- `make ci-local`

### Risks And Open Questions

- FastMCP may require explicit `output_schema` metadata rather than inferring
  schemas from return annotations in the current version.
- Some raw PubTator search fields may be inconsistent. The response model should
  keep an `extra` or `raw` field rather than dropping upstream data.
- Returning Pydantic models from MCP tool functions may alter serialization. The
  implementation must test actual tool metadata and adapter output.

## Roadmap Item 2: Review Index Inventory And TTL Cleanup

### User-Facing Behavior

Operators and local users can list review indexes, inspect high-level index
metadata without loading passage samples, and rely on configurable cleanup of
stale indexes. Public hosted deployments keep destructive deletion disabled by
default.

Expected behavior:

- `list_review_indexes` returns review IDs, created/updated times, source
  counts, passage counts, failure counts, preparation status, approximate bytes,
  and optional expiry metadata.
- `get_review_index_summary` returns one review's inventory-level summary.
- TTL cleanup removes stale review data only when configured.
- Manual deletion is available only when enabled in configuration.

### REST/MCP Surface Changes

Add REST routes:

- `GET /api/reviews`
- `GET /api/reviews/{review_id}/summary`
- `DELETE /api/reviews/{review_id}` gated by config
- `POST /api/reviews/cleanup-expired` gated by config for local/private use

Add MCP tools:

- `pubtator.list_review_indexes`
- `pubtator.get_review_index_summary`

Do not expose `delete_review_index` as a public hosted MCP tool by default. If
the implementation supports it locally, register it only when
`enable_review_index_delete` is true.

### Model/Schema Changes

Add models:

- `ReviewIndexInventoryItem`
- `ListReviewIndexesResponse`
- `ReviewIndexSummaryResponse`
- `DeleteReviewIndexResponse`
- `CleanupExpiredReviewIndexesResponse`

Schema changes:

- Add `updated_at timestamptz not null default now()` to `reviews`, maintained
  when preparation jobs, passages, attempts, and audit events change.
- Add optional expiry metadata through either `reviews.expires_at` or a derived
  expiry based on `updated_at + configured TTL`. Prefer derived expiry first to
  avoid unnecessary writes.
- Add repository methods for listing, summary, delete cascade, and TTL cleanup.

### Migration And Backward Compatibility

Existing review rows without `updated_at` should backfill from `created_at`.
Derived TTL keeps existing rows valid. Deletion must cascade in a controlled
repository method or use foreign keys with explicit cascade only after tests
prove all child tables are covered.

### Tests Required

- Schema tests for `reviews.updated_at` and any indexes used for inventory.
- Repository tests for list ordering, counts, byte estimates, summary of a
  missing review, delete cascade, and TTL cleanup.
- Config tests proving destructive operations default to disabled.
- REST route tests for inventory and gated destructive endpoints.
- MCP facade tests proving hosted public tools do not include delete by default.

### Verification Commands

- `uv run pytest tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_facade.py -q`
- `make ci-local`

### Risks And Open Questions

- Approximate bytes can be expensive if computed from full passage text on every
  list call. Use database aggregate lengths with limits or document that the
  value is approximate.
- TTL cleanup must avoid deleting active reviews. Use `updated_at`, not only
  `created_at`.
- Hosted deployments need a policy decision for whether cleanup is background
  only, manually triggered by operators, or both.

## Roadmap Item 3: GRADE-Style Evidence Certainty Storage

### User-Facing Behavior

Clients can store and retrieve evidence certainty judgments for a review. The
backend stores supplied judgments and links them to passage IDs; it does not
infer certainty.

Each judgment captures:

- review ID
- outcome or question
- study design
- risk of bias notes
- inconsistency notes
- indirectness notes
- imprecision notes
- publication bias notes
- overall certainty label
- certainty rationale
- linked passage IDs
- creator/source metadata when supplied

### REST/MCP Surface Changes

Add REST routes:

- `POST /api/reviews/{review_id}/certainty`
- `GET /api/reviews/{review_id}/certainty`
- `GET /api/reviews/{review_id}/certainty/{certainty_id}`
- `DELETE /api/reviews/{review_id}/certainty/{certainty_id}` gated by the same
  local/private deletion policy as review lifecycle operations.

Add MCP tools:

- `pubtator.add_evidence_certainty`
- `pubtator.list_evidence_certainty`
- `pubtator.get_evidence_certainty`

Do not add an MCP delete tool for hosted public deployments.

### Model/Schema Changes

Add models:

- `EvidenceCertaintyLabel = "high" | "moderate" | "low" | "very_low" | "not_rated"`
- `EvidenceCertaintyRecord`
- `UpsertEvidenceCertaintyRequest`
- `EvidenceCertaintyResponse`
- `ListEvidenceCertaintyResponse`

Add table `review_evidence_certainty` with:

- `certainty_id uuid primary key`
- `review_id text not null references reviews(review_id)`
- `outcome text not null`
- `question text`
- `study_design text`
- note fields for GRADE domains
- `overall_certainty text not null`
- `certainty_rationale text`
- `passage_ids text[] not null default '{}'`
- `created_by text`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

### Migration And Backward Compatibility

This is additive. Existing audit bundle exports should include an empty
`evidence_certainty` list until records exist. Passage IDs should be validated
against the review index when strict validation is requested, but the default
should allow draft judgments that reference passages not yet indexed and mark
them as unresolved.

### Tests Required

- Model validation tests for certainty labels and non-empty outcome.
- Schema tests for the new table and indexes.
- Repository tests for add, list, get, update, and gated delete.
- Audit bundle tests proving certainty records are exported.
- REST and MCP tests proving stored values are returned unchanged.

### Verification Commands

- `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_repository.py tests/unit/test_review_audit.py tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_facade.py -q`
- `make ci-local`

### Risks And Open Questions

- Strict passage validation can block useful draft workflows. The plan should
  support unresolved linked passage IDs explicitly.
- Certainty labels are not universal across all evidence workflows. Use a narrow
  GRADE-compatible enum plus free-text rationale rather than over-modeling.
- Deleting certainty records is destructive and should use the same public-hosted
  policy as review index deletion.

## Roadmap Item 4: Optional Europe PMC Fallback

### User-Facing Behavior

When explicitly enabled, preparation may use Europe PMC open-access full-text
XML as a fallback after PubTator/PMC resolver paths. Inspection and audit output
show Europe PMC attempts, source kind, coverage reason, and any license/access
hint. When disabled, behavior is unchanged.

### REST/MCP Surface Changes

No new default public tool is required. Existing preflight, index, inspect, and
audit surfaces should reflect Europe PMC attempts when enabled. Capabilities
resources should document whether Europe PMC fallback is enabled in the running
server.

### Model/Schema Changes

The current `SourceKind` already includes `europe_pmc_jats`. Add configuration:

- `enable_europe_pmc_fallback: bool = False`
- `europe_pmc_base_url`
- `europe_pmc_rate_limit_per_second`
- `europe_pmc_timeout_seconds`
- `europe_pmc_max_concurrency`

Add a small Europe PMC client/service module that returns a typed resolver result
with open-access/license metadata and parsed passages.

### Migration And Backward Compatibility

No database migration is required if existing attempt metadata is sufficient.
Europe PMC must remain disabled by default so existing deployments and tests see
no behavior change.

### Tests Required

- Config tests proving the fallback is disabled by default.
- Client tests for open-access hit, not-open-access, not-found, timeout, and
  retryable transient failure.
- Preparation tests proving fallback order is deterministic and audit attempts
  are recorded.
- Capability-resource tests proving enabled/disabled status is visible.

### Verification Commands

- `uv run pytest tests/unit/test_review_rerag_config.py tests/unit/test_source_preflight.py tests/unit/test_full_text_preparation.py tests/unit/mcp/test_mcp_facade.py -q`
- `make ci-local`

### Risks And Open Questions

- Europe PMC rate limits and open-access metadata can change. Keep settings
  conservative and make the fallback opt-in.
- XML parsing may produce section labels that differ from PubTator/PMC. Preserve
  source kind and evidence tier so clients can distinguish provenance.
- Do not use Europe PMC to bypass license restrictions.

## Roadmap Item 5: `candidate_fast` Prepare Mode

### Decision

Remove `candidate_fast` from public API and MCP schemas in Phase 3. Do not
implement a real fast candidate mode in this roadmap.

### Justification

The current `candidate_fast` value is accepted by `IndexReviewEvidenceRequest`
but does not change queue behavior. A real fast mode would require a different
workflow: search candidates, score or filter top-N PMIDs, run cheap preflight,
apply stricter preparation timeouts, and report excluded candidates. The current
index endpoint accepts explicit PMIDs and curated URLs, so it lacks the search
candidate context needed to make `candidate_fast` meaningful.

Removing the public mode is the least misleading behavior. A later design can
introduce a separate `screen_review_candidates` or `index_search_candidates`
workflow with measurable latency and selection semantics.

### User-Facing Behavior

Clients see only `prepare_mode="selected"` or no `prepare_mode` enum in public
schemas. Requests that send `candidate_fast` receive a validation error with a
clear message. Documentation and capability resources stop mentioning
`candidate_fast`.

### REST/MCP Surface Changes

Update the shared `PrepareMode` type and any MCP parameter schema so
`candidate_fast` is absent. Keep the default behavior equivalent to today's
selected PMID indexing.

### Model/Schema Changes

Change `PrepareMode` to `Literal["selected"]` or remove the field from public
request models while keeping an internal default if needed for compatibility
with call sites. Prefer keeping the field with a single allowed value for one
release so clients get a precise validation error rather than an unknown field
change.

### Migration And Backward Compatibility

This is a minor public API tightening. It may break clients that send
`candidate_fast`, but those clients were receiving selected-mode behavior
without knowing it. The release note should call this out as removal of a
reserved no-op mode.

### Tests Required

- Model validation tests proving `candidate_fast` is rejected.
- MCP schema tests proving `candidate_fast` is not in the enum.
- Route tests proving default indexing still works.
- Capability/resource tests proving documentation does not advertise the mode.

### Verification Commands

- `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_review_rerag_mcp.py tests/test_routes/test_reviews.py -q`
- `make ci-local`

### Risks And Open Questions

- Some private clients may already send `candidate_fast`. The release note should
  state that it never had distinct behavior and has been removed to avoid false
  assumptions.
- A future real fast workflow should not reuse the old no-op name unless it has
  clearly documented search-input semantics.

## Review Memo Update

The review memo should be updated after these planning files are accepted to
clarify the three-phase sequence and the `candidate_fast` removal recommendation.
It should not mark any of these remaining roadmap items complete until product
code is implemented and `make ci-local` passes.
