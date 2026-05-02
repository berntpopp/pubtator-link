# Review-Scoped Re-RAG POC Design

## Purpose

Build a fast proof of concept for review-scoped evidence preparation and retrieval in PubTator-Link. The POC should let a reviewer or MCP client add candidate PMIDs to a review, start bounded background full-text preparation, and request compact citable context packs while preparation continues.

The backend remains deterministic. It does not call an LLM, make screening judgements, compute risk of bias, or generate evidence certainty. It prepares auditable passages and retrieves them for the client.

## POC Scope

Implement the smallest end-to-end loop:

1. Accept review evidence intake with `review_id`, `pmids`, optional curated URLs, and preparation mode.
2. Prepare full text asynchronously for selected review records.
3. Store retrieval attempts and normalized review-scoped passages in PostgreSQL.
4. Retrieve per-request context packs from the review passage table using PostgreSQL full-text search and deterministic Python reranking.
5. Return partial context when background preparation is still running.

Defer broader review workflow features until this loop is proven.

## Non-Goals

- No external vector database in the POC.
- No embeddings or `pgvector` dependency in the POC.
- No Celery, RQ, or separate worker service in the POC.
- No stored LLM outputs.
- No persisted context packs unless an audit snapshot feature is added later. Fresh context packs can change when new passages are prepared or ranking defaults change.
- No full PRISMA, RoB 2, ROBINS-I, QUADAS-2, or GRADE workflow in the POC.
- No multi-tenant authorization model in the POC. The POC is for single-tenant trusted deployments or deployments protected by an upstream authenticated proxy.

## API Shape

### Index Review Evidence

`POST /api/reviews/{review_id}/evidence/index`

Request:

```json
{
  "pmids": ["40234174"],
  "curated_urls": ["https://example.org/guideline.pdf"],
  "prepare_mode": "selected"
}
```

`prepare_mode` values:

- `selected`: prepare the PMIDs and URLs in this request.
- `candidate_fast`: prepare the request PMIDs with `max_sources_per_record=2`, a 30-second per-document timeout, and a 10-second per-source timeout.

The POC does not include `screened` mode because screening state belongs to the broader review workflow. Add it later when a concrete screening decision API and storage contract exist.

Response:

```json
{
  "success": true,
  "review_id": "rev_123",
  "queued": 1,
  "already_prepared": 0,
  "preparation_status": {
    "queued": 1,
    "running": 0,
    "complete": 0,
    "partial": 0,
    "failed": 0
  }
}
```

### Retrieve Review Context

`POST /api/reviews/{review_id}/context`

Request:

```json
{
  "question": "Should colchicine be started after clinical diagnosis of FMF?",
  "pmids": ["40234174"],
  "entity_ids": [],
  "sections": ["abstract", "results", "discussion", "recommendations"],
  "max_passages": 8,
  "max_chars": 6000
}
```

Response:

```json
{
  "success": true,
  "review_id": "rev_123",
  "context_pack": {
    "question": "Should colchicine be started after clinical diagnosis of FMF?",
    "passages": [
      {
        "citation_key": "S1",
        "passage_id": "PMID:40234174:abstract:0",
        "pmid": "40234174",
        "section": "abstract",
        "text": "..."
      }
    ],
    "citation_map": {
      "S1": "PMID:40234174:abstract:0"
    }
  },
  "preparation_status": {
    "complete": 1,
    "running": 0,
    "partial": 0,
    "failed": 0
  }
}
```

If preparation is still running, return the best available passages and include `running` or `partial` counts. The endpoint should not block indefinitely waiting for full text.

Preparation status terms:

- `queued`: a job exists but has not started.
- `running`: at least one source attempt is still in flight.
- `complete`: preparation finished and at least one full-text or abstract fallback passage was indexed.
- `partial`: preparation finished, at least one source failed or was blocked, and fallback passages were indexed.
- `failed`: preparation finished without indexing any passage.

The index endpoint must return quickly after queueing or deduplicating jobs. It should not wait for full-text preparation to complete.

## Review Identity and Trust Boundary

The POC creates reviews lazily. The first successful `index_review_evidence` call inserts a row into `reviews(review_id, created_at)` if it does not already exist.

`review_id` is caller supplied and not secret. The POC is single-tenant trusted software unless an upstream proxy enforces authentication and authorization. Internet-exposed deployments must put the API and hosted MCP endpoint behind an authenticated reverse proxy before enabling review write/read tools.

