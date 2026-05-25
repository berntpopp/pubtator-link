# MCP LLM Consumer Over 9 Next Wave Design

## Goal

Raise the PubTator-Link MCP LLM-consumer experience from the current high-7/8
range to a credible 9+ by finishing parameter convergence, validation-error
discoverability, metadata-budget controls, and the remaining per-tool polish
identified by black-box LLM testing.

## Current Context

The branch already fixed the highest-severity hard failures from the earlier
report: mixed article ID conversion, source preflight degradation, text
annotation submission, entity-relation bounding, audit export compact default,
ClinVar germline classification parsing, topic-map aliases, PMC annotation
coverage reasons, and search/passages/ground-question ergonomic aliases.

The remaining friction is not architectural. It is mostly consistency:

- Search-like tools still use different argument names for the same mental
  operation: `query`, `text`, `question`, and `topic`.
- PMID-taking tools are split between scalar `pmid` and list-only `pmids`,
  which makes list-of-one calls unnecessarily easy to get wrong.
- Validation errors are not uniformly LLM-teaching envelopes. One tool exposes
  enum values well; most failures still require schema guessing.
- `include_meta=false` is implemented for literature search only, while other
  search/retrieval/staging tools keep paying the metadata tax on repeated calls.
- Several tools below the 9/10 threshold can be lifted with bounded metadata
  enrichment, honest freshness/status notes, and alias support without renaming
  public tools.

## Product Direction

Keep existing public tool names and canonical parameters stable. Add aliases
and response controls as compatibility features, then document `query` and
`pmid` as the preferred LLM-facing defaults. The server should accept common
LLM guesses, normalize them into canonical service requests, and return enough
structured feedback that the next retry can be correct without external schema
inspection.

## Architecture

The design has four layers.

1. Argument normalization:
   Add a small shared MCP argument-normalization layer for aliases before tool
   bodies instantiate service requests. Use `query` as the canonical search
   input and accept legacy aliases (`text`, `question`, `topic`) where tools
   currently expose them. Accept scalar `pmid` beside list `pmids` for PMID-list
   tools and merge to a deduplicated list.

2. Validation error UX:
   Catch FastMCP/Pydantic validation failures as close to the MCP tool boundary
   as possible and enrich the existing error envelope with `valid_params`,
   `missing_params`, `unexpected_params`, and `valid_values_for` for enum or
   literal failures. Keep `success=false`, `error_code="validation_failed"`,
   `_meta.next_commands`, and research-use safety flags consistent with
   `pubtator_link/mcp/errors.py`.

3. Payload budgeting:
   Promote `include_meta` from a search-only option into a repeated-call
   convention for search/retrieval/staging tools that emit workflow metadata.
   Default remains `true` for compatibility. When false, strip `_meta` and
   per-result diagnostic ranking fields that are not needed for normal answer
   construction.

4. Per-tool polish:
   Lift the remaining sub-9 tools with narrowly scoped improvements:
   broaden guideline search by reranking instead of hard-filtering, enrich
   citation and related-article records with existing metadata services, add
   corpus suggestion relevance reasons and a threshold, add passage-budget
   advice to context estimates, add freshness notes to empty citation graphs,
   split long natural-language ground-question searches automatically, allow
   global/session-id-only research session orientation, add a freeform review
   note event type, and add a short-job wait path for text annotation results.

## Non-Goals

- Do not rename or remove public MCP tools.
- Do not turn research-use tools into clinical decision support.
- Do not expose destructive cache/admin behavior in hosted profiles.
- Do not change `.planning/` files.
- Do not expand raw BioC payload defaults; compact/bounded behavior remains the
  default for LLM-facing flows.
- Do not grow grandfathered files past their `.loc-allowlist` ceiling. Split
  helper modules instead of adding bulk to `service_adapters.py`,
  `ncbi_discovery.py`, or `related_evidence.py`.

## Success Criteria

- A fresh LLM session can call every search/lookup/retrieve tool with `query=`
  and every PMID-list tool with `pmid=` without schema errors.
- Every validation error response includes `valid_params`; enum/literal errors
  also include `valid_values_for`.
- Repeated-call flows using `include_meta=false` reduce payload size by at least
  20% on a representative 10-call local smoke script while preserving required
  answer fields.
- The following tools have focused regression tests and move to the target
  shape described by the punch list: `pubtator_search_guidelines`,
  `pubtator_lookup_citation`, `pubtator_suggest_corpus`,
  `pubtator_estimate_publication_context`,
  `pubtator_get_publication_citation_graph`,
  `pubtator_find_related_articles`,
  `pubtator_find_related_evidence_candidates`,
  `pubtator_ground_question`, `pubtator_review_quickstart`,
  `pubtator_list_research_sessions`,
  `pubtator_get_research_session_status`,
  `pubtator_record_review_context`,
  `pubtator_get_review_audit_trail`,
  `pubtator_submit_text_annotation`, and
  `pubtator_get_text_annotation_results`.
- `make ci-local` passes.
- Runtime-facing docs and generated MCP catalog describe the aliases and
  compact controls.

## Self-Review

- No placeholders: this design names the exact behavior and tool surfaces.
- Scope is one cohesive MCP ergonomics wave split into implementation tasks.
- Requirements preserve backward compatibility by adding aliases and optional
  knobs rather than changing existing defaults.
- The high-risk line-count files are explicitly called out for helper splits.
