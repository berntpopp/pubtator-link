# MCP Graph Tools Quality Improvement Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the new graph-oriented MCP tools to >9/10 LLM-client quality by improving topic-map relevance, compact-mode signal retention, retryability, pagination-like continuation, and diagnostics without weakening existing grounded review workflows.

**Architecture:** Keep the existing `pubtator.*` tool family and flat schemas. Add shared graph ranking/continuation helpers where they reduce duplication, but keep production behavior scoped to `citation_graph`, `related_evidence`, and `topic_literature_map` service boundaries. Preserve compact defaults while ensuring compact never hides high-value signals without explicit stubs, counts, and next commands.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, FastMCP/MCP structured content, pytest, Ruff, mypy.

---

## Source Guidance

- MCP tool errors should use tool execution errors with actionable feedback rather than opaque protocol failures when the model can self-correct.
- MCP supports opaque cursor pagination for list operations; for tool-level long tails, mirror the principle with opaque continuation tokens in tool payloads, not client-parsed offsets.
- Tool results that return structured content should also include serialized text content for compatibility.
- Modern MCP client guidance favors progressive discovery when tool catalogs are large; server-side workflow helpers and capability summaries should reduce the need to load all ~50 tools.

References:
- https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- https://modelcontextprotocol.io/specification/draft/server/utilities/pagination
- https://modelcontextprotocol.io/docs/develop/clients/client-best-practices

---

## File Structure

- Modify: `pubtator_link/models/literature_graph.py`
  - Add compact-friendly fields:
    - `cited_by_top_pmids: list[str]`
    - `reference_top_pmids: list[str]`
    - `continuation: LiteratureGraphContinuation | None`
    - `warning_codes: list[ProviderWarningCode]`
    - optional rationale fields for topic-map summary papers.
  - Add `partial_ok` and stage-budget request fields for topic maps.

- Modify: `pubtator_link/services/literature_graph_compact.py`
  - Add shared query-relevance scoring helpers.
  - Add compact candidate budgeting that preserves per-lane minimums before dropping tails.
  - Add continuation-token creation and validation helpers.

- Modify: `pubtator_link/services/citation_graph.py`
  - Add optional query-relative scoring.
  - Preserve at least a small cited-by/reference stub set in compact mode.
  - Emit `cited_by_top_pmids` and `reference_top_pmids`.
  - Add continuation metadata for omitted candidate tails.

- Modify: `pubtator_link/services/related_evidence.py`
  - Add warning-code mapping.
  - Add continuation support for omitted candidates.
  - Ensure compact author summaries are consistently populated from available metadata.

- Modify: `pubtator_link/services/topic_literature_map.py`
  - Replace blind seed acceptance with search-result metadata filtering and seed scoring.
  - Penalize conference/abstract collection seeds before fan-out.
  - Rank summary centrality by topic relevance plus graph degree, not graph degree alone.
  - Move demoted candidates out of `top_candidates`.
  - Fill accessible summary candidates consistently.
  - Replace opaque `recommended_next_pmids` with titled recommendation summaries plus rationale.
  - Add per-stage timing, stage budgets, and `partial_ok`.

- Modify: `pubtator_link/mcp/catalog.py`
  - Tighten descriptions for graph tools with explicit “when to choose topic_map vs citation_graph vs related_evidence.”
  - Add examples that use compact first, then continuation/detail calls.

- Modify: `docs/mcp-tool-catalog.md`
  - Regenerate after schema/catalog changes.

- Test:
  - `tests/unit/test_citation_graph_service.py`
  - `tests/unit/test_related_evidence_service.py`
  - `tests/unit/test_topic_literature_map_service.py`
  - `tests/unit/test_literature_graph_compact.py`
  - `tests/unit/mcp/test_mcp_facade.py`
  - `tests/unit/mcp/test_mcp_service_adapters.py`

---

## Task 1: Shared Warning Codes And Stage Telemetry

**Outcome:** Agents can branch deterministically on failures and tune retries.

- [ ] **Step 1: Add failing tests**
  - In `tests/unit/test_related_evidence_service.py`, assert a coverage warning produces:
    - `warning_codes=["coverage_lookup_failed"]`
    - `provider_status[].retryable == true`
    - `_meta.next_commands` includes a lower-cost retry or fallback retrieval command.
  - In `tests/unit/test_topic_literature_map_service.py`, assert each stage status can include `elapsed_ms` and `budget_ms`.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/unit/test_related_evidence_service.py::test_related_evidence_structured_warning_codes -q`
  - Run: `uv run pytest tests/unit/test_topic_literature_map_service.py::test_topic_map_reports_stage_timing -q`
  - Expected: fail because fields do not exist.

- [ ] **Step 3: Implement**
  - Add a bounded warning-code enum instead of free-text-only warnings.
  - Keep current human-readable `warnings[]`.
  - Add timing fields only to provider/stage status objects, not as top-level clutter.

- [ ] **Step 4: Verify**
  - Run the two focused tests.
  - Run: `make lint`
  - Commit: `feat: add graph warning codes and stage telemetry`

---

## Task 2: Citation Graph Compact Signal Retention

**Outcome:** Compact mode remains small but no longer silently hides the cited-by lane.

- [ ] **Step 1: Add failing tests**
  - In `tests/unit/test_citation_graph_service.py`, create a graph with many references and cited-by records under compact budget pressure.
  - Assert compact response keeps at least 3 `cited_by_candidates` stubs when cited-by records exist.
  - Assert `cited_by_top_pmids` and `reference_top_pmids` are populated even when full candidate arrays are truncated.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/unit/test_citation_graph_service.py::test_citation_graph_compact_preserves_cited_by_stubs -q`

