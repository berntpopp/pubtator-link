# Configuration

Every setting is read from the environment (or `.env`) by `pubtator_link/config.py`.
**Every name carries the `PUBTATOR_LINK_` prefix.** The prefix is not optional: `config.py`
sets `env_prefix="PUBTATOR_LINK_"` with `extra="ignore"`, so an unprefixed name such as
`PORT` or `LOG_LEVEL` is *silently discarded* — no error, no warning, no effect.

The tables below cover the settings you are most likely to change, not all of them;
`config.py` remains the complete list. Start from [`.env.example`](../.env.example) and
inspect what actually resolved:

```bash
pubtator-link config --validate
```

## Server

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBTATOR_LINK_HOST` | `127.0.0.1` | Server host address |
| `PUBTATOR_LINK_PORT` | `8000` | Server port |
| `PUBTATOR_LINK_TRANSPORT` | `unified` | `unified` (REST + MCP at `/mcp`) or `http` (REST only). There is no stdio transport. |
| `PUBTATOR_LINK_MCP_PATH` | `/mcp` | MCP endpoint path |
| `PUBTATOR_LINK_HTTP_MAX_REQUEST_BYTES` | see `config.py` | Inbound request-body cap |
| `PUBTATOR_LINK_ENABLE_INBOUND_RATE_LIMIT` | `false` | Enable the inbound (caller-facing) rate limiter |
| `PUBTATOR_LINK_INBOUND_RATE_LIMIT_PER_MINUTE` | see `config.py` | Inbound rate-limit budget |
| `PUBTATOR_LINK_TRUST_PROXY_HEADERS` | `false` | Trust `X-Forwarded-For` (rightmost entry) — only behind a known reverse proxy |

## Upstream APIs

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBTATOR_LINK_API_BASE_URL` | `https://www.ncbi.nlm.nih.gov/research/pubtator3-api` | PubTator3 API base URL |
| `PUBTATOR_LINK_API_TIMEOUT` | `30` | PubTator3 request timeout (seconds) |
| `PUBTATOR_LINK_RATE_LIMIT_PER_SECOND` | `2.5` | Outbound rate limit. **PubTator3 permits at most 3 requests/second — do not raise this above 3.** |
| `PUBTATOR_LINK_TEXT_API_BASE_URL` | `https://www.ncbi.nlm.nih.gov/CBBresearch/Lu/Demo/RESTful` | Text-processing (NER submission) API |
| `PUBTATOR_LINK_TEXT_API_TIMEOUT` | `60` | Text-processing request timeout (seconds) |

Optional metadata-enrichment upstreams (Europe PMC fallback, Crossref, OpenAlex, Unpaywall)
have their own `PUBTATOR_LINK_*` knobs — including polite-pool contact addresses
(`PUBTATOR_LINK_CROSSREF_MAILTO`, `PUBTATOR_LINK_OPENALEX_MAILTO`,
`PUBTATOR_LINK_UNPAYWALL_EMAIL`) — see `config.py`.

## MCP tool profiles and auth

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBTATOR_LINK_MCP_PROFILE` | `readonly` | `readonly` (full read surface, no write tools) · `lean` (reads + review-index writes) · `full` (complete write surface incl. audit-bundle file export) |
| `PUBTATOR_LINK_MCP_SERVICE_TOKEN` | unset | Optional bearer token for `/mcp`. Unset (default) leaves `/mcp` open for read-only access; set it to bearer-gate the transport (must match the router's `GF_PUBTATOR_TOKEN`). Generate with `openssl rand -hex 32`. |
| `PUBTATOR_LINK_ALLOW_UNAUTHENTICATED_WRITES` | `false` | Loopback-only development exception |
| `PUBTATOR_LINK_ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | Exact Host allowlist |
| `PUBTATOR_LINK_ALLOWED_ORIGINS` | empty | Browser Origin allowlist (request admission; distinct from CORS response headers) |
| `PUBTATOR_LINK_REVIEW_EXPORT_BASE_DIR` | unset | Base directory for `export_review_audit_bundle` files. **Unset disables file export.** |

