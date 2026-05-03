# Literature Map Epic Design

## Status

Approved design captured from brainstorming on 2026-05-03.

## Goal

Build a staged, metadata-first literature exploration epic for PubTator-Link:
article citation graphs, related evidence candidate discovery, and bounded topic
literature maps across citations, authors, and PubTator entities.

This is research infrastructure. It helps researchers and LLM clients decide
what to inspect next. It does not infer biomedical truth, make clinical
recommendations, or claim that graph neighbors support a biomedical claim.

## Scope

The epic ships in three independently testable increments:

1. **Citation graph primitive** for issue #2.
   Add `pubtator.get_publication_citation_graph` and
   `POST /api/publications/citation-graph`. The service accepts exactly one
   PMID or DOI, retrieves outgoing references and incoming citations where
   available, resolves identifiers opportunistically, and returns normalized
   citation-neighbor records with provenance and provider warnings.

2. **Related evidence primitive** for issue #3.
   Add `pubtator.find_related_evidence_candidates` and
   `POST /api/publications/related-evidence`. The service centers on NCBI
   ELink similar articles with `neighbor_score` where available, merges
   optional citation neighbors from the citation graph service, enriches
   candidates with metadata and full-text hints, and ranks candidates with
   transparent reasons.

3. **Topic literature map orchestrator** for issue #4.
   Add `pubtator.build_topic_literature_map` and
   `POST /api/publications/topic-literature-map`. The service takes a query,
   seed PMIDs, or both, builds a bounded graph of papers, authors, entities,
   citations, and related-article edges, then returns structured graph JSON and
   a compact LLM-oriented summary.

## Non-Goals

- Do not scrape publisher full text or bypass paywalls.
- Do not ingest Sci-Hub, LibGen, or other unauthorized sources.
- Do not add paid publisher APIs as required dependencies.
- Do not call the topic map a biomedical knowledge graph in user-facing output.
- Do not infer claim support or evidence certainty from graph structure alone.
- Do not add unbounded recursive citation crawling.
- Do not add embeddings or vector infrastructure in the first epic.
- Do not automatically run review preparation for every graph neighbor.
- Do not add deprecated `_v2` MCP tools or nested `{request: ...}` wrappers.

## External Sources

Use free and legal metadata, identifier, annotation, and availability sources:

- PubTator3 search, metadata, and annotations for topic and entity discovery.
- NCBI E-utilities ELink for PubMed related articles, references, cited-by
  links, and `neighbor_score` related-article scores.
- Crossref Works API for DOI metadata and outgoing references when deposited
  references are available.
- Europe PMC search/citation/reference APIs for PMID/DOI metadata, citation
  networks, and OA/full-text flags.
- OpenAlex Works API for work lookup, authorships, referenced works,
  cited-by URLs, related works, and OA hints.
- Unpaywall for DOI OA status and best OA location. Unpaywall is enabled only
  when `UNPAYWALL_EMAIL` is configured. Otherwise the OA-status step is skipped
  and a `provider_disabled` warning is emitted.

Provider outputs are best-effort metadata. Every normalized node and edge must
carry provenance sufficient to explain where it came from.

Provider clients that support polite pools must identify PubTator-Link when
configured. Crossref requests use `CROSSREF_MAILTO`; OpenAlex requests use
`OPENALEX_MAILTO`.

## Architecture

Add focused literature graph models under
`pubtator_link/models/literature_graph.py`. Do not continue expanding
`pubtator_link/models/discovery.py` for the graph-specific response shapes.

Add small provider clients or helpers rather than a generic graph framework:

- `CrossrefClient`: DOI work lookup and reference extraction.
- `EuropePmcClient`: PMID/DOI metadata, citation/reference lookup where useful,
  and OA/full-text flags.
- `OpenAlexClient`: work lookup, referenced works, cited-by URL, related works,
  authorships, and OA hints.