- [ ] **Step 3: Implement**
  - Budget by lanes:
    - preserve source
    - preserve provider status
    - preserve top PMID arrays
    - preserve 3 cited-by stubs and 3 reference stubs
    - drop long tails
  - Add `budget_advice.retry_arguments` pointing to `response_mode="full"` or a continuation call.

- [ ] **Step 4: Verify**
  - Run focused citation graph tests.
  - Commit: `feat: preserve citation graph compact lane stubs`

---

## Task 3: Query-Relevance Scoring For Citation Graph

**Outcome:** Citation graph becomes a ranker, not just a generator.

- [ ] **Step 1: Add failing tests**
  - Add optional `query` to `PublicationCitationGraphRequest`.
  - Assert `reference_candidates[].score` and `relevance_to_query` are not null when `query` is passed.
  - Assert on-topic title/abstract/title-token overlap ranks above methodology-only records when other signals tie.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/unit/test_citation_graph_service.py::test_citation_graph_scores_candidates_against_query -q`

- [ ] **Step 3: Implement**
  - Score candidates using:
    - query term/title overlap
    - recency
    - access/full-text availability
    - guideline/consensus publication type/title signals
    - citation lane signal (`cited_by` slightly preferred for updates)
  - Keep score approximate and explainable via `rank_reasons`.

- [ ] **Step 4: Verify**
  - Run focused citation graph tests and MCP schema tests.
  - Commit: `feat: score citation graph candidates against query`

---

## Task 4: Related Evidence Continuation And Author Summaries

**Outcome:** Omitted long tails become recoverable without re-querying from scratch.

- [ ] **Step 1: Add failing tests**
  - In `tests/unit/test_related_evidence_service.py`, assert `omitted_counts.candidates > 0` yields `_meta.next_commands` with an opaque continuation token.
  - Assert candidates with authors in metadata produce `author_summary` in compact mode.

- [ ] **Step 2: Verify red**
  - Run focused tests.

- [ ] **Step 3: Implement**
  - Add `cursor` or `continuation_token` to related evidence request.
  - Token should be opaque and include request signature plus start index, signed or stable-hashed enough to detect mismatch.
  - Populate author summaries during candidate summary creation.

- [ ] **Step 4: Verify**
  - Run related evidence tests.
  - Commit: `feat: add related evidence continuation`

---

## Task 5: Topic Map Seed Quality Gate

**Outcome:** Topic map starts from genuinely on-topic seeds.

- [ ] **Step 1: Add failing tests**
  - Build fake search results containing:
    - a high PubTator-score conference abstract collection
    - a guideline/recommendation article
    - a broad off-topic review
  - Metadata marks publication types and titles.
  - Assert seeds exclude or rank down conference/selected-abstract collections when enough alternatives exist.
  - Assert `bias_toward=["guideline"]` promotes guideline seeds before fan-out.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/unit/test_topic_literature_map_service.py::test_topic_map_filters_low_quality_search_seeds -q`

- [ ] **Step 3: Implement**
  - Search still uses PubTator score desc.
  - Fetch metadata for more than requested seeds, e.g. `max_seed_papers * 3` bounded to 50.
  - Score seeds before fan-out:
    - PubTator rank/score
    - query-title overlap
    - guideline/pediatric/treatment/genotype bias matches
    - publication type penalties for conference proceedings, selected abstracts, comments, editorials
    - abstract collection penalty
  - Choose final seeds only after metadata scoring.

- [ ] **Step 4: Verify**
  - Run focused topic-map tests.
  - Commit: `feat: improve topic map seed selection`

---

## Task 6: Topic Map Relevance-Aware Centrality

**Outcome:** `central_papers` stops being dominated by high-degree off-topic papers.

- [ ] **Step 1: Add failing tests**
  - Create a fake graph where an off-topic seed has high degree and an on-topic guideline has lower degree.
  - Assert the guideline ranks first for a guideline-biased query.
  - Assert each central paper has `centrality_reasons`.

