# MCP LLM Consumer Stabilization Design

## Goal

Stabilize PubTator-Link for repeated LLM-driven biomedical review workflows by fixing review-index schema drift, preventing raw backend errors at the MCP boundary, exposing deterministic recovery paths, reducing noisy search payloads, and adding corpus-selection signals before indexing.

## Background

Four independent LLM-consumer evaluations of the previous MCP version produced a consistent pattern:

- citation identity was reliable; no fabricated PMIDs were found,
- the documented workflow and flat MCP schemas were strong,
- review-scoped retrieval was blocked every run by `column "updated_at" of relation "reviews" does not exist`,
- search results were too verbose for first-pass corpus selection,
- LLM-chosen free-text search strings caused PMID drift,
- coverage was discovered too late, after a corpus had already been selected,
- landmark guideline and consensus papers did not rank reliably enough for clinical-genetics review prompts.

Local validation on 2026-05-02 confirms the central operational finding. The current code declares `reviews.updated_at`, but the live Docker PostgreSQL volume still has only `review_id` and `created_at`. Rebuilding and restarting the containers does not replay `/docker-entrypoint-initdb.d` scripts on an existing volume. The current `make db-init` target replays `CREATE TABLE IF NOT EXISTS` statements and therefore does not add missing columns or tables to existing databases.

## Design Principles

1. **Preserve data by default.** Existing review indexes, jobs, attempts, and passages should be migrated in place. Volume reset remains a last-resort local-development escape hatch, not the normal fix.
2. **Follow MCP error semantics.** REST should keep HTTP status codes. MCP tools should distinguish protocol errors from tool-execution errors and report tool-execution failures through MCP tool-error results, not raw Python or database exceptions.
3. **Expose corpus quality before corpus commitment.** Search and staging should surface coverage and canonical entity filters before an LLM spends turns indexing a weak corpus.
4. **Keep compatibility.** Do not rename canonical tools or remove existing fields. Add compact defaults and opt-in verbose fields where possible.
5. **Make degradation explicit.** If full text or section text cannot be returned, responses must say what was returned and why.
6. **Keep clinical-safety scope unchanged.** All changes remain research-use only and should not add clinical decision support behavior.

## MCP Standards Baseline

The implementation should follow the current MCP tool guidance and FastMCP behavior:

- Tool definitions should have unique names, human-readable titles/descriptions, input schemas, output schemas where structured output is expected, and accurate annotations.
- Structured successful outputs must conform to the declared `output_schema`.
- Tool execution failures such as upstream API failures, invalid domain data, database unavailability, and business-logic failures should be surfaced as MCP tool execution errors. They should not be reported as ordinary successful payloads unless the tool's public contract explicitly models partial success.
- Protocol errors remain reserved for malformed JSON-RPC, unknown tools, invalid protocol-level arguments, and server/protocol failures.
- Error details must be sanitized. The server should log raw exceptions internally, but clients should not see SQL strings, stack traces, DSNs, filesystem paths, access tokens, or private URLs.
- Tool outputs should be sanitized and bounded. Large debug fields, annotated snippets, and duplicate citations must be opt-in.
- Read-only and non-destructive annotations should accurately reflect each tool. Indexing/staging tools are write-like but non-destructive; search/diagnostics/preflight/passages are read-only.

References:

- Model Context Protocol tool specification, 2025-06-18: `https://modelcontextprotocol.io/specification/2025-06-18/server/tools`
- FastMCP tool output, error, timeout, and annotation guidance: `https://fastmcp.mintlify.app/servers/tools`

## Scope

In scope:

- Versioned, idempotent database migrations for review re-RAG storage.
- Startup/readiness schema diagnostics that detect stale review databases.
- MCP error envelopes and recovery hints for review indexing/staging/retrieval failures.
- MCP/REST diagnostics endpoint or tool exposing database, indexer, PubTator, and optional fallback subsystem status.
- Search payload controls: compact response mode, optional citations, optional highlighted snippets.
- Canonical entity search support for `search_literature`.
- Coverage preflight integration in search/staging/indexing responses.
- Guideline/consensus discovery improvement without breaking the generic search contract.
- Explicit `coverage_by_pmid`, `failed_pmids`, and degradation warnings in publication passage retrieval.
- Cache/snapshot metadata for reproducible audit trails.
- Documentation and capability-resource updates for review ID semantics and recovery flows.
- Focused tests plus `make ci-local`.

