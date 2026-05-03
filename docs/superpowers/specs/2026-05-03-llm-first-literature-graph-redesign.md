# LLM-First Literature Graph Redesign

## Status

Draft design for review on 2026-05-03.

## Problem

The first literature graph epic proved the core provider and graph plumbing, but
real LLM use exposed product-shape problems:

- `pubtator.build_topic_literature_map` can return very large payloads
  unsuitable for direct model context.
- Topic map ranking can promote off-target, null-PMID, abstract-collection, or
  weakly actionable records.
- `pubtator.get_publication_citation_graph` returns many DOI-only references,
  making them dead ends for PubTator passage retrieval unless the model performs
  extra identifier work.
- Citation graph compact use is noisy: `metadata_only` duplicates reference
  records, empty availability skeletons are repeated, and provider warnings can
  repeat per paper/request.
- Empty `cited_by` arrays do not distinguish "no results" from "provider did
  not run" or "provider failed".
- `pubtator.find_related_evidence_candidates` is useful, but its match reasons
  are too sparse for an LLM to explain why a paper was selected.

The primary consumer is an LLM doing biomedical literature triage before
passage-level grounding. These graph tools should optimize for compact,
actionable, audit-friendly candidate selection, not for dumping every available
graph record by default.

## Research Basis

The redesign follows current tool-use guidance:

- MCP client best practices warn that large tool definitions and large
  intermediate results waste context, increase latency, and degrade model
  performance. They recommend progressive discovery and avoiding large
  intermediate tool payloads in model context:
  <https://modelcontextprotocol.io/docs/develop/clients/client-best-practices>
- MCP tool guidance recommends clear tool names/descriptions, detailed schemas,
  focused operations, documented return structures, error handling, progress
  reporting, timeouts, and rate limiting:
  <https://modelcontextprotocol.info/docs/concepts/tools/>
- OpenAI function-calling guidance emphasizes clear schemas, invalid states made
  unrepresentable, offloading work from the model into code, keeping active
  tools small, and limiting tool/schema token overhead:
  <https://developers.openai.com/api/docs/guides/function-calling>
- MCP responses are structured JSON-RPC results, so these tools should provide
  predictable structured response modes instead of relying on the model to
  post-process huge graph JSON:
  <https://modelcontextprotocol.io/specification/2024-11-05/basic/index>

## Goals

- Make the graph tools directly usable by LLMs without `jq` post-processing.
- Keep default MCP responses small, stable, and task-oriented.
- Preserve full graph access for debugging, UI, and offline workflows.
- Improve candidate quality by preferring actionable PMIDs and demoting noisy
  publication types.
- Make provider behavior transparent per direction/source.
- Reduce context waste from duplicate arrays, empty objects, repeated warnings,
  and DOI-only dead ends.
- Keep all graph outputs research-use-only and explicit that graph relatedness
  is not claim support.

## Non-Goals

- Do not build embeddings or a vector reranker in this redesign.
- Do not infer biomedical claim support from graph edges.
- Do not scrape publisher full text or bypass paywalls.
- Do not require paid APIs.
- Do not remove existing REST/MCP tools.
- Do not make topic maps part of `lean` profile unless separately approved.

## Response Modes

All three graph tools get a shared response-mode concept:

- `compact`: default for MCP. Smallest response for LLM candidate selection.
  It includes seeds, summaries, ranked candidate metadata, provider status, and
  next commands, but no full topology.
- `nodes_edges`: graph topology only. It includes bounded node and edge records
  for visualization or graph reasoning without duplicating full paper payloads.
- `full`: today's complete response for compatibility, UI, offline analysis,
  or manual inspection.

REST defaults remain `full` for backward compatibility in existing API clients.
MCP defaults must be `compact`. REST callers can opt into `compact` or
`nodes_edges` explicitly.

### Payload Budgets

Budgets are enforced in code, not only documented:

- `compact` target: less than 12 KB JSON for normal MCP use.
- `nodes_edges` target: less than 40 KB JSON for normal use.
- `full`: bounded by existing `max_*` parameters, but not optimized for context.

Each response includes approximate truncation metadata:

- `response_mode`
- `response_size_class: "small" | "medium" | "large"`
- `truncated: bool`
- `omitted_counts`
- `next_commands`

`response_size_class` is derived from serialized JSON size after compact
serialization:

- `small`: 4 KB or less.
- `medium`: more than 4 KB and 12 KB or less.
- `large`: more than 12 KB.

When a compact response would exceed its budget, apply the same contract style
as `retrieve_review_context_batch`: keep the highest-ranked content, drop lower
priority sections in deterministic order, set `truncated=true`, populate
`omitted_counts`, and include `budget_advice` explaining exactly which
arguments to reduce or which `response_mode` to request next.

Compaction order for topic maps:

1. Keep `query`, `seed_pmids`, `recommended_next_pmids`, `provider_status`,
   `warnings`, and `next_commands`.
2. Keep highest-ranked `top_candidates` up to `max_candidates`.
3. Keep only PMID index arrays for accessibility, closed, and demoted lists.
4. Drop optional explanations from the lowest-ranked candidates.
5. Drop demoted entries above `max_demoted`.

Compaction order for citation graphs:

1. Keep `source`, `candidate_pmids`, provider status, warnings, and
   `next_commands`.
2. Keep PMID-bearing candidates before DOI-only candidates.
3. Drop unresolved DOI-only candidates above the per-mode cap.
4. Drop optional explanations from lowest-ranked candidates.

When records are omitted, the response should tell the LLM how to fetch more
detail, for example by calling the same tool with `response_mode="compact"` or
`response_mode="full"`, or by calling `pubtator.get_publication_passages`
for selected PMIDs.

## Shared Compact Serialization Rules

`compact` and `nodes_edges` modes must apply these rules:

- Omit empty `availability` blocks. Include availability only if at least one
  flag or field is informative.
- Omit empty `authors`, `publication_types`, `provenance`, `reasons`, and
  warnings arrays where schema compatibility permits. If omitted fields would
  break existing response models, use mode-specific response models.
- Do not duplicate the same paper in multiple arrays unless the second array
  adds distinct semantics. For citation graph, `metadata_only` must not repeat
  records already present in `references` or `cited_by` in compact/nodes_edges
  modes.
- Coalesce repeated provider warnings by `(provider, status, message)` and add a
  count when useful.
- Prefer `candidate_pmids` and compact paper summaries over full graph node
  payloads.
- Exclude `pmid: null` papers from `recommended_next_pmids`.
- Keep DOI-only records in explanatory/demoted sections, not in direct PubTator
  next-step lists.

## Shared Candidate Summary Model

Add a compact candidate shape for LLM triage:

```python
class LiteratureCandidateSummary(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    access: Literal["full_text", "open_access", "metadata_only", "unresolved"]
    access_flags: dict[Literal["has_pmc_full_text", "is_open_access", "has_pdf"], bool] = Field(default_factory=dict)
    score: float | None = None
    relevance_to_query: LiteratureQueryRelevance | None = None
    rank_reasons: list[str] = Field(default_factory=list)
    demotion_reasons: list[str] = Field(default_factory=list)
    source_tools: list[str] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
```

`access` is a derived summary with priority order:

1. `full_text` if PMC full text is available.
2. `open_access` if open access or an OA full-text URL is available.
3. `metadata_only` if metadata exists but no full text/OA signal exists.
4. `unresolved` if metadata is unresolved.

`access_flags` carries orthogonal booleans when more detail is needed.

`rank_reasons` and `demotion_reasons` are model-readable strings with stable
vocabulary, not free-form paragraphs.

`source_tools` uses this stable vocabulary:

- `topic_search`
- `citation_graph`
- `related_evidence`
- `doi_resolution`
- `metadata_backfill`

## Shared Publication Envelope

