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
- No persisted context packs unless an audit snapshot feature is added later.
- No full PRISMA, RoB 2, ROBINS-I, QUADAS-2, or GRADE workflow in the POC.

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
- `screened`: prepare records already marked `maybe` or `include`.
- `candidate_fast`: prepare the request PMIDs with tighter concurrency and timeout limits.

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

## Full-Text Preparation

Preparation is review-scoped and idempotent by `(review_id, source_id)`, where `source_id` is a stable PMID, PMCID, DOI, or curated URL identifier.

The source cascade is:

1. PubTator BioC export with full text when available.
2. PMC BioC / PMC Open Access structured full text.
3. Europe PMC metadata and accessible structured full text hints.
4. Curated or user-provided URLs.
5. Docling PDF fallback for accessible PDFs.
6. Abstract-only fallback when full text is unavailable.

Each source attempt is stored with status:

- `success`
- `not_available`
- `blocked`
- `failed`

Blocked publisher pages, HTML responses for expected PDFs, HTTP 403 responses, and unavailable XML are not hidden. They are first-class retrieval attempts so users can see why full text was not indexed.

## Docling Role

Docling is a fallback adapter, not the primary ingestion path. Structured PubTator, BioC, and JATS sources are preferred because they preserve biomedical annotation context, stable sections, and source identifiers.

Use Docling when:

- structured full text is unavailable,
- the URL is explicit and review-scoped,
- the content is accessible PDF bytes,
- conversion can finish within the POC timeout budget.

Docling output should be normalized into the same `review_passages` table as BioC/JATS passages. Preserve source metadata such as page number, heading path, table marker, and conversion status where available.

## Background Preparation

The POC uses an in-process `asyncio` queue.

Rules:

- Limit concurrent document preparations to 2 by default.
- Use a 60-second per-document timeout and a 20-second per-source timeout.
- Deduplicate queued jobs by `(review_id, source_id)`.
- Repeated indexing calls should warm missing attempts and passages, not duplicate rows.
- Store job state so MCP clients can see whether context is complete, partial, running, or failed.

This keeps the POC fast and avoids introducing a production worker stack before the retrieval design is validated.

## PostgreSQL Storage

### `review_preparation_jobs`

Tracks background preparation state.

Important columns:

- `job_id`
- `review_id`
- `source_id`
- `source_type`
- `status`
- `queued_at`
- `started_at`
- `finished_at`
- `error`

### `full_text_retrieval_attempts`

Records every attempted source.

Important columns:

- `attempt_id`
- `review_id`
- `source_id`
- `source`
- `status`
- `url`
- `reason`
- `content_type`
- `content_length`
- `created_at`

### `review_passages`

Stores normalized retrieval units.

Important columns:

- `passage_id`
- `review_id`
- `source_id`
- `source_type`
- `pmid`
- `pmcid`
- `doi`
- `url`
- `section`
- `heading_path`
- `page`
- `text`
- `entity_ids`
- `relation_types`
- `screening_status`
- `search_vector`
- `created_at`

Indexes:

- GIN index on `search_vector`
- btree index on `review_id`
- btree index on `(review_id, pmid)`
- btree index on `(review_id, source_id)`
- btree index on `(review_id, section)`

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
order by lexical_rank desc
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

Suggested section priority for biomedical review context:

1. title
2. abstract
3. results
4. recommendations
5. discussion
6. methods
7. body

Suggested source priority:

1. PubTator full BioC / PMC BioC
2. JATS structured text
3. Docling PDF fallback
4. abstract-only fallback

The returned context pack is generated fresh for each request. It includes citation keys (`S1`, `S2`) mapped to stable passage IDs.

## Error Handling

- Retrieval endpoints return partial context rather than failing when some documents are still preparing.
- Full-text source failures are stored as attempts and do not fail the whole review.
- Invalid PMIDs or unreachable curated URLs fail that source item, not the full request.
- Database failures return an API error and do not claim preparation was queued.
- Background preparation exceptions mark the job `failed` with a short error message.

## Testing Strategy

Unit tests:

- source cascade records blocked and unavailable attempts,
- PDF detection accepts only PDF bytes,
- Docling adapter is skipped when content is not an accessible PDF,
- passage normalization preserves review ID, PMID, section, and source type,
- reranker prefers query-matching and filtered passages,
- packer enforces `max_chars` and `max_passages`,
- repeated indexing is idempotent.

Route tests:

- `index_review_evidence` queues preparation and returns status,
- `retrieve_review_context` returns partial context while a job is running,
- `retrieve_review_context` returns citation maps for prepared passages.

Database tests:

- schema contains preparation jobs, retrieval attempts, review passages, and indexes,
- repository can upsert passages without duplicating them,
- repository can query passages by review and full-text search.

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
- Docling metadata is stored in a JSON column for the POC. Stable fields can be promoted after testing real PDFs.
