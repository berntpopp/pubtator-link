# Review Re-RAG POC

This POC prepares review-scoped evidence passages and retrieves compact context packs. It is research-use only and is not for diagnosis, treatment, triage, patient management, or clinical decision support.

## Setup

Set a PostgreSQL URL:

```bash
export PUBTATOR_LINK_DATABASE_URL=postgresql://user:pass@localhost:5432/pubtator_link
make db-init
```

Start the server with one worker for the POC:

```bash
make dev
```

## Queue Evidence Preparation

```bash
curl -s http://127.0.0.1:8000/api/reviews/rev_123/evidence/index \
  -H 'content-type: application/json' \
  -d '{"pmids":["40234174"],"prepare_mode":"selected"}'
```

The endpoint returns after queueing. Preparation continues in the background.

## Inspect The Index

```bash
curl -s 'http://127.0.0.1:8000/api/reviews/rev_123/index?include_passage_samples=true&sample_per_pmid=1'
```

Use inspection before retrieval to confirm which PMIDs, sections, passage counts, and failed sources are available.

## Retrieve Context

```bash
curl -s http://127.0.0.1:8000/api/reviews/rev_123/context \
  -H 'content-type: application/json' \
  -d '{"question":"Should colchicine start after clinical diagnosis of FMF?","max_passages":8,"max_chars":6000,"include_diagnostics":true}'
```

The context pack is generated fresh for each request. It can change as more passages are prepared.

## Batch Query Variants

```bash
curl -s http://127.0.0.1:8000/api/reviews/rev_123/context/batch \
  -H 'content-type: application/json' \
  -d '{"queries":["colchicine children","FMF phenotype"],"max_passages_per_query":4,"max_total_passages":8}'
```

Batch retrieval keeps per-query diagnostics and returns a deterministic merged context pack. If retrieval returns zero passages, inspect the index and retry with shorter keyword queries or PMID filters.