All graph tools use one compact publication envelope in `source`,
`references`, `cited_by`, `nodes`, `candidates`, and summaries. Mode-specific
models may omit empty fields, but they must not invent different names for the
same concept.

Canonical fields:

- `pmid`
- `doi`
- `pmcid`
- `title`
- `journal`
- `year`
- `publication_types`
- `access`
- `availability` only when informative
- `provenance` only when informative or in `full`

This gives LLMs and clients one parser instead of separate shapes for source
paper, graph node paper, reference paper, cited-by paper, and related candidate.

## Provider Status Model

Add provider/direction status structures:

```python
class LiteratureProviderStatus(BaseModel):
    provider: str
    operation: str
    status: Literal["not_requested", "skipped", "success", "empty", "partial", "failed", "disabled"]
    result_count: int = 0
    retryable: bool = False
    message: str | None = None
```

`result_count` is always an integer. For `disabled`, `skipped`,
`not_requested`, and `failed`, use `0` unless partial results were returned
before the failure.

Citation graph responses include:

- `references_status: list[LiteratureProviderStatus]`
- `cited_by_status: list[LiteratureProviderStatus]`
- `identifier_resolution_status: list[LiteratureProviderStatus]`
- `open_access_status: list[LiteratureProviderStatus]`

This directly addresses the ambiguity between "no citing papers" and "provider
unavailable".

## Topic Literature Map Redesign

### Tool Contract

`pubtator.build_topic_literature_map` adds:

- `response_mode: "compact" | "nodes_edges" | "full" = "compact"` for MCP.
- `max_candidates: int = 12` for compact candidate count.
- `include_demoted: bool = true`.
- `max_demoted: int = 3`.
- `bias_toward: list["guideline" | "cohort" | "genotype_phenotype" | "treatment" | "pediatric" | "population"] | None = None`.
- `max_graph_nodes: int = 30` and `max_graph_edges: int = 60` for
  `nodes_edges` mode.

### Compact Response

`compact` returns:

- `query`
- `seed_pmids`
- `summary`
- `top_candidates: list[LiteratureCandidateSummary]`
- `recommended_next_pmids`
- `accessible_full_text_pmids`
- `closed_central_pmids`
- `demoted_candidate_pmids`
- `demoted_reasons_by_pmid`
- `provider_status`
- `warnings`
- `next_commands`
- `omitted_counts`

`top_candidates` is the only compact response array carrying full candidate
envelopes. Accessibility, closed-source, and demoted fields are PMID indexes
into `top_candidates` where possible. If a demoted paper is not in
`top_candidates`, include only its PMID/DOI and reasons, capped by
`max_demoted`. This prevents the same paper from serializing three or four
times.

`summary` is a compact replacement for the existing `TopicLiteratureMapSummary`:
counts, top candidate PMIDs, bridge PMIDs, recent connected PMIDs, dominant
author names when relevant, and omitted counts. It does not embed full paper
records in compact mode.

Compact mode does not include full `nodes` or full `edges`.

### Nodes/Edges Response

`nodes_edges` returns topology only:

- bounded nodes with compact publication envelopes
- bounded edges with type, source, target, weight, and reasons
- no duplicate summary arrays
- no full metadata expansion unless needed to interpret topology

### Full Response

`full` preserves the current complete graph shape for compatibility and
manual inspection. It may still add provider status and ranking fields.

### Ranking Rules

Topic map candidate ranking is deterministic and explainable. The service
computes a transparent score, but exposes the score with reasons rather than
pretending it is evidence quality.

Positive signals:

- Has PMID.
- Has PMC full text or open access.
- Appears in multiple discovery paths: seed search, citation graph, related
  evidence.
- Has high PubMed neighbor score.
- Has shared MeSH/entity overlap with the query or seed set.
- Title/publication type indicates guideline, recommendation, consensus,
  Delphi, cohort, registry, genotype-phenotype, treatment, or pediatric focus
  when those terms appear in the query.