Out of scope:

- Removing the `pubtator.` prefix from tool names.
- Removing existing tools or forcing a breaking tool-surface tier split.
- Changing hosted-client deferred-tool behavior; the server can document and advertise core tools, but cannot force all MCP clients to eagerly load them.
- Adding ClinVar, Infevers, or other variant-interpretation sources.
- Implementing a full biomedical guideline classifier. This iteration uses deterministic query/filter/rerank heuristics and explicit guideline-search affordances.
- Destructive cache/database operations in public MCP tools.

## Architecture

### 1. Review Database Migrations

Add a small first-party migration runner rather than introducing Alembic for this narrow PostgreSQL footprint.

New files:

- `pubtator_link/db/migrations/0001_review_schema_base.sql`
- `pubtator_link/db/migrations/0002_review_schema_drift_repair.sql`
- `pubtator_link/db/migrations/__init__.py`
- `pubtator_link/db/migrate.py`

The runner:

- connects using `PUBTATOR_LINK_DATABASE_URL`,
- creates `schema_migrations(version text primary key, applied_at timestamptz not null default now())`,
- applies migration files in lexical order inside transactions,
- records applied versions,
- exposes a Python function for startup use and a module CLI for Makefile/Docker use.

`0001` is the current schema for new databases. `0002` is the in-place repair migration for existing Docker volumes. It must:

- add `reviews.updated_at` with a default and backfill,
- create `reviews_updated_at_idx`,
- add missing retrieval-attempt audit columns,
- create missing `review_audit_events`, `review_research_sessions`, `review_research_session_candidates`, and `review_evidence_certainty` tables,
- create missing indexes,
- avoid destructive rewrites.

The existing `pubtator_link/db/review_schema.sql` remains as bootstrap documentation but should be generated-equivalent to the migrations after implementation.

Add settings:

- `PUBTATOR_LINK_AUTO_MIGRATE=true` by default for local/Docker deployments.
- `PUBTATOR_LINK_REQUIRE_SCHEMA_CURRENT=true` by default when review DB is configured.

Startup behavior:

- if `AUTO_MIGRATE` is true, run additive migrations before constructing review services,
- if migration fails, mark readiness `not_ready` and surface a sanitized reason,
- if `REQUIRE_SCHEMA_CURRENT` is true and required columns/tables are absent, refuse review services and report diagnostics.

### 2. Centralized MCP Error Boundary

Create a centralized MCP error module, for example `pubtator_link/mcp/errors.py`, used by all MCP tool functions through a wrapper helper. Do not let individual tools hand-roll failure payloads.

FastMCP-specific behavior:

- create the MCP server with `mask_error_details=True`,
- catch expected tool-execution exceptions in one helper,
- convert them to a sanitized `fastmcp.exceptions.ToolError`,
- serialize the machine-readable recovery envelope as compact JSON in the `ToolError` message,
- log raw exception details server-side with request/tool context.

This intentionally uses MCP's `isError: true` execution-error path. The JSON envelope is carried in the error text so LLM clients can self-correct while MCP clients still see the call as a tool failure.

Standard envelope carried in the tool-error text:

```json
{
  "error_code": "review_index_unavailable",
  "message": "Review indexing is unavailable because the review database schema is not current.",
  "retryable": false,
  "fallback_tool": "pubtator.get_publication_passages",
  "fallback_args": {"pmids": ["39540697"], "mode": "compact_passages"},
  "recovery": "Run database migrations, then retry pubtator.index_review_evidence.",
  "_meta": {
    "next_commands": [
      {
        "tool": "pubtator.get_publication_passages",
        "arguments": {"pmids": ["39540697"], "mode": "compact_passages"}
      },
      {
        "tool": "pubtator.diagnostics",
        "arguments": {}
      }
    ],
    "unsafe_for_clinical_use": true
  }
}
```

Error codes:

- `schema_validation_failed`
- `review_index_unavailable`
- `review_schema_not_current`
- `review_queue_unavailable`
- `review_retrieval_failed`
- `upstream_unavailable`
- `validation_failed`
- `internal_error`

Raw SQL, stack traces, DSNs, and private URLs must not be returned to MCP clients.

