# Correctness and Performance Score Sprint Design

Date: 2026-05-13
Status: Written for user review

## Goal

Raise PubTator-Link from the current 7.6/10 review score to above 8/10 by
prioritizing correctness, runtime speed, and performance. The sprint targets
known high-impact issues rather than broad cosmetic refactoring.

## Success Criteria

- `make ci-local` passes.
- `make test-cov` stays at or above the existing 80% threshold.
- Public or hosted deployments no longer expose misleading or unintended cache
  clear behavior.
- Review preparation no longer holds a PostgreSQL transaction or pooled
  connection while waiting on upstream PubTator, Europe PMC, URL fetch, parser,
  or embedding work.
- MCP annotations accurately distinguish idempotent writes from non-idempotent
  writes.
- Review audit rows capture real retry metadata where the PubTator client has
  retry information.
- Batch publication export correctly counts and returns exported documents.
- Focused tests lock in each corrected behavior.

## Non-Goals

- No full dependency-injection rewrite.
- No large split of `pubtator_link/mcp/service_adapters.py` or
  `pubtator_link/repositories/review_rerag.py`.
- No new authentication framework.
- No change to biomedical retrieval semantics beyond the listed correctness
  fixes.
- No performance benchmark harness beyond lightweight regression tests for the
  changed paths.

## Approach

Use a correctness and performance sprint:

1. Fix concrete behavior defects first.
2. Narrow database critical sections around review preparation.
3. Preserve existing public APIs where possible, but prefer explicit failure over
   misleading behavior.
4. Add small tests beside the code being changed.
5. Run the full local CI and coverage checks before completion.

This is intentionally smaller than a broad architecture cleanup. It should raise
the practical quality score quickly while reducing the highest operational risks.

## Workstream 1: Cache Endpoint Safety and Semantics

### Problem

`PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS` exists, but the cache router is mounted
unconditionally. The REST cache clear endpoint advertises selective clearing by
pattern, while `PublicationService.clear_cache()` clears all async-lru caches
regardless of the pattern and returns configured capacity rather than actual
items cleared.

### Design

- Make `UnifiedServerManager.create_app()` include `cache_router` only when
  `settings.enable_cache_endpoints` is true.
- Keep the existing setting name.
- Set `enable_cache_endpoints` to false by default. Tests and development docs
  should opt in explicitly when cache endpoints are needed.
- Change `PublicationService.clear_cache(pattern=None)` to count current cache
  entries before clearing and return the actual count cleared.
- Reject non-empty `pattern` in the route with HTTP 400 until real scoped
  invalidation exists. This is more correct than pretending to clear a subset.
- Update route documentation and tests so clients know the endpoint clears all
  enabled caches only.

### Acceptance Tests

- A server created with `settings.enable_cache_endpoints = False` returns 404 for
  `/api/cache/stats` and `/api/cache/clear`.
- A server created with the flag true exposes existing cache stats.
- `DELETE /api/cache/clear?pattern=pub_export:*` returns 400 with a message that
  pattern clearing is unsupported.
- Full clear returns the actual number of cached entries present before the
  clear.

## Workstream 2: Review Preparation Lock and Pool Pressure

### Problem

`PostgresReviewReragRepository.with_preparation_lock()` holds a transaction and
transaction-scoped advisory lock while awaiting a callback. The callback performs
slow upstream fetches, parsing, optional fallback retrieval, passage writes, and
embedding generation. This pins a pooled database connection during network and
CPU work.

### Design

Replace callback-under-lock with short repository operations:

- Add a repository method named `claim_preparation_job(review_id, source_id)`.
- The claim method should:
  - acquire a connection;
  - start a short transaction;
  - take the same advisory lock;
  - atomically move the job to `running` only if it is still claimable;
  - commit and release the connection before any upstream work starts.
- The worker should:
  - claim the job;
  - skip work if another worker or process already claimed it;
  - run `prepare_pmid()` or `prepare_curated_url()` outside the DB transaction;
  - call `mark_job_finished()` after the work returns or fails.
- Keep `mark_running_jobs_failed_on_startup()` as the crash repair mechanism.
- Remove `with_preparation_lock()` from the repository protocol and concrete
  repository after queue tests move to the claim model.

### Data Flow

1. `ReviewPreparationQueue._worker()` receives `(review_id, source_id, source_kind, source_value)`.
2. Worker calls `repository.claim_preparation_job(...)`.
3. Repository uses a short transaction to guard the state transition.
4. Worker performs network and parsing work without holding a DB connection.
5. Preparation service writes passages and attempts through existing repository
   methods, each with their own short acquire.
6. Worker marks the job terminal.

### Acceptance Tests

- A fake repository records event order and proves preparation starts only after
  claim transaction completion.
- If `claim_preparation_job()` returns false, the worker does not call the
  preparation service.
- Two queued jobs with a slow fake preparation service can run concurrently when
  `prep_concurrency=2`.
- Existing timeout and failure paths still mark jobs failed.

## Workstream 3: MCP Write Idempotency Semantics

### Problem

`REVIEW_WRITE_ANNOTATIONS` declares `idempotentHint=True` for all review writes.
Some tools are not idempotent. `pubtator_add_evidence_certainty` creates a new
UUID when no certainty ID is supplied. `pubtator_record_review_context` appends
new context and event records.

### Design

- Add separate annotation constants:
  - `IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS`
  - `NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS`
- Keep idempotent annotations for operations that dedupe naturally, such as
  review evidence indexing.
- Use non-idempotent annotations for append/create operations where retrying can
  create additional records.