- Title/metadata overlaps central query terms after simple normalization.
- Recent enough for guideline/consensus queries, with no hard cutoff unless the
  user provides a year bound.

Demotion/exclusion signals:

- `pmid is None`: never include in `recommended_next_pmids`.
- DOI-only unresolved paper: keep in `demoted_candidate_pmids` with
  `demoted_reasons_by_pmid`, or in `full`, not direct PubTator next steps.
- Publication type or title suggests conference abstracts, meeting abstracts,
  supplement collections, annual highlights, veterinary-only papers, unrelated
  syndromes, or generic issue summaries.
- Very weak query overlap.
- Provider status indicates unresolved metadata only.

The demotion vocabulary must be stable:

- `missing_pmid`
- `doi_only_unresolved`
- `conference_abstract_collection`
- `supplement_collection`
- `annual_review_collection`
- `off_topic_title`
- `low_query_overlap`
- `metadata_only`

Demotion reasons are versioned by `ranking_version`. Clients must tolerate
unknown future demotion reasons. New values are additive only within a ranking
major version.

Every compact candidate includes `relevance_to_query` as a bounded structure:

```python
class LiteratureQueryRelevance(BaseModel):
    score: float
    matched_terms: list[str] = Field(default_factory=list)
    matched_mesh: list[str] = Field(default_factory=list)
    matched_intents: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
```

The score is for ranking only; it is not evidence quality.

### Query-Aware Ranking

The query is parsed into lightweight intent flags:

- `guideline_intent`: guideline, recommendation, consensus, Delphi.
- `pediatric_intent`: child, pediatric, paediatric, children.
- `population_intent`: Turkey, Turkish, Mediterranean, ancestry terms.
- `variant_intent`: variant, VUS, genotype, phenotype, penetrance.
- `treatment_intent`: colchicine, treatment, resistance, management.

These flags only affect ranking and reasons. They do not create biomedical
claims.

Intent matching is deterministic: lowercase and Unicode-normalize the query,
then use case-insensitive substring matching over normalized text. Plurals such
as `guidelines` match `guideline`; British/American variants such as
`paediatric` and `pediatric` are both explicit triggers.

Compact responses include `ranking_version`, starting with
`topic_map_ranker_v1`.

## Citation Graph Redesign

### Tool Contract

`pubtator.get_publication_citation_graph` adds:

- `response_mode: "compact" | "nodes_edges" | "full" = "compact"` for MCP.
- `resolve_reference_pmids: bool = true`.
- `max_reference_resolution: int = 20`.
- `include_provider_status: bool = true`.

### Compact Response

`compact` returns:

- `source`
- `reference_candidates: list[LiteratureCandidateSummary]`
- `cited_by_candidates: list[LiteratureCandidateSummary]`
- `candidate_pmids`
- `references_status`
- `cited_by_status`
- `identifier_resolution_status`
- `open_access_status`
- `warnings`
- `next_commands`
- `omitted_counts`

It does not return `metadata_only` if the same paper is already in references or
cited-by candidates.

### Nodes/Edges Response

`nodes_edges` returns source, bounded reference/cited-by nodes, and graph edges
without repeated metadata arrays. This is for graph topology inspection when the
LLM or a UI needs structure rather than candidate triage.

### DOI-to-PMID Resolution

For DOI-bearing references and cited-by records:

1. Batch DOI conversion through `NcbiDiscoveryClient.convert_article_ids` /
   `DiscoveryService.convert_article_ids`, up to `max_reference_resolution`.
2. If resolved, merge PMID into the paper and add
   `rank_reasons=["resolved_pmid_from_doi"]`.
3. If unresolved, retain DOI but add `demotion_reasons=["doi_only_unresolved"]`.
4. Do not exceed the max resolution budget.
5. Emit `identifier_resolution_status` with counts for resolved, unresolved,
   skipped, and failed.

This addresses the dead-end problem where Crossref/OpenAlex references have DOI
but no PMID.

