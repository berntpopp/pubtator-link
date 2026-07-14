# REST API

pubtator-link serves a FastAPI REST surface alongside MCP. In `unified` transport both run
on one port (REST plus MCP at `/mcp`); `http` serves REST only. Interactive docs are at
`http://localhost:8000/docs` (Swagger UI) and `/redoc` (ReDoc) when
`PUBTATOR_LINK_ENABLE_DOCS=true`.

The REST surface is *not* the model-facing surface. LLM clients should use the MCP tools,
which return compact citable passages and budget metadata; REST returns upstream shapes.
Route access still depends on edge authentication — the reverse proxy must not publish this
backend as a general REST origin (see [Security](SECURITY.md)).

## Core

- `GET /` — root endpoint with service information
- `GET /health` — health check and status
- `GET /api/cache/stats` — cache statistics, only when `PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=true`
- `DELETE /api/cache/clear` — clear all publication-service caches, only when cache endpoints are explicitly enabled

## Publication export

- `GET /api/publications/export/{format}` — export publication annotations by PMIDs
- `GET /api/publications/pmc_export/{format}` — export PMC publications by PMC IDs

**Supported formats**: `pubtator`, `biocxml`, `biocjson`

```bash
# Export publication annotations in BioC JSON format
curl "http://127.0.0.1:8000/api/publications/export/biocjson?pmids=29355051,32511357"

# Export with full text (biocxml/biocjson only)
curl "http://127.0.0.1:8000/api/publications/export/biocxml?pmids=29355051&full=true"

# Export PMC publications
curl "http://127.0.0.1:8000/api/publications/pmc_export/biocjson?pmcids=PMC7696669,PMC8869656"
```

## Entity search

- `GET /api/entities/autocomplete` — find entity IDs through autocomplete

**Supported bioconcepts**: `Gene`, `Disease`, `Chemical`, `Species`, `Variant`, `CellLine`

```bash
# Find disease entities
curl "http://127.0.0.1:8000/api/entities/autocomplete?query=breast%20cancer&concept=Disease&limit=5"

# Find gene entities
curl "http://127.0.0.1:8000/api/entities/autocomplete?query=BRCA1&concept=Gene"
```

## Publication search

- `GET /api/search` — search publications by text, entity IDs, or relations, with sorting

```bash
# Free text search (default: relevance-based sorting)
curl "http://127.0.0.1:8000/api/search?text=breast%20cancer&page=1"

# Sort by publication date (newest first)
curl "http://127.0.0.1:8000/api/search?text=breast%20cancer&sort=date%20desc"

# Sort by publication date (oldest first)
curl "http://127.0.0.1:8000/api/search?text=autism&sort=date%20asc"

# Sort by relevance score (highest first)
curl "http://127.0.0.1:8000/api/search?text=epilepsy&sort=score%20desc"

# Entity-based search with sorting
curl "http://127.0.0.1:8000/api/search?text=@CHEMICAL_remdesivir&sort=date%20desc"

# Relation-based search
curl "http://127.0.0.1:8000/api/search?text=relations:ANY|@CHEMICAL_Doxorubicin|@DISEASE_Neoplasms"
```

**Supported sort options**

- `date desc` — newest publications first (default for date sorting)
- `date asc` — oldest publications first
- `score desc` — highest relevance first (default for relevance sorting)
- `score asc` — lowest relevance first

## Entity relations

- `GET /api/relations` — find related entities

**Supported relation types**: `treat`, `cause`, `cotreat`, `convert`, `compare`, `interact`,
`associate`, `positive_correlate`, `negative_correlate`, `prevent`, `inhibit`, `stimulate`,
`drug_interact`

```bash
# Find entities that interact with a chemical
curl "http://127.0.0.1:8000/api/relations?e1=@CHEMICAL_remdesivir&type=interact"

# Find diseases treated by a chemical
curl "http://127.0.0.1:8000/api/relations?e1=@CHEMICAL_Doxorubicin&type=treat&e2=Disease"
```

## Text annotation

Annotation is a two-step asynchronous protocol: submit returns a `session_id`, then poll for
results.

- `POST /api/annotations/submit` — submit text for NER processing
- `GET /api/annotations/{session_id}` — retrieve annotation results

```bash
# Submit text for gene entity extraction
curl -X POST "http://127.0.0.1:8000/api/annotations/submit" \
  -H "Content-Type: application/json" \
  -d '{"text": "The ESR1 mutations are associated with breast cancer", "bioconcept": "Gene"}'

# Retrieve results (use session_id from submit response)
curl "http://127.0.0.1:8000/api/annotations/abc123def456"
```