- Do not introduce dynamic per-argument annotations. MCP annotations are static,
  so ambiguous write tools should be marked non-idempotent.

### Acceptance Tests

- `pubtator_add_evidence_certainty` has `readOnlyHint=False` and
  `idempotentHint=False`.
- `pubtator_record_review_context` has `readOnlyHint=False` and
  `idempotentHint=False`.
- `pubtator_index_review_evidence` keeps its existing write annotation semantics
  because queue and repository behavior deduplicate by review/source IDs.

## Workstream 4: Retry Metadata Integrity

### Problem

The PubTator client receives retry metadata from `call_with_retries()` but
discards it. Review preparation later attempts to read
`pubtator_client.last_retry_metadata`, so audit rows usually record default
attempt metadata rather than actual retry behavior.

### Design

- Add `last_retry_metadata` to `PubTator3Client`.
- Set it for every `_make_request()` call:
  - retrying GET calls use the metadata returned by `call_with_retries()`;
  - non-retried calls record one attempt;
  - exhausted retry responses preserve `terminal_reason="retry_exhausted"`;
  - exhausted retried request errors record `attempt_count=policy.max_attempts`
    and `terminal_reason="request_error"`;
  - non-retried request errors record one attempt and
    `terminal_reason="request_error"`.
- Keep the field internal to the client; do not expose it in public REST
  response models.
- Keep `FullTextPreparationService._last_retry_metadata()` as the adapter point,
  but make it reliably receive real metadata from the client.

### Acceptance Tests

- A GET that succeeds after retry sets `last_retry_metadata.attempt_count` to the
  actual number of attempts.
- A retry-exhausted response records `terminal_reason="retry_exhausted"`.
- `FullTextPreparationService.prepare_pmid()` records the retry metadata in
  `record_retrieval_attempt()`.
- Non-retried POST text-annotation calls still record one attempt internally.

## Workstream 5: Batch Export Correctness

### Problem

`batch_export_publications()` treats `PublicationExportResponse` as if it had a
top-level `documents` attribute. The response actually stores documents in
`export_data["documents"]`. The current path can silently produce empty
successful batches.

### Design

- Read documents from `result.export_data["documents"]` when the result is a
  `PublicationExportResponse`.
- Keep partial failure accounting through `asyncio.gather(..., return_exceptions=True)`.
- Count successfully exported documents, not batches.
- Keep the method in this sprint. Later cleanup can remove it only through a
  separate deprecation or API-removal decision.

### Acceptance Tests

- Two successful internal batches return publications for all exported
  documents.
- One failed batch and one successful batch returns successful publications and
  increments `error_count`.
- Empty input returns a completed batch with zero successes and zero errors.

## Workstream 6: Focused Performance Verification

### Problem

The current suite is broad, but it does not explicitly guard the highest-risk
performance behavior: long review preparation work must not pin DB transactions
or block independent jobs.

### Design

- Add lightweight async unit tests rather than a new benchmark framework.
- Use fakes with `asyncio.Event` or short sleeps to verify concurrency and event
  ordering deterministically.
- Keep tests under `tests/unit/`.
- Do not hit live PubTator, Europe PMC, or PostgreSQL in these tests.

### Acceptance Tests

- Review preparation worker concurrency test completes in less than the serial
  sum of fake delays.
- Repository fake shows no "transaction open" marker during fake network work.
- Existing route and MCP tests still pass.

## Expected Score Impact

| Area | Current | Target After Sprint | Reason |
| --- | ---: | ---: | --- |
| Correctness | 7/10 | 8.2/10 | Fixes concrete behavior bugs and audit integrity. |
| Speed/performance | 7/10 | 8/10 | Removes long DB connection hold during review prep. |
| MCP/LLM tool design | 8/10 | 8.4/10 | Correct write semantics and safer retry behavior. |
| Security/ops | 7/10 | 8/10 | Cache clear exposure becomes explicit and honest. |
| Architecture/modularization | 6.5/10 | 7/10 | Narrower critical sections without broad refactor. |
| Overall | 7.6/10 | 8.2/10 | High-impact defects are resolved with focused tests. |

## Test and Verification Plan

Focused commands during implementation:

```bash
uv run pytest tests/test_routes/test_cache.py -q
uv run pytest tests/unit/test_review_preparation_queue.py -q
uv run pytest tests/unit/test_pubtator_client_retry.py -q
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
uv run pytest tests/test_services.py -q
```

Final commands before completion:

```bash
make ci-local
make test-cov
```

Database-backed integration tests remain opt-in unless
`PUBTATOR_LINK_TEST_DATABASE_URL` is configured.

## Risks and Mitigations

- Cache endpoint gating may break clients that relied on default exposure.
  Mitigation: document the flag and update tests to opt in explicitly.
- Changing review queue locking may affect multi-process behavior. Mitigation:
  keep the advisory lock inside the short claim transaction and preserve startup
  repair of orphaned running jobs.
- `last_retry_metadata` on a shared client is internal mutable state. Mitigation:
  read it immediately after awaited client calls and cover the intended audit
  path. A future stronger design can return structured transport metadata
  alongside raw API payloads.
- FastMCP annotation changes may affect client planning. Mitigation: tests assert
  exact annotation semantics for the changed tools.

## Implementation Ordering

1. Cache endpoint gating and honest clear semantics.
2. Batch export correctness.
3. Retry metadata integrity.
4. MCP write idempotency annotations.
5. Review preparation claim model and concurrency tests.
6. Full verification and documentation updates.

This order gets low-risk correctness fixes landed before the more delicate queue
and repository changes.
