# Hybrid Embedding Reranker Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-03

## Purpose

Improve clinical review-context relevance by adding an optional local dense
embedding reranker over bounded lexical candidates. The first implementation
slice keeps Postgres full-text search as the recall stage, stores local passage
embeddings with `pgvector`, and fuses lexical plus dense ranks with guardrails
that prevent references and abbreviations from being promoted as evidence.

## Goals

- Add local-only passage embeddings for review passages.
- Rerank the top 50 lexical candidates with cosine similarity.
- Use Reciprocal Rank Fusion (RRF) to combine lexical rank and dense rank.
- Keep `REF`, `references`, and `ABBR` passages from being promoted above
  evidence-bearing sections by dense similarity.
- Fall back to existing lexical ranking when embeddings, the local model, or
  `pgvector` are unavailable.
- Surface diagnostics that explain dense rerank status, model name, candidate
  count, missing embedding count, and fallback reason.
- Keep the hosted/public default deterministic and lightweight unless dense
  reranking is explicitly enabled.

## Non-Goals

- No external embedding API calls.
- No generated clinical answer or clinical decision support.
- No cross-encoder reranker in the first implementation.
- No broad vector-first retrieval over the whole review corpus in the first
  implementation.
- No committed files under `benchmarks/`.
- No replacement of existing citation, passage, PMID, or source provenance.
- No enriched passage embedding input in the first implementation; benchmarked
  enriched text underperformed raw passage text for the current corpus.

## Benchmark Evidence

An offline benchmark was run against the live Docker Postgres corpus
`fmf-mefv-vus-turkish-pediatric-colchicine`.

Corpus and queries:

- 1,103 real review passages.
- Six clinical FMF/MEFV/colchicine queries.
- First stage fixed to existing lexical top 50.
- Metric: silver `nDCG@10`, plus target PMID hit@5/MRR where a target PMID was
  obvious.

Model bake-off:

| Variant | Dim | Mean guarded nDCG@10 | Mean latency over top 50 |
| --- | ---: | ---: | ---: |
| Lexical baseline | n/a | 0.647 | n/a |
| `BAAI/bge-small-en-v1.5` guarded dense | 384 | 0.738 | 0.071s |
| `intfloat/e5-small-v2` guarded dense | 384 | 0.734 | 0.050s |
| `sentence-transformers/all-MiniLM-L6-v2` guarded dense | 384 | 0.691 | 0.026s |
| `BAAI/bge-base-en-v1.5` guarded dense | 768 | 0.785 | 0.097s |
| `Qwen/Qwen3-Embedding-0.6B` guarded dense | 1024 | 0.763 | 0.326s |

Fusion bake-off:

| Variant | Mean nDCG@10 | Target MRR |
| --- | ---: | ---: |
| Lexical baseline | 0.647 | 0.611 |
| BGE-small raw guarded dense | 0.738 | 0.444 |
| BGE-small raw weighted blend 70/30 | 0.748 | 0.583 |
| BGE-small raw RRF | 0.782 | 0.778 |
| BGE-base raw RRF | 0.789 | 0.611 |

The benchmark supports `BAAI/bge-small-en-v1.5` as the first implementation
model: it keeps `vector(384)` storage, delivers most of the measured gain, and
is much cheaper than Qwen. `BAAI/bge-base-en-v1.5` remains the likely
higher-quality profile after the storage and config abstractions exist.

## Model Decision

Use `BAAI/bge-small-en-v1.5` for the MVP.

Reasons:

- 384-dimensional embeddings match the requested `vector(384)` footprint.
- It improved the benchmark by 20.9% relative when combined with RRF.
- It preserved target PMID hit@5 in the benchmark.
- It is small enough to run locally in-process for private deployments.

Do not use `Qwen/Qwen3-Reranker-0.6B` for this feature because it is a
cross-encoder reranker, not a stored-vector cosine model. Keep
`Qwen/Qwen3-Embedding-0.6B` as an optional future profile; it supports flexible
dimensions, but the initial benchmark did not justify its latency and storage
cost.

## Public Configuration

Add review embedding settings under the existing `PUBTATOR_LINK_` environment
prefix:

- `PUBTATOR_LINK_REVIEW_EMBEDDING_RERANK_ENABLED=false`
- `PUBTATOR_LINK_REVIEW_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`
- `PUBTATOR_LINK_REVIEW_EMBEDDING_DIM=384`
- `PUBTATOR_LINK_REVIEW_EMBEDDING_TOP_K=50`
- `PUBTATOR_LINK_REVIEW_EMBEDDING_RRF_K=60`
- `PUBTATOR_LINK_REVIEW_EMBEDDING_BATCH_SIZE=32`
- `PUBTATOR_LINK_REVIEW_EMBEDDING_DEVICE=auto`

The feature is disabled by default. When disabled, retrieval behavior remains
the current lexical ranking behavior.

## Schema

Add `pgvector` support and a separate embedding table rather than embedding
columns on `review_passages`.

