# Review-Feeding Discovery Tools Design

Date: 2026-05-02

## Summary

Add NCBI-backed discovery tools that feed PubTator-Link review workflows:
MeSH vocabulary lookup, citation-to-PMID lookup, article ID conversion, and
related/cited/reference article expansion. The feature should close the next
competitive gap identified in the 2026-05-01 landscape documents without turning
PubTator-Link into a general reference manager.

The tools must return candidate PMIDs and explicit next-step metadata so LLM
clients can move directly into `pubtator.stage_research_session` or
`pubtator.index_review_evidence`.

## Context

The completed roadmap already covers source coverage preflight, resolver
attempts, retry/backoff, bounded preparation parallelism, passage lookup,
neighboring passages, typed MCP schemas, review index lifecycle, GRADE-style
certainty storage, audit bundles, Europe PMC fallback, and research-session
staging.

The strongest remaining competitor gap is PubMed workflow parity from mature
PubMed MCPs:

- true MeSH vocabulary lookup,
- ECitMatch-style citation lookup,
- PMID/PMCID/DOI conversion as a public discovery surface,
- related, cited-by, and reference expansion.

PubTator-Link should add these only where they help build or refine a review
candidate corpus.

## Goals

1. Add a focused NCBI discovery client using E-utilities-compatible endpoints.
2. Expose four read-only MCP tools:
   - `pubtator.convert_article_ids`
   - `pubtator.lookup_mesh`
   - `pubtator.lookup_citation`
   - `pubtator.find_related_articles`
3. Add matching REST routes under a discovery namespace for non-MCP clients.
4. Return typed Pydantic output models with candidate PMIDs, source diagnostics,
   and `_meta.next_commands`.
5. Reuse existing retry/backoff policy and conservative timeouts.
6. Keep every output research-use scoped and suitable for staging/indexing.

## Non-Goals

- Do not add citation formatting as a primary feature in this slice.
- Do not add journal analytics, trend charts, or bibliometric scoring.
- Do not add Semantic Scholar, OpenAlex, Crossref, or CORE integrations.
- Do not scrape publisher pages or fetch PDFs.
- Do not compute screening decisions, evidence certainty, or clinical advice.
- Do not make these tools mutate review indexes; they only return candidates.

## Proposed Public Surface

### `pubtator.convert_article_ids`

Input:

- `ids: list[str]`
- `source: "pmid" | "pmcid" | "doi" | "auto" = "auto"`
- `target: list["pmid" | "pmcid" | "doi"] | None = None`

Output:

- `records`: one record per requested identifier,
- `candidate_pmids`: PMIDs resolved from the input set,
- `unresolved`: identifiers that could not be mapped,
- `_meta.next_commands`: staging and indexing suggestions when PMIDs are present.

### `pubtator.lookup_mesh`

Input:

- `query: str`
- `limit: int = 10`
- `exact: bool = False`

Output:

- MeSH descriptor records with UI, name, scope note, entry terms, tree numbers,
  and optional search term suggestions,
- `candidate_pmids`: empty by default because this is vocabulary lookup, not
  literature retrieval,
- `_meta.next_commands`: suggested `pubtator.search_literature` calls using the
  descriptor name or MeSH term.

### `pubtator.lookup_citation`

Input:

- `citations: list[str]`

Output:

- one result per citation with `matched`, `not_found`, or `ambiguous` status,
- PMID, DOI, title, journal/year metadata when available,
- `candidate_pmids` for matched citations,
- `_meta.next_commands` for staging/indexing matched PMIDs.

### `pubtator.find_related_articles`

Input:

- `pmids: list[str]`
- `mode: "similar" | "cited_by" | "references" = "similar"`
- `limit: int = 20`

Output:

- related article records with PMID, title, journal/year metadata when fetched,
  relation mode, and source PMID,
- `candidate_pmids` deduplicated in stable order,
- unresolved or unsupported source PMIDs,
- `_meta.next_commands` for staging/indexing candidate PMIDs.

## Architecture

### Models

Create `pubtator_link/models/discovery.py` for request and response models. Keep
the models independent from review storage so the discovery layer can be tested
without a database.

Core models:

