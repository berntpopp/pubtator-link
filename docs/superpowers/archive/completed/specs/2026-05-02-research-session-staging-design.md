# Research Session Staging Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-02

## Purpose

PubTator-Link already has the reliability foundation called for by the May 1
reviews: source preflight, resolver attempts, retry/backoff, bounded
concurrency, passage addressability, typed MCP outputs, review lifecycle tools,
PRISMA-style audit bundles, GRADE-style certainty storage, and optional Europe
PMC fallback. The next useful product move is speed without opacity.

This design adds an explicit research-session staging workflow. A client can
turn a search query or known PMID list into a transparent session manifest that
records candidate PMIDs, source coverage hints, staging decisions, queued
preparation jobs, and terminal outcomes. Later retrieval can use the same
review index quickly, while users can still inspect exactly what was staged,
skipped, failed, or unavailable.

## Goals

- Add a session-level manifest for live research work that groups query text,
  candidate PMIDs, coverage hints, staging decisions, and review preparation
  status.
- Add an explicit REST and MCP staging call that can search, preflight, and queue
  selected candidates with bounded limits.
- Expose session status so LLM clients can decide whether to wait, retrieve
  available passages, or inspect failures.
- Reuse existing review index, preflight, queue, audit, and retrieval services
  instead of adding a parallel evidence store.
- Keep staging transparent: every candidate has a status, decision reason,
  coverage hint, and optional source/job result.

## Non-Goals

- Do not make every literature search automatically download or index full text.
- Do not introduce hidden answer synthesis, clinical recommendations, or
  patient-specific decision support.
- Do not bypass existing source policy. Staging uses PubTator, PMC/BioC,
  Europe PMC only when enabled, and explicit curated URLs only when supplied.
- Do not add a UI or full systematic-review workflow manager.
- Do not add a broad discovery graph in this slice; related/cited/reference and
  MeSH tools can come later.

## Recommended Approach

Use an explicit staging tool rather than implicit search side effects.

The tool accepts a `review_id`, optional `session_id`, optional `query`,
optional explicit `pmids`, and conservative staging limits. If a query is
provided, the service calls the existing PubTator search path, extracts top
candidate PMIDs, deduplicates them with explicit PMIDs, records the search run,
preflights candidates, chooses which ones to queue, enqueues preparation through
`ReviewPreparationQueue`, and stores a manifest. Status calls read the manifest
plus existing preparation status.

This is preferable to automatic search-time prefetch because it avoids surprise
network and storage work in hosted deployments. It is also preferable to a
separate cache-only system because it reuses the review index that downstream
retrieval already understands.

## Public Behavior

New REST routes:

- `POST /api/reviews/{review_id}/sessions/stage`
- `GET /api/reviews/{review_id}/sessions/{session_id}`
- `GET /api/reviews/{review_id}/sessions`

New MCP tools:

- `pubtator.stage_research_session`
- `pubtator.get_research_session_status`
- `pubtator.list_research_sessions`

The staging response returns:

- `session_id`
- `review_id`
- `query`
- `candidate_count`
- `queued_count`
- `skipped_count`
- `coverage_summary`
- `candidates`
- `preparation_status`
- `_meta.next_commands`

Candidate statuses:

- `candidate`
- `preflighted`
- `queued`
- `abstract_ready`
- `full_text_ready`
- `abstract_only`
- `metadata_only`
- `failed`
- `skipped`

Decision reasons:

- `selected_by_rank`
- `explicit_pmid`
- `duplicate`
- `over_candidate_limit`
- `coverage_unknown`
- `metadata_only`
- `preflight_failed`
- `already_indexed`
- `queue_rejected`

## Architecture

### Models

Add session request/response models to
`pubtator_link/models/review_rerag.py` because sessions are part of the
review-scoped evidence workflow and reuse existing `SourceCoverageHint` and
`PreparationStatus` models.

Core models:

- `StageResearchSessionRequest`
- `ResearchSessionCandidate`
- `ResearchSessionManifest`
- `StageResearchSessionResponse`
- `ResearchSessionStatusResponse`
- `ListResearchSessionsResponse`

### Storage

Add two tables to `pubtator_link/db/review_schema.sql`:

- `review_research_sessions`
- `review_research_session_candidates`

The session table stores the durable manifest header. The candidate table stores
one row per PMID, including rank, coverage hint JSON, status, decision reason,
and source/job metadata. This keeps session state queryable without duplicating
passage text.

### Repository

Extend `PostgresReviewReragRepository` with session methods:

- `upsert_research_session`
- `upsert_research_session_candidate`
- `list_research_sessions`
- `get_research_session`
- `update_research_session_candidate_status`

The repository remains the only writer for session tables.

### Service

Add `pubtator_link/services/research_session.py`.

Responsibilities:

- Normalize and deduplicate candidate PMIDs.
- Run PubTator search only when a query is supplied.
- Preflight candidates through `SourcePreflightService`.
- Choose candidates to queue based on `max_candidates`,
  `stage_full_text`, and coverage hints.
- Enqueue preparation through `ReviewPreparationQueue`.
- Persist the manifest and return status-oriented responses.

The service does not retrieve passages directly and does not generate
scientific conclusions.

### REST, MCP, And Resources

Add route functions in `pubtator_link/api/routes/reviews.py` so staging lives
next to existing review workflows. Add dependency wiring in
`pubtator_link/api/routes/dependencies.py`.

Add service-adapter functions in `pubtator_link/mcp/service_adapters.py` and MCP
tools in `pubtator_link/mcp/tools/review.py`. Update
`pubtator_link/mcp/resources.py` to include the staging workflow in the MCP
capability guidance.

## Error Handling

- Empty `query` and empty `pmids` is a validation error.
- Invalid PMIDs are rejected before search/preflight.
- Search timeout returns a normal API error and does not create a partial
  session.
- Per-PMID preflight failures are stored as candidate status `failed` with
  decision reason `preflight_failed`.
- Queue deduplication is not an error. The candidate is stored as
  `already_indexed` or `queued` depending on the queue result.
- Status reads return 404 when the session is missing for the review.

## Testing

Required tests:

- Pydantic model validation for request limits, status values, and manifest
  serialization.
- SQL schema tests for both session tables and indexes.
- Repository mapper tests for session and candidate rows.
- Service tests with fake search, fake preflight, and fake queue dependencies.
- REST route tests for stage, get status, and list sessions.
- MCP adapter/facade tests for tool registration, output schemas, and
  research-use safety language.
- Audit bundle test proving session manifests are exported or linked from the
  audit output.

## Acceptance Criteria

- A client can call one staging tool with a query and receive a manifest with
  candidate PMIDs, coverage hints, queued/skipped decisions, and next commands.
- A client can poll a session and see candidate statuses converge as preparation
  jobs finish.
- Staging never hides source behavior: skipped and failed candidates include
  explicit reasons.
- Existing `retrieve_review_context` and `retrieve_review_context_batch` work
  unchanged against the review index populated by staging.
- The audit bundle includes enough session metadata to reconstruct what was
  searched, selected, queued, skipped, and retrieved.

## Open Questions Resolved

- Staging is explicit, not automatic search-time side effect.
- Session IDs are server-generated when omitted, but callers may provide one for
  reproducible workflows.
- The first implementation stages only PMIDs, not arbitrary URLs; curated URLs
  remain supported through existing review indexing calls.
- Candidate selection is deterministic: explicit PMIDs first, then search rank,
  with stable de-duplication by PMID.