For `pubtator.index_review_evidence` and `pubtator.stage_research_session`, fallback args should preserve the PMIDs the user already selected so the LLM can deterministically downgrade to `get_publication_passages`.

For tools that support partial success as a normal domain result, keep `success=true` with explicit `failed_pmids`, `warnings`, and diagnostics. Use MCP tool errors only when the tool cannot complete its core operation.

Every MCP tool should either:

- return a Pydantic-backed structured object matching `output_schema`, or
- raise a standardized `ToolError` through the central helper.

Missing output schemas on existing MCP tools should be filled where the response shape is already typed. For dynamic legacy tools, add an internal typed response model before declaring an output schema.

### 3. Diagnostics Tool And Readiness

Add `pubtator.diagnostics` and enrich `/ready`.

Diagnostics should report:

- process status,
- database configured/connected/current schema,
- applied migration versions,
- missing required schema items when stale,
- review queue availability,
- PubTator API availability as `unknown` unless cheaply checked,
- Europe PMC fallback enabled/disabled,
- recovery commands for stale schema.

MCP diagnostics should be read-only and research-use scoped.

Diagnostics failures should also use the centralized MCP error helper, but the tool should be best-effort: if one subsystem check fails, return the remaining subsystem statuses with a degraded status rather than failing the whole diagnostics call.

### 4. Search Payload And Corpus Controls

Extend `pubtator.search_literature` and `/api/search` with backward-compatible optional arguments:

- `response_mode: "compact" | "standard" | "full" = "compact"` for MCP, `"standard"` for REST if preserving REST verbosity is preferred,
- `include_citations: "none" | "nlm" | "bibtex" | "both" = "none"` for MCP,
- `text_hl_format: "none" | "plain" | "annotated" = "plain"` for MCP,
- `limit: int | None = 5` for MCP,
- `entity_ids: list[str] | None = None`,
- `coverage: "none" | "preflight" = "none"`,
- `guideline_boost: bool = false`.

`entity_ids` are combined with text using PubTator-compatible query syntax:

- only entity IDs: `@GENE_MEFV AND @DISEASE_Familial_Mediterranean_Fever`,
- text plus entities: `(<text>) AND @GENE_MEFV AND @DISEASE_Familial_Mediterranean_Fever`.

`coverage="preflight"` runs the existing source preflight service for returned PMIDs and attaches:

```json
"coverage_hint": {
  "expected_coverage": "abstract_only",
  "coverage_reason": "no_pmcid",
  "pmcid": null,
  "pmc_fallback_available": false
}
```

`guideline_boost=true` applies deterministic local reranking to the returned page:

- boost publication types containing `Guideline`, `Practice Guideline`, `Consensus`, `Consensus Development Conference`, or `Systematic Review`,
- boost title/abstract terms such as `recommendation`, `guideline`, `consensus`, `EULAR`, `PReS`, `SHARE`,
- retain original score and expose `rank_features` in full mode.

Add `pubtator.search_guidelines` only as a thin MCP convenience wrapper over `search_literature` with `guideline_boost=true` and guideline-oriented publication types. It should not add a separate backend path.

`text_hl_format` controls highlighted snippets:

- `none`: omit `text_hl`,
- `plain`: strip PubTator entity markup such as `@GENE_MEFV @@@MEFV@@@` while preserving readable highlighted text,
- `annotated`: preserve the upstream annotated snippet.

`limit` is a response shaping limit. If PubTator3 does not expose a reliable page-size parameter, the server fetches the upstream page and returns the first `limit` results after local reranking. `total_results` and `total_pages` still describe the upstream result set.

For entity autocomplete, preserve upstream `synonyms` and add a lightweight derived `matched_terms` list when upstream only exposes terms inside the `match` text. This avoids changing the existing entity contract while giving LLMs useful disambiguation signals for ambiguous biomedical names.

### 5. Passage Coverage, Failed PMIDs, And Degradation Warnings

Extend publication passage responses with:

- `coverage_by_pmid: dict[str, "full_text" | "abstract_only" | "title_only" | "unknown"]`,
- `coverage_reason_by_pmid: dict[str, str]`,
- `failed_pmids: list[{"pmid": str, "reason": str}]`,
- `warnings: list[str]`.

If `mode="section_text"` or `full=true` requested body sections but only title/abstract passages are returned, include:

```json
"warnings": [
  "No full-text section passages were available for PMID 39540697; returned abstract-level PubTator passages."
]
```

This is a disclosure requirement, not a failure. It prevents silent evidence downgrades.

### 6. Reproducibility Metadata

Add lightweight reproducibility metadata to search, publication passage, and review retrieval responses:

- `cache_key`: deterministic hash of tool name, normalized inputs, and relevant source options,
- `corpus_snapshot_date`: current UTC date for live upstream calls,
- `source_versions`: include `pubtator3` and migration schema version where relevant.

This does not claim that PubTator data itself is frozen; it gives report authors an audit timestamp and a deterministic local request key.

### 7. Review Retrieval Diagnostics

The code already has typed zero-result reasons. Extend only where needed:

- add `coverage_abstract_only`,
- add `no_pmids_indexed`,
- preserve existing enum values for compatibility.

Add `dry_run: bool = false` to `retrieve_review_context_batch`. Dry run performs DB candidate counting and returns diagnostics/query summaries without passage text. It should use `response_mode="diagnostics"` internally and avoid extra full payload packing.

### 8. Documentation And Resources

Update:

- `README.md`
- `docs/MCP_CONNECTION_GUIDE.md`
- `docs/development/operations-runbook.md`
- `docker/README.md`
- `pubtator_link/mcp/resources.py`
- `pubtator_link/mcp/facade.py` instructions

Required docs content:

- run `make db-migrate` for existing databases,
- Docker rebuild does not reset existing PostgreSQL volumes,
- `review_id` is a caller-chosen durable namespace; same ID accumulates sources, same PMID deduplicates, collisions reuse the same review index,
- canonical LLM workflow: entity search -> search_literature with entity_ids/coverage -> preflight -> index -> inspect -> retrieve,
- fallback workflow if index unavailable: get publication passages for the same PMIDs and include degradation note,
- compact search defaults and opt-in citations.
- `text_hl_format="plain"` is the default because annotated PubTator snippets are useful for debugging but unnecessarily large for normal LLM reading.
- `limit=5` is the recommended MCP discovery default; callers can raise it when they need broader recall.

## Testing Strategy

Use TDD task-by-task.

Focused test areas:

- migration runner applies repair migration to an old schema fixture,
- startup resource creation runs migrations when configured,
- `/ready` reports stale/current schema accurately,
- MCP review tools return structured error envelopes for simulated DB schema errors,
- search adapter respects `include_citations`, `text_hl_format`, `limit`, `entity_ids`, `coverage`, and guideline reranking,
- passage service emits coverage, failed PMIDs, and section/full-text degradation warnings,
- diagnostics tool schema and response are typed,
- docs/resources advertise the new recovery and compact search flows.

Required final verification:

```bash
make ci-local
```

## Migration Safety

The repair migration must be idempotent. Running it repeatedly should not alter row counts or fail on existing columns/indexes/tables.

No migration in this iteration may:

- drop a table,
- drop a column,
- truncate data,
- rewrite passage text,
- change primary keys,
- rename public tables.

## Rollout

1. Ship migration runner and repair migration.
2. Apply it to the current Docker database using `make db-migrate`.
3. Verify `pubtator.index_review_evidence` no longer fails on the live stack.
4. Ship MCP error/recovery envelope.
5. Ship search/coverage/passage ergonomics.
6. Update docs/resources.
7. Run focused tests and `make ci-local`.

## Acceptance Criteria

- Existing Docker database is repaired in place without volume deletion.
- `pubtator.index_review_evidence` succeeds or returns a structured MCP fallback envelope; it never leaks `UndefinedColumnError`.
- `/ready` and `pubtator.diagnostics` identify stale schema and recovery commands.
- `search_literature` can run with canonical `entity_ids`, compact payloads, opt-in citations, opt-in highlights, and preflight coverage hints.
- Guideline/consensus-oriented searches can be requested directly and rank landmark guideline-like results ahead of ordinary reviews when they appear in the returned candidate page.
- `get_publication_passages` returns explicit coverage/degradation/failed-PMID fields.
- Review retrieval emits reproducibility metadata and supports diagnostics-only dry runs.
- Documentation tells LLM clients and operators exactly how to recover from index failures and how to stabilize corpus selection.
- Focused tests pass.
- `make ci-local` passes.
