# Architecture

pubtator-link is a live proxy in front of NCBI's PubTator3, plus a review-scoped retrieval
layer that turns fetched articles into compact, citable, durable passages. It stores no
copy of PubTator3 — there is no data bundle and no ingest step.

## Transports

Streamable HTTP only. The server always boots through the `pubtator-link` CLI:

- `unified` — FastAPI REST API **and** MCP at `/mcp` on one port (default).
- `http` — REST API only.

There is **no stdio transport**. SSE is not offered. TLS terminates at an external reverse
proxy.

## Project structure

```
pubtator-link/
├── pubtator_link/
│   ├── api/
│   │   ├── client.py           # PubTator3 API client with rate limiting
│   │   └── routes/             # FastAPI route definitions
│   ├── models/
│   │   ├── requests.py         # Request validation models
│   │   ├── responses.py        # Response models
│   │   ├── entities.py         # Bioconcept entity models
│   │   └── publications.py     # Publication models
│   ├── services/
│   │   └── publication_service.py  # Business logic with caching
│   ├── mcp/                    # MCP facade, tool registration, profiles, resources
│   ├── db/                     # Review re-RAG schema and migrations
│   ├── config.py               # Configuration management
│   ├── logging_config.py       # Structured logging
│   ├── server_manager.py       # Unified server management
│   └── cli.py                  # Typer command-line interface (pubtator-link)
└── pyproject.toml              # Project configuration
```

## Key components

- **API client** — rate-limited HTTP client respecting PubTator3 guidelines (at most
  3 requests/second upstream; the client defaults to 2.5).
- **Service layer** — business logic with async LRU caching.
- **Server manager** — unified handling of the transport modes.
- **Data models** — Pydantic models for type safety across requests and responses.
- **MCP facade** — FastMCP Streamable HTTP surface mounted at `/mcp`, built per tool
  profile (`readonly` / `lean` / `full`).

## Review re-RAG subsystem

The differentiator, and the reason a database exists. A review corpus is namespaced by a
caller-chosen `review_id`: preparation fetches sources, splits them into passages, and
persists them in PostgreSQL with pgvector. Retrieval is lexical by default, with optional
local dense reranking (see [Configuration](configuration.md)); lexical retrieval always
remains the fallback.

Consequences worth knowing:

- `review_id` is durable, not a request ID. Reusing it **appends** new PMIDs and treats
  already-prepared PMIDs as no-ops. Choose a stable project slug and never include PHI.
- Passages carry stable IDs and `stable_citation_key`s, so citations survive re-retrieval,
  later responses, and exported notes. Request-local labels like `S1` do not.
- Review retrieval excludes tables and references by default and returns budget metadata
  (`budget`, `total_chars`, `estimated_tokens`) so clients can avoid context blow-ups
  without shell post-processing.
- Follow-up reads should prefer the MCP resources (`pubtator://reviews/{review_id}`, its
  `sessions/`, `passages/`, `audit/`, and `llm-context/latest` children) over re-running
  tools.
- Without a database the review tools degrade: call `diagnostics`, then fall back to
  `get_publication_passages` with the same PMIDs. Self-hosted deployments repair a stale
  schema with `make db-migrate`.

Design notes and the original proof of concept: [REVIEW_RERAG_POC.md](REVIEW_RERAG_POC.md).

## Performance characteristics

- **Rate limiting** — respects PubTator3's ceiling and protects the upstream from abuse.
- **Async architecture** — non-blocking I/O for concurrency.
- **Caching** — async LRU reduces upstream calls and latency.
- **Connection pooling** — efficient HTTP client management.
- **Graceful degradation** — documented fallbacks when an upstream or the review index is
  unavailable.