```sql
create extension if not exists vector;

create table if not exists review_passage_embeddings (
    review_id text not null,
    passage_id text not null,
    model_name text not null,
    embedding_dim integer not null,
    text_hash text not null,
    embedding vector(384) not null,
    created_at timestamptz not null default now(),
    primary key (review_id, passage_id, model_name),
    foreign key (review_id, passage_id)
        references review_passages(review_id, passage_id)
        on delete cascade
);
```

The MVP table uses `vector(384)` because the first supported model is
`BAAI/bge-small-en-v1.5`. A later multi-dimension migration can add a second
table or additional profile-specific tables if BGE-base or Qwen is promoted.

Docker development Postgres must use a pgvector-capable image, such as
`pgvector/pgvector:0.8.2-pg18-trixie`, instead of plain `postgres:18-alpine`.

## Architecture

### Embedding Provider

Create a small local embedding boundary in
`pubtator_link/services/review_context/embeddings.py`.

Responsibilities:

- Load a Sentence Transformers model lazily.
- Apply the BGE query instruction only to query text.
- Encode passage text without instruction.
- Normalize embeddings.
- Provide a deterministic fake provider for tests.
- Raise typed unavailable/configuration errors that retrieval can degrade from.

The `sentence-transformers` and `torch` dependency group should be optional so
CI and default Docker builds do not pull ML dependencies unless enabled.

### Repository

Extend `PostgresReviewReragRepository` with embedding operations:

- `upsert_passage_embeddings(review_id, embeddings)`
- `get_passage_embeddings(review_id, passage_ids, model_name, embedding_dim)`
- `list_passages_missing_embeddings(review_id, model_name, embedding_dim, limit)`

Use `text_hash` to detect stale embeddings when passage text changes.

### Indexing And Backfill

During review evidence preparation, compute embeddings for newly indexed
passages when the feature is enabled and a model is available. Add a focused
service method that can backfill missing embeddings for existing indexed
reviews without changing source ingestion semantics.

If embedding generation fails, indexing should still succeed and retrieval
should fall back to lexical ranking with diagnostics.

### Retrieval

The retrieval flow becomes:

1. Search Postgres FTS with existing lexical query, internally limited to
   `review_embedding_top_k` when dense reranking is enabled.
2. Sort lexical candidates with existing `rerank_key` to get lexical rank.
3. Fetch stored embeddings for candidate passage IDs.
4. Embed the question locally.
5. Compute cosine similarity for candidates with embeddings.
6. Build dense rank over eligible sections only.
7. Append `REF`, `references`, and `ABBR` candidates after evidence sections.
8. Fuse lexical rank and dense rank with RRF:

```text
score = 1 / (rrf_k + lexical_rank) + 1 / (rrf_k + dense_rank)
```

9. Sort by fused score, then existing deterministic tie-breakers.
10. Pack and merge using the existing budgeting path.

Candidates with missing embeddings retain lexical rank and should not be
promoted by dense score.

## Diagnostics

Add retrieval diagnostics when dense reranking is requested or active:

```json
{
  "embedding_rerank": {
    "enabled": true,
    "active": true,
    "model_name": "BAAI/bge-small-en-v1.5",
    "embedding_dim": 384,
    "candidate_count": 50,
    "embedded_candidate_count": 48,
    "missing_embedding_count": 2,
    "strategy": "lexical_top_k_dense_rrf",
    "fallback_reason": null
  }
}
```

Fallback reasons include:

- `disabled`
- `provider_unavailable`
- `schema_unavailable`
- `query_embedding_failed`
- `no_candidate_embeddings`
- `dimension_mismatch`

## Error Handling

- Retrieval must not fail solely because the embedding provider is unavailable.
- Schema errors from missing `pgvector` should degrade to lexical retrieval and
  produce diagnostics when possible.
- Model dimension mismatches should disable dense rerank for that request and
  surface `dimension_mismatch`.
- Embedding generation during indexing should not mark source preparation as
  failed unless passage indexing itself failed.
- Public MCP errors should continue to use existing MCP error wrapping.

## Testing

Use TDD in the implementation plan:

- Unit tests for RRF and guarded dense ranking.
- Unit tests for config parsing.
- Unit tests for local provider dependency-unavailable behavior.
- Repository tests for the embedding table and stale hash behavior.
- Service tests proving dense RRF changes ordering and lexical fallback works.
- Docker tests proving the compose Postgres image supports `create extension vector`.
- MCP/service-adapter tests proving diagnostics are surfaced.

Run focused tests per task, then `make ci-local` before completion.

## Compatibility

- Dense reranking is opt-in and off by default.
- Existing review indexes remain valid; they simply have no embeddings until
  backfilled or newly prepared with the feature enabled.
- Existing retrieval responses retain their current passage/citation fields.
- Existing Docker ports and environment variables remain unchanged.
- Public hosted deployments can leave the feature disabled to avoid ML runtime
  and model download requirements.