## Full-Text Preparation

Preparation is review-scoped and idempotent by `(review_id, source_id)`, where `source_id` is a stable PMID, PMCID, DOI, or curated URL identifier.

The source cascade is:

1. PubTator BioC export with full text when available.
2. PMC BioC / PMC Open Access structured full text.
3. Europe PMC metadata and accessible JATS or structured full text hints.
4. Curated or user-provided URLs.
5. Docling PDF fallback for accessible PDFs.
6. Abstract-only fallback when full text is unavailable.

Passage IDs are deterministic within a review source and are used for idempotent upserts and citation maps. The format is:

- PubMed abstract or full text: `PMID:{pmid}:{normalized_section}:{zero_based_index}`
- PMC-only source without PMID: `PMCID:{pmcid}:{normalized_section}:{zero_based_index}`
- Curated URL or Docling PDF source: `URL:{source_hash}:{normalized_section_or_page}:{zero_based_index}`

`normalized_section` uses lowercase ASCII, spaces replaced by underscores, and non-alphanumeric separators collapsed to one underscore.

Each source attempt is stored with status:

- `success`
- `not_available`
- `blocked`
- `failed`

Blocked publisher pages, HTML responses for expected PDFs, HTTP 403 responses, and unavailable XML are not hidden. They are first-class retrieval attempts so users can see why full text was not indexed.

## URL Fetch Safety

Curated URLs and Docling PDF fetches are server-side network requests and must use a defensive URL validator.

Rules:

- Allow only `https` by default. `http` is allowed only when an explicit development setting enables it.
- Resolve hostnames before connecting and reject loopback, private, link-local, multicast, unspecified, reserved, and metadata addresses, including `169.254.169.254`.
- Use bounded redirects with a maximum of 3 hops.
- Re-validate scheme, host, and resolved IPs after each redirect.
- Enforce a response `Content-Length` cap before reading the body.
- Enforce the same byte cap while streaming the body, even when `Content-Length` is missing or wrong.
- Use the 20-second per-source timeout for the whole fetch.
- Require accessible PDF bytes before invoking Docling. HTML returned from a PDF URL is recorded as `blocked`.

The POC body cap defaults to 50 MB for PDFs and 10 MB for HTML/XML/text sources.

## Docling Role

Docling is a fallback adapter, not the primary ingestion path. Structured PubTator, BioC, and JATS sources are preferred because they preserve biomedical annotation context, stable sections, and source identifiers.

Use Docling when:

- structured full text is unavailable,
- the URL is explicit and review-scoped,
- the content is accessible PDF bytes,
- conversion can finish within the POC timeout budget.

Docling output should be normalized into the same `review_passages` table as BioC/JATS passages. Preserve source metadata such as page number, heading path, table marker, and conversion status where available.

Docling parses untrusted PDFs in process for the POC. This is an accepted POC risk for local or trusted deployments. A production hardening task should move PDF parsing to a subprocess or container boundary. The first Docling call may have a model or converter cold start, so the queue should report the job as `running` rather than blocking the index endpoint.

## Background Preparation

The POC uses an in-process `asyncio` queue.

Rules:

- The POC runtime is constrained to one web worker process by default.
- Limit concurrent document preparations to 2 by default.
- Use a 60-second per-document timeout and a 20-second per-source timeout.
- Deduplicate queued jobs by `(review_id, source_id)`.
- Also use a PostgreSQL advisory lock keyed by `(review_id, source_id)` around preparation execution so accidental multi-worker or multi-process runs do not duplicate source fetches.
- Repeated indexing calls should warm missing attempts and passages, not duplicate rows.
- Store job state so MCP clients can see whether context is complete, partial, running, or failed.
- On startup, jobs left in `running` state from a previous process are marked `failed` with reason `process_restarted`. A later index call may queue them again.

This keeps the POC fast and avoids introducing a production worker stack before the retrieval design is validated.

## PostgreSQL Storage

Schema lives in `pubtator_link/db/review_schema.sql`. The POC exposes a `make db-init` target to apply it locally. Application startup may validate that required tables exist, but it should not silently run destructive migrations.

### `reviews`

Tracks review identities created lazily by the POC.

Important columns:

- `review_id text primary key`
- `created_at timestamptz not null default now()`