Initial implementation uses NCBI ID conversion only for bounded DOI-to-PMID
resolution. Europe PMC/OpenAlex fallback can be added later if live testing
shows materially better resolution without excessive latency.

Operational requirements:

- Batch DOI conversions; do not issue one HTTP call per DOI.
- Cache DOI-to-PMID results because they are stable enough for the graph use
  case. Cache positive and negative results separately with bounded TTL.
- Respect provider rate limits and retry-after behavior through the existing
  NCBI discovery/retry path.
- Run DOI resolution after provider fetches, but keep a wall-clock budget so
  citation graph calls do not become unbounded. Initial target: p95 added
  latency under 2 seconds for `max_reference_resolution=20` with a warm cache.
- Emit `identifier_resolution_status` with resolved, unresolved, skipped,
  cached, failed, and timeout counts.

### Provider Status

Per direction, status must explain:

- Provider was not requested because direction excluded it.
- Provider was skipped because required source identifier was missing.
- Provider ran and found results.
- Provider ran successfully but found no results.
- Provider failed.
- Provider disabled, e.g. Unpaywall email missing.

Examples:

- Europe PMC cited-by with source PMID and zero records:
  `status="empty", result_count=0`.
- Europe PMC cited-by with DOI-only source and no PMID:
  `status="skipped", message="PMID required"`.
- Unpaywall disabled:
  one coalesced `disabled` status, not a repeated warning for every DOI.

### Compact Redundancy Rules

In `compact` and `nodes_edges` modes:

- Do not include `metadata_only` duplicates.
- Do not include empty availability.
- Coalesce identical Unpaywall disabled warnings into one provider status.
- Limit DOI-only unresolved records unless the user asks for `full`.
- Sort actionable PMID-bearing records before DOI-only records.

### Citation Graph Match Reasons

Citation graph candidate summaries include `rank_reasons` and
`demotion_reasons` so the LLM can choose a tight corpus without always making a
second related-evidence call. Stable reasons include:

- `resolved_pmid_from_doi`
- `has_pmid`
- `has_open_access`
- `full_text_available`
- `source_reference`
- `source_cited_by`
- `shared_mesh`
- `title_query_overlap`
- `guideline_or_consensus_match`
- `doi_only_unresolved`

Citation graph candidates also include `relevance_to_query` when a query or
source title terms are available. If no query-like signal exists, omit
`relevance_to_query` rather than emitting an empty object.

## Related Evidence Redesign

`pubtator.find_related_evidence_candidates` remains the most directly useful
tool and should keep its current default behavior, but add:

- `response_mode: "compact" | "nodes_edges" | "full" = "compact"`.
- richer `match_reasons`.
- optional source metadata/entity comparison when cheap.

Stable match reasons:

- `pubmed_neighbor_score`
- `citation_neighbor`
- `full_text_available`
- `open_access_available`
- `shared_mesh`
- `shared_publication_type`
- `guideline_or_consensus_match`
- `pediatric_match`
- `population_match`
- `variant_or_genotype_match`
- `treatment_match`
- `year_window_match`

Related evidence should remain PMID-first. DOI-only records are not useful for
review indexing unless resolved.

## Backward Compatibility

- Existing response models remain available through `response_mode="full"`
  or existing REST defaults.
- MCP defaults change to `compact`.
- Tool names do not change.
- Existing arguments remain valid.
- Legacy callers that ignore additive provider status/ranking/cache fields will
  continue to parse existing `full` responses.
- New response models should be additive. If exact current model compatibility
  prevents omitting empty fields, introduce mode-specific response models rather
  than weakening compactness.

Slice 1 must not change the `response_mode="full"` shape beyond additive fields.
Existing REST clients should see the same references/cited_by/nodes/edges arrays
unless they opt into compact modes.

MCP default migration is explicit: during the first implementation release,
missing `response_mode` on MCP calls emits a deprecation warning in `_meta` while
returning current `full` behavior for one release. The following release flips
the MCP default to `compact`. If we decide not to stage the release, the first
tool description sentence must clearly say that `compact` is the default and
`full` is required for legacy nodes/edges arrays.

