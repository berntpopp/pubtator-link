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

## Retrieve Context

```bash
curl -s http://127.0.0.1:8000/api/reviews/rev_123/context \
  -H 'content-type: application/json' \
  -d '{"question":"Should colchicine start after clinical diagnosis of FMF?","max_passages":8,"max_chars":6000}'
```

The context pack is generated fresh for each request. It can change as more passages are prepared.