- `UnpaywallClient`: DOI OA status and best OA location.
- Extend `NcbiDiscoveryClient` to support ELink `neighbor_score` parsing while
  preserving existing `find_related_articles` behavior.
- New REST routes and MCP tools emit telemetry through the existing metrics and
  MCP telemetry contract, including request counts, failures, and latency where
  the current instrumentation supports those dimensions.

Add three service boundaries:

- `CitationGraphService` owns provider fan-out, DOI/PMID resolution,
  citation-neighbor normalization, and provider warnings.
- `RelatedEvidenceService` owns ELink-centered candidate discovery,
  deduplication, availability-aware ranking, filters, caution text, and match
  reasons.
- `TopicLiteratureMapService` owns bounded graph construction, centrality
  scoring, bridge selection, author/entity/citation/related edges, summary
  generation, and retrieval hints. It calls service interfaces, not raw provider
  clients.

## Shared Data Model

Define shared graph-oriented models:

- `LiteraturePaper`: normalized article metadata with `pmid`, `doi`, `pmcid`,
  `openalex_id`, `title`, `journal`, `year`, `publication_types`, `authors`,
  `availability`, and `provenance`.
- `LiteratureAuthor`: display name plus ORCID/OpenAlex author ID and
  affiliations when available.
- `LiteratureEntity`: PubTator entity ID, type, name, and mention provenance.
- `LiteratureGraphNode`: typed node wrapper for `paper`, `author`, and
  `entity`.
- `LiteratureGraphEdge`: `cites`, `cited_by`, `authored_by`,
  `mentions_entity`, `related_by_elink`, and `related_by_pubtator_search`
  edges with `source`, `target`, `weight`, `reasons`, and `provenance`.
- `ProviderWarning`: provider name, status, retryability, and sanitized message.

Response models:

- `PublicationCitationGraphResponse`
- `RelatedEvidenceCandidatesResponse`
- `TopicLiteratureMapResponse`

Deduplicate papers by stable key in this order:

1. PMID
2. DOI lowercased
3. PMCID
4. OpenAlex ID

Deduplicate edges by `(source_key, target_key, edge_type)`. Store provenance as
a list on the edge. If multiple providers support the same conceptual edge,
merge reasons and append provider-specific provenance entries without hiding the
individual sources.

## Citation Graph Flow

Inputs:

- `pmid: str | None`
- `doi: str | None`
- `direction: "references" | "cited_by" | "both" = "both"`
- `resolve_metadata: bool = true`
- `include_open_access_status: bool = true`
- `max_results: int = 50`

Validation requires exactly one of `pmid` or `doi`.

Flow:

1. Resolve the source article from PMID or DOI using existing ID conversion and
   publication metadata, with Europe PMC and OpenAlex fallback.
   Partial identifier resolution is a soft path: a DOI-resolved source without a
   PMID can still return DOI/OpenAlex/Crossref-derived graph data, with a
   warning that PMID-only providers were skipped.
2. Fetch outgoing references from Crossref by DOI first, OpenAlex
   `referenced_works` second, and Europe PMC references where PMID or PMCID
   coverage exists.
3. Fetch incoming citations from Europe PMC citations and NCBI ELink
   `pubmed_pubmed_citedin` first, then OpenAlex `cited_by_api_url` when
   available.
4. Normalize all neighbors into `LiteraturePaper` records.
5. Mark each neighbor with one of:
   `resolved_full_text_candidate`, `resolved_metadata_only`,
   `unresolved_reference`, or `publisher_entitlement_required`.
6. Return source metadata, `references`, `cited_by`, `candidate_pmids`,
   `metadata_only`, and provider warnings.

## Related Evidence Flow

Inputs:

- `pmid: str`
- `max_results: int = 25`
- `prefer_full_text: bool = true`
- `include_pubtator_search: bool = true`
- `include_citation_neighbors: bool = true`
- `publication_types: list[str] | None = None`
- `year_min: int | None = None`
- `year_max: int | None = None`

