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
- No incorrect dead batch publication export helper remains in the codebase.
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
- No broad split of MCP tool modules. MCP annotation changes are localized to
  `pubtator_link/mcp/annotations.py`, `pubtator_link/mcp/tools/review.py`, and
  targeted tests.

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
  should opt in explicitly when cache endpoints are needed. This is an accepted
  breaking behavior change because the existing default exposes a destructive
  operational route and the flag currently gives operators a false sense of
  control.
- Change `PublicationService.clear_cache(pattern=None)` to count current cache
  entries before clearing and return the actual count cleared.
- Reject non-empty `pattern` in the route with HTTP 400 until real scoped
  invalidation exists. This applies to every non-empty pattern, including known
  prefixes such as `pub_export:*` and unknown prefixes.
- Update route documentation and tests so clients know the endpoint clears all
  enabled caches only.
- When the flag is off, both `/api/cache/stats` and `/api/cache/clear` are absent
  and return FastAPI's normal 404 response.

### Acceptance Tests

- A server created with `settings.enable_cache_endpoints = False` returns 404 for
  `/api/cache/stats` and `/api/cache/clear`.
- A server created with the flag true exposes existing cache stats.
- `DELETE /api/cache/clear?pattern=pub_export:*` returns 400 with a message that
  pattern clearing is unsupported.
- `DELETE /api/cache/clear?pattern=unknown:*` also returns 400 with the same
  unsupported-pattern behavior.
- Full clear returns the actual number of cached entries present before the
  clear.
- Existing cache route tests are updated to opt in to cache endpoint exposure
  through settings override or a dedicated app fixture.

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
  - atomically move the job to `running` only if it is still queued;
  - commit and release the connection before any upstream work starts.
- The claim operation must use an atomic update contract equivalent to:

  ```sql
  update review_preparation_jobs
  set status = 'running',
      started_at = now(),
      error = null,
      updated_at = now()
  where review_id = $1
    and source_id = $2
    and status = 'queued'
  returning job_id
  ```

  A returned row means this worker owns the job. No row means another worker,
  process, or previous state transition owns it.
- The worker should:
  - claim the job;
  - skip work if another worker or process already claimed it;
  - run `prepare_pmid()` or `prepare_curated_url()` outside the DB transaction;
  - call `mark_job_finished()` after the work returns or fails.
- Remove the separate `mark_job_running()` call from
  `ReviewPreparationQueue._worker()`; claiming is the single state transition
  from queued to running.
- Keep `mark_running_jobs_failed_on_startup()` as the crash repair mechanism.
- Remove `with_preparation_lock()` from the repository protocol and concrete
  repository after queue tests move to the claim model.
- Keep the short advisory lock inside the claim transaction even though the
  status update is atomic. The lock is a conservative multi-process guard around
  the same `(review_id, source_id)` key while the codebase is transitioning away
  from callback-scoped locking.
- Do not add a periodic stale-job sweeper in this sprint. Running-job orphan
  repair remains startup-based, which matches the current queue's practical
  behavior after `mark_job_running()` succeeds. A periodic `started_at` cutoff is
  a follow-up operations improvement if long-lived processes need automatic
  recovery without restart.

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
- A repository-level test verifies that a queued job is claimed once and a second
  claim returns false without starting preparation.

## Workstream 3: MCP Write Idempotency Semantics

### Problem

`REVIEW_WRITE_ANNOTATIONS` declares `idempotentHint=True` for all review writes.
Some tools are not idempotent. `add_evidence_certainty` creates a new
UUID when no certainty ID is supplied. `record_review_context` appends
new context and event records. Six tools currently use this annotation and must
be classified.

### Design

- Add separate annotation constants:
  - `IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS`
  - `NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS`
- Keep idempotent annotations for operations with explicit deduplication,
  specifically review evidence indexing and ground-question indexing.
- Use non-idempotent annotations for append/create operations where retrying can
  create additional records.
- Classify the current tools as:
  - `add_evidence_certainty`: non-idempotent because it creates a new
    certainty UUID when the caller does not supply one.
  - `stage_research_session`: non-idempotent because it generates a new
    session ID when omitted and writes session/candidate rows.
  - `review_quickstart`: non-idempotent because it stages a research
    session and may generate a session ID through the stage service.
  - `record_review_context`: non-idempotent because it appends context
    and event records.
  - `index_review_evidence`: idempotent because review/source queueing
    and repository state deduplicate by `review_id` and source ID.
  - `ground_question`: idempotent for MCP retry purposes because the
    default review ID is deterministic from the question, indexing deduplicates
    selected sources, and the tool does not append research sessions or LLM
    context records.
- Do not introduce dynamic per-argument annotations. MCP annotations are static,
  so ambiguous write tools should be marked non-idempotent.