The three allowlists (`..._ALLOWED_HOSTS`, `..._ALLOWED_ORIGINS`, `..._CORS_ORIGINS`) accept
either comma-separated values, as `.env.example` writes them, or a JSON array, as
`docker/docker-compose.yml` writes them.

Write-capable profiles require service auth unless the loopback-only exception is enabled.
The full rationale, rollout order, and token-rotation procedure are in [Security](SECURITY.md).

## Review re-RAG database

The review-index tools need PostgreSQL with pgvector. Without a database they degrade;
call `diagnostics` and fall back to `get_publication_passages`.

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBTATOR_LINK_DATABASE_URL` | unset | PostgreSQL URL. Required by `make db-init` / `make db-migrate`. |
| `PUBTATOR_LINK_AUTO_MIGRATE` | see `config.py` | Apply idempotent migrations at startup |
| `PUBTATOR_LINK_REQUIRE_SCHEMA_CURRENT` | see `config.py` | Refuse to serve on a stale review schema |
| `PUBTATOR_LINK_POSTGRES_DB` / `_USER` / `_PASSWORD` / `_PORT` | see `.env.example` | Compose sidecar credentials. Production supplies the password from a secret store, with no fallback. |

Preparation and retrieval are bounded by `PUBTATOR_LINK_REVIEW_PREP_CONCURRENCY`,
`PUBTATOR_LINK_REVIEW_RETRIEVAL_CONCURRENCY`, `PUBTATOR_LINK_REVIEW_PREFLIGHT_CONCURRENCY`,
per-document/source timeouts, `PUBTATOR_LINK_REVIEW_INDEX_TTL_SECONDS`, and download caps
(`PUBTATOR_LINK_REVIEW_PREP_PDF_MAX_BYTES`, `..._TEXT_MAX_BYTES`). `index_review_evidence`
caps `pmids` and `curated_urls` at 200 entries each.

### Optional local embedding rerank

Private deployments can enable local dense reranking for review retrieval:

```bash
PUBTATOR_LINK_REVIEW_EMBEDDING_RERANK_ENABLED=true
PUBTATOR_LINK_REVIEW_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
PUBTATOR_LINK_REVIEW_EMBEDDING_DIM=384
```

Lexical retrieval remains the fallback when embeddings are missing, the model is
unavailable, or `pgvector` is not installed.

## Caching

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBTATOR_LINK_CACHE_SIZE` | `1000` | LRU cache size |
| `PUBTATOR_LINK_CACHE_TTL` | `3600` | Cache TTL (seconds) |
| `PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS` | `false` | Expose the opt-in cache management REST endpoints |

The caching system uses async LRU caching with configurable size and TTL:

- **Publication export** — cached by PMIDs, format, and full-text flag.
- **Entity autocomplete** — cached by query, concept, and limit.
- **Publication search** — cached by query text and page number.
- **Entity relations** — cached by entity, relation type, and target type.

Cache management endpoints are disabled by default. With
`PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=true`, `/api/cache/stats` and `/api/cache/clear`
appear. The clear endpoint clears *all* publication-service async-lru caches;
pattern-based clearing is rejected until scoped invalidation exists.

## Logging, docs, and CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBTATOR_LINK_LOG_LEVEL` | `INFO` | Logging level |
| `PUBTATOR_LINK_LOG_FORMAT` | `console` | `console` for development, `json` for production |
| `PUBTATOR_LINK_ENABLE_DOCS` | `true` | Serve the interactive REST docs at `/docs` |
| `PUBTATOR_LINK_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | CORS **response** headers. Distinct from `PUBTATOR_LINK_ALLOWED_ORIGINS`, which admits the request. |

## CLI

The `pubtator-link` CLI follows the GeneFoundry Logging & CLI Standard v1:

```bash
pubtator-link serve --transport unified --host 127.0.0.1 --port 8000  # REST + MCP
pubtator-link serve --transport http    --host 127.0.0.1 --port 8000  # REST only
pubtator-link config --validate                                       # resolved config
pubtator-link health --url http://127.0.0.1:8000                      # probe /health
pubtator-link version                                                 # installed version
```