Validation requires a numeric PMID string and bounded `max_results`.

Flow:

1. Fetch source metadata and PubTator entities when available.
2. Query NCBI ELink similar articles using `cmd=neighbor_score` so
   `pubmed_neighbor_score` is retained.
3. Optionally merge citation graph neighbors from the citation graph service.
4. Optionally run bounded PubTator search from source title and entity terms.
5. Enrich candidates with metadata, publication types, availability, and shared
   entities when cheap.
6. Rank deterministically with a lexicographic ordering rather than opaque
   weighted scoring:
   ELink score descending, full-text availability when `prefer_full_text=true`,
   shared-entity count descending, requested publication type match,
   publication year descending, and PMID ascending as the final stable
   tiebreaker.
7. Emit match reasons and caution text. Do not label candidates as substitutes
   or claim-supporting articles.

## Topic Literature Map Flow

Inputs:

- `query: str | None`
- `pmids: list[str] | None`
- `max_seed_papers: int = 25`
- `max_neighbors_per_paper: int = 10`
- `include_authors: bool = true`
- `include_citations: bool = true`
- `include_pubtator_entities: bool = true`
- `include_related_candidates: bool = true`
- `year_min: int | None = None`
- `year_max: int | None = None`
- `prefer_full_text: bool = true`

Validation requires at least one of `query` or `pmids`.

Flow:

1. Seed from explicit PMIDs and/or PubTator search results for `query`.
2. Cap seeds with `max_seed_papers`.
3. For each seed, add the paper node, author edges, PubTator entity edges,
   citation edges, and related-candidate edges according to input flags.
4. Cap expansion with `max_neighbors_per_paper`; do not recursively crawl beyond
   the first neighborhood.
5. Compute explainable centrality from graph-structural signals only, using a
   lexicographic ordering:
   seed membership, citation/related degree descending, shared-entity degree
   descending, author connectivity descending, publication year descending, and
   stable paper key ascending as the final tiebreaker. Treat accessibility as a
   separate retrieval-priority signal, not as evidence that a paper is
   structurally central.
6. Build summary sections from deterministic selectors:
   central papers, recent connected papers, bridge papers, dominant author
   groups, accessible candidates, closed central sources, and next retrieval
   set.
7. Return `summary`, `nodes`, `edges`, `candidate_retrieval_hints`, `warnings`,
   and limitations.

## REST API

Use publication-centered endpoints:

- `POST /api/publications/citation-graph`
- `POST /api/publications/related-evidence`
- `POST /api/publications/topic-literature-map`

Use POST for all three because the inputs include lists, flags, and bounded
future options. This matches existing publication endpoints such as
`/api/publications/metadata`, `/api/publications/passages`, and
`/api/publications/context-estimate`.

## MCP Tools

Expose flat canonical tool signatures:

- `pubtator.get_publication_citation_graph`
- `pubtator.find_related_evidence_candidates`
- `pubtator.build_topic_literature_map`

All tools are read-only, open-world, and research-use scoped. Use typed
`output_schema`, `READ_ONLY_OPEN_WORLD` annotations, and `run_mcp_tool`.

Profile exposure:

- `pubtator.get_publication_citation_graph`: `lean`, `full`, and `readonly`.
- `pubtator.find_related_evidence_candidates`: `lean`, `full`, and `readonly`.
- `pubtator.build_topic_literature_map`: `full` first. Add to `lean` only in a
  separate follow-up after payload size and latency are proven.

The generated MCP catalog must include the new tools from runtime registration.
Regenerate `docs/mcp-tool-catalog.md` with
`uv run python scripts/generate_mcp_tool_catalog.py`, and keep
`tests/unit/mcp/test_mcp_tool_catalog.py` passing.

## Error Handling And Degradation

Provider failures produce structured warnings when another provider can still
answer. Hard failures are limited to:

