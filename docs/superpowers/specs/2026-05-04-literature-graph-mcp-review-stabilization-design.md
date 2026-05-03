# Literature Graph MCP Review Stabilization Design

## Status

Approved scope for stacked PR work on 2026-05-04.

## Problem

Recent end-to-end MCP use showed that the new literature graph tools are useful
for corpus selection, but several seams now hurt review workflows:

- Citation graph, topic map, and related evidence do not agree on
  `has_pmc_full_text` and `is_open_access` for the same PMID.
- DOI-to-PMID resolution depends primarily on the PMC ID Converter, which only
  returns related IDs for articles present in PMC. DOI-only references outside
  PMC become dead ends even when PubMed or OpenAlex can resolve them.
- Compact topic maps hide the most useful graph summaries by returning empty
  `central_papers`, `recent_connected_papers`, `bridge_papers`, and
  `accessible_full_text_candidates` arrays while reporting hundreds of omitted
  nodes and edges.
- Graph next commands still include the deprecated `prepare_mode` argument even
  though MCP schema policy tells clients to omit it.
- `retrieve_review_context_batch` defaults often drop relevant passages in
  multi-query review runs because fixed char budgets are too small for the
  requested passage counts.
- Related evidence exposes raw NCBI neighbor scores without a normalized score
  useful across calls.
- Repeated disabled Unpaywall warnings consume context without adding action.

The desired result is not a new graph product. It is a stabilization pass that
makes the current graph and retrieval tools predictable, compact, and consistent
for LLM literature-review orchestration.

## Research Basis

Provider behavior checked while triaging the review:

- OpenAlex Works exposes DOI, PMID, PMCID, open-access fields, `ids.*`, and the
  `cites` filter for incoming citation lookups. It can resolve the EULAR DOI
  `10.1136/annrheumdis-2015-208690` to PMID `26802180`.
  Source: <https://developers.openalex.org/api-reference/works>
- OpenAlex single-work lookup accepts external IDs such as DOI, PMID, and PMCID.
  Source: <https://developers.openalex.org/api-reference/works/get-a-single-work>
- PMC ID Converter converts DOI/PMID/PMCID identifiers, but its own
  documentation states it only returns related IDs if the article is in PMC.
  Source: <https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/>
- NCBI E-utilities provide the structured interface to Entrez/PubMed and can be
  used as a DOI fallback via PubMed ESearch using article identifier field
  searches.
  Source: <https://www.ncbi.nlm.nih.gov/books/NBK25501/>
- Unpaywall exposes `is_oa`, `oa_status`, and `best_oa_location` fields, but
  the API requires an email. When no email is configured, warnings should be
  coalesced and should not be the primary OA signal.
  Source:
  <https://support.unpaywall.org/support/solutions/articles/44002142311-what-do-the-fields-in-the-api-response-and-snapshot-records-mean->

## Goals

- Make one canonical paper availability answer flow through citation graph,
  topic map, and related evidence.
- Improve DOI-to-PMID conversion enough that high-value non-PMC references,
  including guideline DOIs, become actionable PMIDs when provider data exists.
- Keep compact graph responses compact while still carrying useful summaries.
- Remove deprecated `prepare_mode` from active graph/discovery next commands.
- Reduce avoidable retrieval truncation in normal multi-query review batches.
- Add normalized related-evidence score signals without removing raw scores.
- Keep provider transparency and research-use guardrails.
- Stack all changes on PR #19.

## Non-Goals

- Do not add paid provider dependencies.
- Do not scrape publisher pages or bypass access controls.
- Do not remove existing response fields in this PR; compatibility fields may
  remain while new compact fields are added.
- Do not replace the review indexing pipeline.
- Do not build a full `corpus_select` convenience tool in this pass. Add enough
  standardized signals that such a tool can be implemented later.

## Architecture

The fix has four phases that can ship in one stacked PR:

1. Shared resolver consistency layer.
2. Compact graph contract cleanup.
3. Review retrieval budget upgrade.
4. Tool UX and documentation cleanup.

The design keeps existing service entry points, but moves duplicated paper
mapping into a small shared helper module so the three graph tools can call the
same mapping and merge logic.

## Phase 1: Resolver Consistency Layer

Add a shared literature paper resolver/mapping module responsible for:

- building `LiteraturePaper` from PubMed metadata;
- merging availability flags from PubMed metadata, PMCID presence, OpenAlex,
  Europe PMC, and Unpaywall;
- resolving DOI to PMID through a cascade:
  1. PMC ID Converter;
  2. OpenAlex single-work DOI lookup;
  3. PubMed ESearch article identifier lookup.

Provider statuses should distinguish:

- `ncbi_idconv_resolved`
- `not_in_pmc`
- `openalex_resolved`
- `pubmed_esearch_resolved`
- `provider_no_match`
- `provider_failed`
- `skipped`

For source paper metadata, PMCID implies `has_pmc_full_text=true` and
`is_open_access=true` unless a future provider explicitly proves otherwise. This
matches the behavior already used by related evidence after the review follow-up
patch.

Citation graph should use the shared mapper for:

- source paper from PMID or DOI;
- Crossref reference records after DOI resolution;
- OpenAlex referenced and citing works;
- Europe PMC cited-by works.

Related evidence and topic map should use the same metadata-to-paper helper
instead of each maintaining a private version.

## Phase 2: Compact Graph Contract Cleanup