- `ArticleIdKind`
- `ArticleIdConversionRecord`
- `ArticleIdConversionResponse`
- `MeshDescriptor`
- `MeshLookupResponse`
- `CitationLookupStatus`
- `CitationLookupRecord`
- `CitationLookupResponse`
- `RelatedArticleMode`
- `RelatedArticleRecord`
- `RelatedArticlesResponse`
- `DiscoveryMeta`

`DiscoveryMeta` should contain:

- `source_urls: list[str]`
- `next_commands: list[dict[str, object]]`
- `research_use_only: bool = True`

### Client

Create `pubtator_link/services/ncbi_discovery.py` with an async
`NcbiDiscoveryClient`.

The client owns NCBI-specific HTTP behavior:

- base URL: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils`,
- endpoint methods for ID conversion, MeSH lookup, ECitMatch, and article links,
- use existing `RetryPolicy`/`call_with_retries`,
- conservative timeout and user-agent parameters,
- optional email/API key config fields if provided later.

The client should parse structured XML or JSON with standard parsers. It should
not use ad hoc regex parsing for XML responses.

### Service

Create `DiscoveryService` in the same module or a small companion module if the
client becomes too large. The service maps client records to public Pydantic
responses and builds `_meta.next_commands`.

The service is responsible for:

- stable deduplication of candidate PMIDs,
- preserving input order,
- limiting response size,
- converting upstream failures into structured partial results where possible,
- keeping all tools read-only.

### REST Routes

Create `pubtator_link/api/routes/discovery.py` and register it with the FastAPI
app. Suggested routes:

- `POST /api/discovery/convert-article-ids`
- `GET /api/discovery/mesh`
- `POST /api/discovery/lookup-citations`
- `POST /api/discovery/related-articles`

Route behavior should mirror MCP responses.

### MCP Tools

Create `pubtator_link/mcp/tools/discovery.py` and register it from
`pubtator_link/mcp/facade.py`.

Every tool must:

- use typed output schemas,
- include research-use language in the description,
- avoid destructive behavior,
- return model dumps by alias where needed,
- include candidate handoff metadata.

## Data Flow

1. User or LLM calls a discovery tool.
2. Tool validates input with Pydantic/FastMCP.
3. `DiscoveryService` calls `NcbiDiscoveryClient`.
4. Client applies retry/backoff around idempotent NCBI requests.
5. Service maps upstream records into typed response models.
6. Response includes `candidate_pmids` and `_meta.next_commands`.
7. Client can pass PMIDs to `pubtator.stage_research_session` or
   `pubtator.index_review_evidence`.

## Error Handling

Use partial responses rather than failing the entire request when one identifier,
citation, or PMID cannot be resolved.

Recommended status values:

- ID conversion: `resolved`, `unresolved`, `invalid`, `failed`
- Citation lookup: `matched`, `not_found`, `ambiguous`, `failed`
- Related articles: `resolved`, `no_links`, `failed`

Request-level failures should use existing FastAPI/MCP error handling only for
invalid input, malformed upstream responses that prevent parsing the whole
response, or exhausted transport failures.

## Testing

Unit tests:

- model validation and serialization,
- client parsing for representative NCBI responses,
- retry metadata propagation on transient failures,
- service deduplication and `_meta.next_commands`,
- MCP adapter output schemas and model dumps,
- route behavior with fake service dependencies.

Contract tests:

- tool inventory includes the four discovery tools,
- output schemas are specific and not generic objects,
- tool descriptions include research-use boundaries.

No network tests are required in CI.

## Documentation

Update:

- README MCP tool table,
- `pubtator_link/mcp/resources.py` capabilities text,
- competitor/capability roadmap docs to mark this slice as planned or complete
  after implementation.

## Acceptance Criteria

- MCP exposes the four discovery tools with typed output schemas.
- REST exposes equivalent discovery endpoints.
- All discovery outputs include candidate PMIDs when applicable.
- All matched candidate PMID outputs include `_meta.next_commands` that point to
  research-session staging or review indexing.
- Invalid or unresolved individual inputs do not discard successful records.
- Unit and route tests pass without network access.
- `make ci-local` passes before claiming implementation complete.