### `review_preparation_jobs`

Tracks background preparation state.

Important columns:

- `job_id uuid primary key`
- `review_id text not null references reviews(review_id)`
- `source_id text not null`
- `source_kind text not null`
- `status text not null`
- `queued_at timestamptz not null default now()`
- `started_at timestamptz`
- `finished_at timestamptz`
- `error text`
- `unique(review_id, source_id)`

### `full_text_retrieval_attempts`

Records every attempted source.

Important columns:

- `attempt_id uuid primary key`
- `review_id text not null references reviews(review_id)`
- `source_id text not null`
- `source_kind text not null`
- `status text not null`
- `url text`
- `reason text`
- `content_type text`
- `content_length bigint`
- `created_at timestamptz not null default now()`

Indexes:

- btree index on `(review_id, source_id, source_kind, created_at)`

### `review_passages`

Stores normalized retrieval units.

Important columns:

- `passage_id text not null`
- `review_id text not null references reviews(review_id)`
- `source_id text not null`
- `source_kind text not null`
- `pmid text`
- `pmcid text`
- `doi text`
- `url text`
- `section text not null`
- `heading_path text`
- `page integer`
- `text text not null`
- `entity_ids text[] not null default '{}'`
- `relation_types text[] not null default '{}'`
- `screening_status text not null default 'candidate'`
- `source_metadata jsonb not null default '{}'`
- `search_vector tsvector generated always as (to_tsvector('english', coalesce(heading_path, '') || ' ' || section || ' ' || text)) stored`
- `created_at timestamptz not null default now()`
- `primary key(review_id, passage_id)`

Indexes:

- GIN index on `search_vector`
- GIN index on `entity_ids`
- btree index on `review_id`
- btree index on `(review_id, pmid)`
- btree index on `(review_id, source_id)`
- btree index on `(review_id, section)`

Use `source_kind` consistently for the kind of prepared source or retrieval attempt. Do not mix `source`, `source_type`, and `source_kind` in new models.

## Per-Request Re-RAG

The POC retrieval path is PostgreSQL full-text search plus deterministic Python packing.

PostgreSQL retrieves candidates:

```sql
select
  passage_id,
  pmid,
  section,
  text,
  ts_rank_cd(search_vector, websearch_to_tsquery('english', $2)) as lexical_rank
from review_passages
where review_id = $1
  and search_vector @@ websearch_to_tsquery('english', $2)
  and ($3::text[] is null or entity_ids && $3::text[])
  and ($4::text[] is null or pmid = any($4::text[]))
  and ($5::text[] is null or section = any($5::text[]))
order by lexical_rank desc, passage_id asc
limit 80;
```

Python then reranks and packs candidates using:

- lexical rank,
- PMID filters,
- entity overlap,
- section priority,
- screening-status boost,
- source priority,
- per-PMID diversity,
- max passage and character limits.

Reranking is deterministic. For equal scores, sort by section priority, source priority, PMID, and `passage_id`.

Apply per-PMID diversity after scoring and before final packing. The POC default is `max_passages_per_pmid=2` unless the caller explicitly filters to a single PMID.

`max_chars` is enforced by dropping any passage that would exceed the budget. Do not truncate passages mid-text because that weakens citation integrity.

Suggested section priority for biomedical review context:

1. title
2. abstract
3. results
4. recommendations
5. discussion
6. methods
7. body

`recommendations` is expected mostly from Docling-parsed clinical practice guideline PDFs. PubTator, PMC BioC, and JATS sources may not emit that exact section name.

Suggested source priority:

1. PubTator full BioC / PMC BioC
2. JATS structured text
3. Docling PDF fallback
4. abstract-only fallback

The returned context pack is generated fresh for each request. It includes citation keys (`S1`, `S2`) mapped to stable passage IDs.

Known POC retrieval limitations:

- Lexical-only retrieval can under-recall biomedical synonyms and aliases, such as `MEFV` and `FMF`, unless those terms are present in the passage or entity metadata.
- `websearch_to_tsquery` is convenient and user-friendly but does not provide robust phrase proximity ranking.
- Hybrid `pgvector` retrieval and synonym expansion are backlog items after the POC loop is validated.

## MCP Surface

Expose the POC through hosted MCP as research-use scoped tools:

- `pubtator.index_review_evidence`: write tool. Queues or deduplicates review-scoped evidence preparation.
- `pubtator.retrieve_review_context`: read tool. Retrieves a compact context pack from already prepared review passages.

These tools must carry the same research-use limitation as the existing MCP surface: they are for biomedical literature exploration, not diagnosis, treatment, triage, patient management, or clinical decision support.

## Error Handling

- Retrieval endpoints return partial context rather than failing when some documents are still preparing.
- Full-text source failures are stored as attempts and do not fail the whole review.
- Invalid PMIDs or unreachable curated URLs fail that source item, not the full request.
- Database failures return an API error and do not claim preparation was queued.
- Background preparation exceptions mark the job `failed` with a short error message.
- All job transitions and retrieval attempts are logged through the existing structlog setup with `review_id`, `source_id`, and `attempt_id` or `job_id` bound where available.

## Testing Strategy

Unit tests:

- SSRF and URL-validation rules reject private, loopback, link-local, metadata, unsupported schemes, over-limit redirects, and oversized bodies,
- source cascade records blocked and unavailable attempts,
- PDF detection accepts only PDF bytes,
- Docling adapter is skipped when content is not an accessible PDF,
- passage normalization preserves review ID, PMID, section, and source kind,
- reranker prefers query-matching and filtered passages,
- packer enforces `max_chars` and `max_passages`,
- repeated indexing is idempotent,
- concurrent indexing deduplicates by `(review_id, source_id)`,
- per-document and per-source timeouts are enforced,
- deterministic tie-breaking keeps citation maps stable when data has not changed.

Route tests:

- `index_review_evidence` queues preparation and returns status,
- `retrieve_review_context` returns partial context while a job is running,
- `retrieve_review_context` returns citation maps for prepared passages.

Database tests:

- schema contains preparation jobs, retrieval attempts, review passages, and indexes,
- repository can upsert passages without duplicating them,
- repository can query passages by review and full-text search,
- integration test applies `review_schema.sql` against a real PostgreSQL service,
- FTS index smoke test confirms the query plan can use the GIN index for review passage search.

Docling fallback tests:

- accessible PDF bytes are accepted for conversion,
- HTML disguised as a PDF is rejected and recorded as `blocked`.

## Post-POC Backlog

Keep these as plan items or GitHub issues after the POC spec is approved:

- Add `pgvector` hybrid retrieval inside PostgreSQL.
- Evaluate external vector stores only if review corpora outgrow PostgreSQL or require cross-review retrieval.
- Add Celery, RQ, or another durable worker when background preparation needs to survive process restarts.
- Store context-pack audit snapshots for reproducibility.
- Add richer Docling table, figure, and caption extraction.
- Add PRISMA flow endpoints.
- Add structured extraction endpoints.
- Add RoB 2, ROBINS-I, QUADAS-2, and GRADE-oriented workflow endpoints.
- Add admin controls for retrying failed full-text preparation jobs.

## POC Defaults

- Background preparation concurrency defaults to 2 documents.
- Per-document preparation timeout defaults to 60 seconds.
- Per-source retrieval timeout defaults to 20 seconds.
- Hosted POC deployments should run one web worker process unless the advisory-lock path has been verified under multi-worker load.
- PDF body cap defaults to 50 MB.
- HTML/XML/text body cap defaults to 10 MB.
- `http` curated URLs are disabled by default and enabled only with `PUBTATOR_LINK_ALLOW_HTTP_URLS=true` for local development.
- PubTator and Europe PMC fetches reuse the same rate-limiter pattern as `PubTator3Client`.
- Docling metadata is stored in a JSON column for the POC. Stable fields can be promoted after testing real PDFs.

Config additions:

- `PUBTATOR_LINK_DATABASE_URL`
- `PUBTATOR_LINK_REVIEW_PREP_CONCURRENCY`
- `PUBTATOR_LINK_REVIEW_PREP_DOCUMENT_TIMEOUT_SECONDS`
- `PUBTATOR_LINK_REVIEW_PREP_SOURCE_TIMEOUT_SECONDS`
- `PUBTATOR_LINK_REVIEW_PREP_PDF_MAX_BYTES`
- `PUBTATOR_LINK_REVIEW_PREP_TEXT_MAX_BYTES`
- `PUBTATOR_LINK_ALLOW_HTTP_URLS`
- `PUBTATOR_LINK_ENABLE_DOCLING`