- [ ] **Step 2: Verify red**
  - Run focused topic-map tests.

- [ ] **Step 3: Implement**
  - Centrality score = topic relevance + seed quality + graph degree + recency + accessibility.
  - Hard demote `low_query_overlap` from summary centrality unless no alternatives remain.
  - Add `centrality_reasons` or a compact rationale object.

- [ ] **Step 4: Verify**
  - Run topic-map tests.
  - Commit: `feat: rank topic map centrality by relevance`

---

## Task 7: Topic Map Output Consistency

**Outcome:** The compact response is self-explanatory and not internally contradictory.

- [ ] **Step 1: Add failing tests**
  - Assert `summary.accessible_full_text_candidates` is non-empty when `accessible_full_text_pmids` is non-empty and paper metadata is available.
  - Assert `recommended_next_pmids` has parallel `recommended_next_candidates` with title, journal, year, and rationale.
  - Assert demoted items are absent from `top_candidates` and appear only in demoted blocks when requested.
  - Assert compact graph omission includes `graph_inspection_hint`.

- [ ] **Step 2: Verify red**
  - Run focused topic-map tests.

- [ ] **Step 3: Implement**
  - Add titled recommendation summaries.
  - Canonicalize accessible candidate location or keep both but ensure summary mirrors top-level IDs.
  - Filter demoted candidates out of top candidates by default.
  - Add graph inspection hint when nodes/edges are omitted.

- [ ] **Step 4: Verify**
  - Run topic-map tests and catalog generation.
  - Commit: `feat: make topic map compact output consistent`

---

## Task 8: Topic Map Timeout Policy

**Outcome:** Agents can choose between partial useful results and strict failure.

- [ ] **Step 1: Add failing tests**
  - Assert `partial_ok=false` returns `isError=true`/route error semantics when a stage times out before required stages complete.
  - Assert `stage_budgets` can allocate more budget to citation graph or related evidence.
  - Assert timeout recovery commands preserve all user intent and adjust only the failed stage.

- [ ] **Step 2: Verify red**
  - Run focused topic-map and MCP adapter tests.

- [ ] **Step 3: Implement**
  - Add `partial_ok: bool = true`.
  - Add bounded `stage_timeout_ms` or structured `stage_budgets` with defaults:
    - seed search: 15%
    - seed metadata: 20%
    - citation graph: 35%
    - related evidence: 20%
    - metadata backfill: 10%
  - Continue to emit partial responses by default.
  - Strict mode should fail with actionable retry args.

- [ ] **Step 4: Verify**
  - Run topic-map tests and MCP error tests.
  - Commit: `feat: add topic map partial mode and stage budgets`

---

## Task 9: Discovery Simplification

**Outcome:** The tool catalog feels smaller without removing power-user tools.

- [ ] **Step 1: Add tests**
  - Assert `workflow_help` recommends:
    - `search_literature` for unknown topics
    - `find_related_evidence_candidates` when a seed PMID exists
    - `get_publication_citation_graph` for citation expansion
    - `build_topic_literature_map` only for broad map requests or explicit graph summaries.

- [ ] **Step 2: Implement**
  - Add a graph-tool decision table to capabilities/workflow help.
  - Tighten `Do not use for` boundaries in tool catalog supplements.
  - Keep progressive discovery compatibility: do not require loading all graph tools to choose the first step.

- [ ] **Step 3: Verify**
  - Run workflow help and MCP catalog tests.
  - Commit: `docs: clarify graph tool selection`

---

## Task 10: End-To-End Quality Gates

**Outcome:** The score improvements are backed by reproducible checks.

- [ ] **Step 1: Add scenario fixtures**
  - Create deterministic unit/integration fixtures for:
    - FMF guideline query
    - EULAR/PReS seed PMID `40234174`
    - high-degree off-topic neighbor
    - compact budget truncation with cited-by lane present.

- [ ] **Step 2: Run focused checks**
  - `uv run pytest tests/unit/test_citation_graph_service.py tests/unit/test_related_evidence_service.py tests/unit/test_topic_literature_map_service.py tests/unit/test_literature_graph_compact.py -q`

- [ ] **Step 3: Run full checks**
  - `make ci-local`

- [ ] **Step 4: Commit**
  - Commit: `test: add graph tool quality scenarios`

---

## Success Criteria

- Citation graph compact mode always preserves visible cited-by signal when cited-by data exists.
- Citation graph can rank candidates against an optional query.
- Related evidence long tails have an opaque continuation path.
- Warning handling includes stable machine-readable codes.
- Topic map no longer admits conference abstract collections or broad off-topic reviews as central seeds when better search hits exist.
- Topic map central papers are relevance-aware and explainable.
- Topic map compact response has no contradictory empty/non-empty paths for the same concept.
- All three graph tools expose cache/snapshot/source/version metadata, provider status, response size, and next commands.
- `make ci-local` passes.