### Acceptance Tests

- `add_evidence_certainty` has `readOnlyHint=False` and
  `idempotentHint=False`.
- `stage_research_session` has `readOnlyHint=False` and
  `idempotentHint=False`.
- `review_quickstart` has `readOnlyHint=False` and
  `idempotentHint=False`.
- `record_review_context` has `readOnlyHint=False` and
  `idempotentHint=False`.
- `index_review_evidence` keeps its existing write annotation semantics
  because queue and repository behavior deduplicate by review/source IDs.
- `ground_question` keeps idempotent write annotation semantics and has
  a unit test documenting the rationale.

## Workstream 4: Retry Metadata Integrity

### Problem

The PubTator client receives retry metadata from `call_with_retries()` but
discards it. Review preparation later attempts to read
`pubtator_client.last_retry_metadata`, which is not set by the real client, so
audit rows currently receive empty metadata.

### Design

- Add a private sidecar-returning request path named
  `_make_request_with_metadata(...) -> tuple[dict[str, Any], RetryAttemptMetadata]`.
- Keep the public `_make_request()` behavior returning only `dict[str, Any]` by
  delegating to the sidecar path and discarding the metadata.
- Add `export_publications_with_metadata(...)` for audit-sensitive review
  preparation calls. Existing `export_publications(...)` delegates to it and
  returns only the payload.
- Build retry metadata for every sidecar request:
  - retrying GET calls use the metadata returned by `call_with_retries()`;
  - non-retried calls record one attempt;
  - exhausted retry responses preserve `terminal_reason="retry_exhausted"`;
  - exhausted retried request errors record `attempt_count=policy.max_attempts`
    and `terminal_reason="request_error"`;
  - non-retried request errors record one attempt and
    `terminal_reason="request_error"`.
- Update `FullTextPreparationService.prepare_pmid()` to call
  `export_publications_with_metadata()` when the client provides it. This avoids
  shared mutable state races between concurrent preparation jobs.
- Keep `FullTextPreparationService._last_retry_metadata()` only as compatibility
  fallback for test fakes or older clients.
- Do not expose retry metadata in public REST response models.

### Acceptance Tests

- A GET that succeeds after retry returns sidecar metadata with the actual
  attempt count.
- A retry-exhausted response records `terminal_reason="retry_exhausted"`.
- `FullTextPreparationService.prepare_pmid()` records the retry metadata in
  `record_retrieval_attempt()`.
- Two concurrent fake preparation jobs cannot overwrite each other's retry
  metadata because each export call receives metadata as a sidecar.
- Non-retried POST text-annotation calls through the sidecar request path record
  one attempt internally.

## Workstream 5: Dead Batch Export Removal

### Problem

`batch_export_publications()` treats `PublicationExportResponse` as if it had a
top-level `documents` attribute. The response actually stores documents in
`export_data["documents"]`. The current path can silently produce empty
successful batches. A repository grep confirms this method has no in-repo
callers outside its own definition and is not exposed through REST or MCP.

### Design

- Remove `PublicationService.batch_export_publications()` rather than fixing
  uncalled code.
- Remove any tests or docs that present the helper as supported if they appear
  during implementation.
- Keep `export_publications_list()` and route/MCP publication export behavior
  unchanged.
- Do not add new batch export tests; removal is verified by grep, type checking,
  and existing publication service tests.

### Acceptance Tests

- `rg "batch_export_publications\\(" pubtator_link tests` returns no production
  or test call sites after removal.
- `make typecheck-fast` passes without the removed method.
- Existing publication route and service tests pass.

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
  This break is accepted because the existing behavior exposes a destructive
  route despite a feature flag. Mitigation: document the opt-in flag, update
  tests to opt in explicitly, and mention the default change in the changelog or
  development docs.
- Changing review queue locking may affect multi-process behavior. Mitigation:
  keep the advisory lock inside the short claim transaction and preserve startup
  repair of orphaned running jobs.
- Running jobs can still be orphaned until restart if a worker dies after claim
  and before terminal status. Mitigation: document this residual risk and keep
  startup repair. Periodic stale-job repair is a follow-up, not part of this
  sprint.
- Retry metadata must not rely on shared mutable client state. Mitigation:
  sidecar-returning client methods provide metadata to the caller that performed
  the request.
- FastMCP annotation changes may affect client planning. Mitigation: tests assert
  exact annotation semantics for the changed tools.

## Implementation Ordering

1. Cache endpoint gating and honest clear semantics.
2. Dead batch export removal.
3. Retry metadata integrity.
4. MCP write idempotency annotations.
5. Review preparation claim model and concurrency tests.
6. Full verification and documentation updates.

This order gets low-risk correctness fixes landed before the more delicate queue
and repository changes.
