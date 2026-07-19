# Review Scope And Lifecycle Hardening Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-02

## Purpose

Fix the remaining high-risk review-index lifecycle problems for LLM-driven
literature reviews:

- prevent ambiguous cross-session evidence reuse,
- make indexing completion optionally synchronous for small corpora,
- stop durable duplicate reprocessing,
- expose non-mutating index cost/queue estimates,
- preserve auditability without exposing destructive hosted MCP operations.

This is the first implementation slice because session/index ambiguity is a
hard correctness and audit-risk issue.

## Goals

- Keep existing `review_id` behavior backward compatible.
- Add optional `session_id` scoping to review evidence preparation, inspection,
  retrieval, and audit export.
- Guarantee that session-scoped retrieval cannot return PMIDs outside that
  session.
- Let callers wait for a chosen indexing status without modeling polling loops.
- Make duplicate source enqueue semantics durable, not just in-memory.
- Add `wait_for_completion` with bounded timeout to `index_review_evidence`.
- Add `dry_run` to `index_review_evidence`.
- Remove or deprecate the dead public `prepare_mode` argument.
- Keep public hosted MCP non-destructive.

## Non-Goals

- No backend LLM.
- No clinical decision support or generated medical classifications.
- No destructive public MCP delete operation.
- No migration to experimental MCP Tasks/SSE in this slice. MCP task support is
  available in newer protocol revisions, but a flat optional wait flag is safer
  for current clients.

## Current State

Solved:

- Database tables and repository reads are keyed by `review_id`.
- Research session tables are keyed by `(review_id, session_id)`.
- `list_review_indexes`, `get_review_index_summary`, REST delete, and REST
  cleanup exist.
- Audit bundle export exists.

Remaining gaps:

- Retrieval is review-scoped only; staged research sessions do not constrain
  retrieval results.
- `index_review_evidence` returns immediately and forces poll/inspect loops.
- Completed sources can be requeued after leaving the in-memory queue.
- `already_prepared` currently means "already in memory queue", not "durably
  complete or already present".
- `index_review_evidence` has no dry-run path.

## Public Surface

### `session_id`

Add optional `session_id: str | None = None` to:

- `pubtator.index_review_evidence`
- `pubtator.inspect_review_index`
- `pubtator.retrieve_review_context`
- `pubtator.retrieve_review_context_batch`
- `pubtator.get_review_passages_by_id`
- `pubtator.get_neighboring_review_passages`
- `pubtator.export_review_audit_bundle`

REST equivalents add `session_id` in request bodies or query parameters, matching
the existing route style.

Behavior:

- Omitted `session_id`: preserve current review-wide behavior.
- Provided `session_id`: only sources/passages associated with that session are
  visible.
- Unknown session: return a typed not-found/recovery error rather than silently
  falling back to review-wide retrieval.
- Session-scoped audit bundles include only session candidates, sources,
  passages, retrieval runs, and certainty records linked to that session where
  possible.

### `index_review_evidence`

Add fields:

```json
{
  "session_id": "fmf-phase-1",
  "wait_for_completion": true,
  "wait_for_status": "complete_or_partial",
  "timeout_ms": 30000,
  "dry_run": false
}
```

Response additions:

```json
{
  "dry_run": false,
  "waited_ms": 1240,
  "timed_out": false,
  "estimated_queue_position": 0,
  "estimated_source_count": 3,
  "already_indexed": 2,
  "already_queued": 1,
  "newly_queued": 0
}
```

Semantics:

- `dry_run=true` performs validation and durable status checks only; it does not
  enqueue or mutate.
- `wait_for_completion=true` waits until all requested sources for the selected
  scope are terminal or timeout expires.
- `wait_for_status` is more explicit and should be preferred over
  `wait_for_completion` once added. Allowed values:
  - `complete`: all requested sources are complete,
  - `complete_or_partial`: all requested sources are terminal and at least one
    source produced usable passages,
  - `terminal`: all requested sources are complete, partial, or failed.