- Invalid request input.
- No resolvable source article when a source article is required.
- Total upstream failure where no provider returns usable seed data.

Warnings include provider name, failure status, retryability, and sanitized
message. Responses include `research_use_only: true` and limitations text where
the output could otherwise be mistaken for evidence quality or claim support.

## Caching

Caching is conservative:

- Reuse existing HTTP retry and rate-limit patterns.
- Add cache keys by provider and normalized identifier where the current cache
  infrastructure fits.
- Prefer short-lived metadata cache entries for high-fanout providers:
  Crossref, OpenAlex, Europe PMC, and Unpaywall.
- Do not add destructive cache operations to MCP.
- Do not make cache stats part of this epic.

## Bounds And Hosted Safety

Initial bounds:

- Citation graph `max_results <= 100`, default 50.
- Related evidence `max_results <= 100`, default 25.
- Topic map `max_seed_papers <= 50`, default 25.
- Topic map `max_neighbors_per_paper <= 20`, default 10.

Services must avoid unbounded provider fan-out. Hosted MCP responses should
favor compact summaries and retrieval hints over dumping every provider field.

## Testing Strategy

Use mocked unit tests for provider parsing and service behavior, plus route and
MCP surface tests.

Real-network integration tests and VCR-style recorded provider tests are out of
scope for this epic. The specific DOI and PMID identifiers in acceptance
criteria refer to mocked fixture payloads under `tests/fixtures/`, not live
provider calls.

Provider parsing tests:

- Crossref reference extraction from a mocked DOI work payload.
- Europe PMC citation/reference and OA/full-text fields from mocked payloads.
- OpenAlex work, authorship, referenced work, related work, cited-by, and OA
  fields from mocked payloads.
- Unpaywall OA status and best OA location from mocked payloads.
- NCBI ELink `neighbor_score` parsing from mocked JSON or XML payloads.

Citation graph tests:

- Exactly-one identifier validation.
- DOI/PMID resolution.
- Outgoing reference normalization.
- Incoming citation normalization.
- Partial provider failure with warnings.
- Metadata-only versus full-text-candidate status.

Related evidence tests:

- ELink score parsing.
- Deduplication across providers.
- `prefer_full_text=true` ranking behavior.
- Publication type and year filters.
- Provider warnings.
- Caution text.

Topic map tests:

- Graph construction from mocked query results and seed PMIDs.
- Node and edge deduplication.
- Author and entity edges.
- Central paper selection.
- Bridge paper selection.
- Next retrieval hints.
- Bounded expansion.

Surface tests:

- REST validation and response serialization for all three endpoints.
- MCP flat signatures and output schemas.
- MCP profile registration.
- Generated MCP catalog inclusion.

Required final verification before merge is `make ci-local`.

## Acceptance Criteria

- Citation graph service returns references for DOI
  `10.1016/j.ard.2025.05.020` using mocked Crossref payloads.
- Citation graph service returns cited-by results for PMID `40562663` using
  mocked Europe PMC or NCBI ELink payloads.
- Related evidence service parses mocked NCBI ELink neighbor-score results.
- Related candidates include provenance and transparent match reasons.
- If `prefer_full_text=true`, accessible candidates rank ahead of otherwise
  similar abstract-only candidates.
- Topic map service builds a small map from mocked query results and seed PMIDs.
- Nodes and edges are deduplicated across provider IDs where possible.
- Topic map output includes provenance, warnings, limitations, compact summary,
  structured graph, and retrieval hints.
- REST routes validate request invariants.
- MCP tools expose flat canonical signatures and appear in expected profiles.
- Partial provider failures degrade gracefully when core seed data exists.
- `make ci-local` passes before merge.

## Implementation Notes

The implementation plan should follow the staged order. Each increment should
land with focused models, service tests, route tests, MCP tests, and generated
catalog updates before moving to the next increment.

The topic map service should compose the citation graph and related evidence
services. It should not duplicate raw provider parsing logic from the lower
layers.