Compact graph responses should keep the information an LLM needs to decide what
to retrieve next.

Topic map compact mode:

- populate `summary.central_papers`, `summary.recent_connected_papers`, and
  `summary.bridge_papers` with bounded compact paper summaries;
- keep `summary.accessible_full_text_candidates` only if it adds details beyond
  `accessible_full_text_pmids`; otherwise omit or leave empty intentionally and
  document the PMID list as canonical;
- keep `omitted_counts` and `_meta.truncated` for hidden topology;
- keep `top_candidates`, but add a deduped `signals` field per candidate that
  combines relevance reasons, rank reasons, and demotion reasons.

Citation graph compact mode:

- keep `reference_candidates` and `cited_by_candidates` as canonical compact
  lanes;
- leave legacy `references` and `cited_by` arrays empty in compact mode, but
  make the tool description explicit;
- add top-level counts:
  - `actionable_pmid_count`
  - `metadata_only_count`
  - `unresolved_doi_count`
- add compact-mode status hints so empty arrays cannot be mistaken for provider
  emptiness.

Related evidence compact mode:

- add `normalized_neighbor_score` in the range `0.0..1.0`, normalized within the
  returned candidate set;
- keep raw `pubmed_neighbor_score` for transparency;
- add `signals` as the deduped LLM-facing explanation while keeping
  `match_reasons` for compatibility.

## Phase 3: Review Retrieval Budget Upgrade

Change retrieval defaults and budget behavior to avoid silent loss of strong
sources in common multi-query batches.

MCP defaults should become more generous than REST/model defaults:

- `retrieve_review_context_batch` MCP default `max_chars`: `24000`.
- MCP default `max_response_chars`: `48000`.
- Keep model-level validation caps unchanged.

Add auto-fit logic when the caller does not explicitly provide budgets:

- derive an effective `max_chars` from requested
  `max_total_passages * max_chars_per_passage`, bounded by model caps;
- derive `max_response_chars` from the estimated JSON overhead;
- preserve explicit caller budgets exactly.

Budget advice should add:

- `estimated_tokens_to_unlock`;
- `dropped_pmid_count`;
- `dropped_priority_pmids`, capped and ordered by drop frequency or priority;
- a concrete retry suggestion that includes `max_chars`,
  `max_response_chars`, and `prioritize_pmids` when relevant.

Do not remove diagnostics. The goal is to need recovery less often and make
recovery cheaper when needed.

## Phase 4: Tool UX And Documentation Cleanup

Remove deprecated `prepare_mode` from active next commands generated by:

- `pubtator_link/services/citation_graph.py`
- `pubtator_link/services/topic_literature_map.py`
- `pubtator_link/services/ncbi_discovery.py`

Keep accepting `prepare_mode="selected"` in REST/model compatibility paths for
now.

Coalesce disabled Unpaywall warnings:

- one top-level provider status should say Unpaywall is disabled;
- repeated per-paper disabled warnings should be summarized, not repeated in
  candidate metadata or `_meta.warnings`.

Improve tool discovery without adding a new workflow engine:

- add a workflow bundle resource or catalog hint that lists the canonical
  search/map/graph/index/inspect/retrieve tools together;
- document that graph compact mode returns candidates and summary PMIDs, while
  `nodes_edges` returns topology and `full` returns legacy arrays;
- document that full graph mode can be large and should usually follow
  `response_size_class` or explicit user request.

## Data Flow

Graph flow:

1. Tool receives PMID/DOI/query.
2. Service gathers provider records.
3. Shared resolver normalizes IDs, metadata, availability, and provenance.
4. Service ranks candidates.
5. Response shaper produces `compact`, `nodes_edges`, or `full`.
6. `_meta` reports provider statuses, warnings, next commands, size class, and
   truncation.

Retrieval flow:

1. MCP adapter records whether the caller explicitly supplied budget args.
2. Adapter or model normalization derives effective budgets only for omitted
   args.
3. Retrieval service packs passages and diagnostics.
4. Dropped summary includes actionable budget advice and token estimate.

## Compatibility

- Existing REST fields remain.
- Existing MCP field names remain unless already hidden by compact serializers.
- New fields are additive.
- `prepare_mode="selected"` remains accepted for legacy REST/model callers, but
  no active tool examples or generated next commands should include it.

## Testing Strategy

Use TDD for every implementation task:

- provider unit tests for OpenAlex DOI lookup, OpenAlex cited-by fallback,
  PubMed ESearch DOI fallback, and PMC ID Converter `not_in_pmc`;
- resolver unit tests for consistent availability merging;
- service unit tests for citation graph EULAR DOI resolution and source
  availability for PMID `28386255`;
- topic map compact tests that fail if summary arrays are empty when graph
  content exists;
- related evidence tests for normalized scores and shared availability;
- review context batch tests for auto-fit defaults and enriched budget advice;
- MCP/catalog tests for no `prepare_mode` in generated next commands and
  updated workflow bundle guidance.

Final verification:

- focused literature graph suite;
- focused review retrieval suite;
- `make ci-local`;
- live Docker smoke checks for PMID `28386255` and DOI
  `10.1136/annrheumdis-2015-208690`.

## Rollout

Stack all changes onto PR #19 as task-sized commits. Rebuild/restart Docker
after implementation so the local MCP service reflects the final branch. Keep
the two existing untracked files untouched.