- `timeout_ms` default is conservative, e.g. `0`/no wait unless
  `wait_for_completion=true`; max should be bounded, e.g. 120 seconds.
- If timeout expires, return current status with `timed_out=true` and
  `retry_after_ms`.

### Retrieval Preparation Status

Add to `retrieve_review_context` and `retrieve_review_context_batch` responses:

```json
{
  "prepared_pmids": ["33454820"],
  "still_preparing_pmids": ["37298536"],
  "failed_pmids": ["40562663"]
}
```

These lists should be scoped by `review_id` and optional `session_id`. They let
LLM consumers reason about partial retrieval results without re-querying the
index or inferring state from dropped passages.

## Data Model

Add a session-source link table instead of duplicating passages:

```sql
create table if not exists review_session_sources (
    review_id text not null,
    session_id text not null,
    source_id text not null,
    created_at timestamptz not null default now(),
    primary key(review_id, session_id, source_id),
    foreign key(review_id, session_id)
        references review_research_sessions(review_id, session_id),
    foreign key(review_id, source_id)
        references review_preparation_jobs(review_id, source_id)
);
```

Repository queries that accept `session_id` join through this table. This keeps
passage storage DRY and makes one prepared source reusable across sessions only
when explicitly linked.

## Durable Dedup

`enqueue_preparation_job` should return an enum-like result:

- `newly_queued`
- `already_queued`
- `already_running`
- `already_indexed`
- `previously_failed_requeued`

Completed/partial sources should not be requeued by default. A later explicit
`force_reindex` option can be designed separately if needed.

## `prepare_mode` Cleanup

`prepare_mode` is currently a public const-like argument with only `"selected"`.
It costs schema tokens and implies unavailable modes.

Plan:

1. Stop advertising `prepare_mode` in MCP tool descriptions and sample calls.
2. Keep accepting `prepare_mode="selected"` temporarily for compatibility.
3. Add structured capability metadata marking it deprecated:

```json
{
  "name": "prepare_mode",
  "status": "deprecated",
  "replacement": "omit",
  "removal_after": "next_minor"
}
```

4. Remove the argument from public schemas in a later compatibility cleanup, or
   only keep it on REST if needed for older clients.

## Error Handling

- Unknown `session_id`: `session_not_found`.
- Session has zero linked sources: success with empty results plus `next_steps`.
- Queue unavailable: existing `review_queue_unavailable` recovery envelope.
- Timeout waiting: success with `timed_out=true`, not a tool error.

## Testing

Required tests:

- repository tests proving session-scoped search cannot return non-session PMIDs,
- queue tests for durable dedup return values,
- route/MCP adapter tests for `wait_for_completion`, timeout, and `dry_run`,
- audit bundle tests for session-scoped export,
- regression test for unknown session not falling back to review-wide data.

## Documentation

Update workflow help:

1. stage or choose candidate PMIDs,
2. index with optional `session_id`,
3. use `wait_for_completion=true` for small corpora,
4. retrieve with the same `session_id`,
5. export the audit bundle before synthesis.

Tool descriptions should be functional and short. The global research-use notice
belongs once in server instructions/capabilities, not repeated in every tool
description.

Capabilities and workflow help should also promote
`pubtator.find_entity_relations` as the follow-on tool after entity grounding
when the caller needs PubTator relation evidence before choosing search terms or
candidate PMIDs. Keep it in the discovery/entities group and include a concise
sample call keyed by `entity_id` and `relation_type`.

Section names used for retrieval filters, indexed passage metadata, available
section diagnostics, and workflow examples should use lowercase canonical
section names. Normalize incoming section labels before storage/querying so
values such as `Abstract`, `RESULTS`, and `Methods & Results` cannot create
parallel taxonomy entries or missed session-scoped retrieval matches.