## Error Handling

- Provider failures are non-fatal unless no usable source identifier exists.
- Provider warnings are coalesced.
- Provider status is structured and directional.
- Empty results are not treated as failures.
- Tool outputs must include next-step recovery or expansion commands where
  useful.
- Compact graph responses include cache metadata where the underlying service
  has a cacheable snapshot:
  - `cache_key`
  - `snapshot_date`
  - `source_versions`
  - `ranking_version`

Topic maps and DOI resolution should use cache keys based on normalized query,
seed PMIDs, response-affecting options, and ranking version.

## Observability

Graph tool telemetry must log:

- `response_mode`
- `response_size_class`
- `ranking_version`
- `intent_flags`
- `n_candidates_total`
- `n_candidates_returned`
- `n_demoted`
- `n_resolved_doi`
- `n_unresolved_doi`
- provider status counts

Ranking changes should be measurable against fixtures and live telemetry.

## Testing Strategy

Unit tests:

- Topic map compact omits full nodes/edges and stays under a small serialized
  size in fixture tests.
- Topic map excludes null-PMID and DOI-only unresolved records from
  `recommended_next_pmids`.
- Topic map demotes conference abstract collections and off-topic titles.
- Topic map ranks guideline/consensus records above generic reviews for
  guideline-intent queries.
- Topic map golden fixtures:
  - PMID `33778981` must demote with `off_topic_title` and/or
    `conference_abstract_collection` for an FMF clinical genetics query.
  - PMID `40616106` must demote with `low_query_overlap` for an FMF query.
  - PMID `28386255` must rank in the top 3 for guideline-intent FMF queries.
  - PMID `36680425` must rank in the top 5 for colchicine-resistance plus
    pediatric-intent queries.
- Citation graph compact deduplicates `metadata_only` from references.
- Citation graph omits empty availability in compact/nodes_edges modes.
- Citation graph returns provider status for success, empty, skipped, failed,
  and disabled paths.
- Citation graph resolves DOI references to PMIDs within a bounded budget.
- Citation graph coalesces repeated Unpaywall disabled warnings.
- Citation graph candidate summaries expose `relevance_to_query` and
  `rank_reasons`.
- Citation graph DOI resolution batches DOI conversions and uses cached
  positive/negative results.
- Related evidence emits enriched match reasons for shared MeSH, publication
  type, full text, and intent matches.

Route/MCP tests:

- Tool schemas expose `response_mode` enums.
- MCP defaults are compact.
- Tool descriptions document `response_size_class` and warn that `full` can be
  large.
- REST defaults are explicitly tested.
- Output schema is flat and avoids nested `request`.

Integration-style tests with fake providers:

- A Crossref-heavy citation graph with mostly DOI-only references yields
  resolved PMIDs where possible and demotes unresolved DOI-only records.
- A topic query with noisy abstract collections still recommends actionable
  PMID-bearing guideline/cohort candidates.

Verification:

- Focused graph tests.
- MCP catalog regeneration.
- `make ci-local`.

## Rollout

Implement in three slices:

1. Shared response modes, compact serializers, provider status, publication
   envelope, and citation graph compact response.
2. Topic map compact response and ranking/demotion redesign.
3. Related evidence reason enrichment and docs/prompt updates.

Each slice should be independently committed and verified.

## Design Decisions

- MCP defaults to `compact`; REST defaults to `full` for compatibility.
- `compact` omits graph topology by default; `nodes_edges` includes bounded
  topology.
- DOI-to-PMID resolution starts with NCBI ID conversion only and exposes
  structured unresolved counts/status so fallback value can be measured later.
- `access` is a priority-ordered summary; orthogonal access details live in
  `access_flags`.
- Candidate subtype arrays in compact responses are PMID indexes, not repeated
  envelopes.
