# PubTator-Link MCP Capability, Speed, Usability, and Scientific Rigor Review

Date: 2026-05-01

## Executive Summary

PubTator-Link is already a strong LLM-facing biomedical grounding MCP. The current
`search -> index -> inspect -> retrieve` workflow, compact passage packing, stable
citation keys, source coverage labels, and retrieval diagnostics are the right
foundation for audit-grade literature synthesis.

The next improvement should not be another broad tool-surface rewrite. The highest
leverage work is to make evidence preparation more transparent, faster, and more
recoverable:

1. Add preflight source coverage and lawful full-text fallback before or during
   indexing.
2. Add bounded async parallelism where calls are currently sequential.
3. Add exponential backoff, retry, and `Retry-After` handling for upstream APIs.
4. Add passage-level addressability so LLMs can cheaply expand or re-fetch exact
   evidence.
5. Add typed MCP output models so clients see real schemas, not generic objects.
6. Add review-audit metadata aligned with PRISMA/GRADE-style evidence practice.

This review is a design memo, not an implementation plan. It should be converted
into scoped specs and implementation plans before code changes.

## Current Strengths

### LLM-Oriented Workflow

The MCP server instructions and capability resource teach a practical workflow:
literature search, review evidence indexing, index inspection, and compact review
retrieval. The current public tools use flat top-level arguments rather than
`request` envelopes, which is materially easier for tool-calling models.

Relevant code:

- `pubtator_link/mcp/facade.py`
- `pubtator_link/mcp/resources.py`
- `pubtator_link/mcp/tools/review.py`
- `pubtator_link/mcp/service_adapters.py`

### Context Discipline

`retrieve_review_context_batch` already supports:

- `response_mode`: `compact`, `merged_only`, `full`, `diagnostics`
- `max_chars`
- `max_response_chars`
- `max_chars_per_passage`
- dropped passage reasons
- per-query summaries
- stable citation keys
- source-aware budget strategies

This is a good fit for LLM consumers because the server constrains context before
the model receives it.

Relevant code:

- `pubtator_link/models/review_rerag.py`
- `pubtator_link/services/review_context/batch_budgeting.py`
- `pubtator_link/services/review_context/packing.py`
- `pubtator_link/services/review_context/diagnostics.py`

### Citation Traceability

Passages have deterministic IDs such as `PMID:{pmid}:{section}:{index}` and
stable citation keys derived from passage IDs. This is one of the most important
features for reproducible synthesis because it separates request-local labels
from durable identifiers.

Relevant code:

- `stable_citation_key_for_passage()` in `pubtator_link/models/review_rerag.py`
- `passage_id_for_pmid()` in `pubtator_link/models/review_rerag.py`

## Main Gaps

### 1. Coverage Is Discovered Too Late

Today `FullTextPreparationService.prepare_pmid()` tries PubTator full BioC first,
then falls back to PubTator abstract export if no passages are parsed. After that,
coverage is inferred from sections and attempt statuses during index inspection.

This means an LLM often learns that a load-bearing PMID is `abstract_only` only
after it has already paid the indexing round trip.

Current behavior:

- Full PubTator export attempted with `full=True`.
- Abstract PubTator export attempted only if full export yields no passages.
- No PMC ID conversion preflight.
- No BioC-PMC fallback by PMID/PMCID.
- No precise `coverage_reason`.
- No `pmc_fallback_available` or `license/access` hint.

Recommended behavior:

- Add a coverage preflight service for PMIDs before indexing.
- Add `coverage_reason` to source summaries.
- Add fallback attempt summaries even when the final status is success.
- Record why full text was unavailable: no PMCID, not in PMC OA/manuscript set,
  PubTator full export empty, upstream 404, license/reuse unavailable, timeout,
  blocked source, parser unsupported, or unknown.
- Surface `expected_coverage` on search results where cheap metadata is already
  present, and on index enqueue responses where a preflight was run.

### 2. Full-Text Fallback Should Prefer Approved APIs

The reviews suggested publisher landing pages as a fallback. That should be a
late, explicit curated-source path, not the default automatic path.

Preferred lawful resolver cascade:

1. PubTator full BioC export by PMID.
2. PMC ID Converter for PMID -> PMCID/DOI/MID metadata.
3. NCBI BioC-PMC by PMID or PMCID when the article is in the supported PMC OA or
   manuscript collections.
4. PMC OAI-PMH JATS XML for records whose license allows reuse.
5. Europe PMC full-text XML for open-access records, if enabled and rate-limited.
6. PubTator abstract export.
7. PubMed/PMC metadata-only record with explicit `title_only` or `abstract_only`
   coverage.
8. Curated user-provided PDF/HTML URL, only when explicitly supplied.

This keeps hosted MCP behavior research-use scoped and avoids default scraping of
publisher pages.

### 3. Retry And Backoff Are Missing

The current `PubTator3Client` has a token-bucket rate limiter, but `_make_request`
does not currently retry transient failures with exponential backoff. It raises on
HTTP status errors and request errors.

Recommended behavior:

- Add retry policy for idempotent upstream calls:
  - `GET /search`
  - `GET /publications/export/...`
  - `GET /publications/pmc_export/...`
  - `GET /entity/autocomplete`
  - `GET /relations`
  - PMC ID Converter
  - BioC-PMC
  - PMC OAI-PMH
  - Europe PMC metadata/full-text endpoints
- Retry status codes: `408`, `429`, `500`, `502`, `503`, `504`.
- Respect `Retry-After` when present.
- Use exponential backoff with full jitter:
  - base: 250-500 ms
  - factor: 2
  - cap: 8-20 s depending on endpoint
  - attempts: 3 by default, 5 for preparation jobs if within document timeout
- Do not blindly retry non-idempotent text annotation submit if the request may
  have been accepted. If needed, retry only connection failures before a response
  is received and mark uncertainty in the result.
- Return retry diagnostics in source attempts:
  - `attempt_count`
  - `last_status_code`
  - `retry_after_ms`
  - `backoff_ms`
  - `terminal_reason`

### 4. Parallelism Can Improve Latency Without Changing Semantics

Several operations are naturally parallel but currently have sequential surfaces
or per-call client creation patterns.

Recommended parallelism:

- In `retrieve_review_context_batch`, run per-query retrieval concurrently with a
  bounded semaphore, then preserve deterministic merge ordering by query index.
- In evidence preparation, run independent source resolver attempts with careful
  ordering:
  - race cheap metadata/preflight calls where safe,
  - keep final source priority deterministic,
  - bound concurrency globally and per upstream host.
- In batch PMID preflight, call PMC ID Converter with batches up to its documented
  limit, then perform BioC-PMC checks with bounded concurrency.
- Reuse application-scoped HTTP clients and rate limiters rather than creating
  short-lived clients inside every MCP tool where practical.

Parallelism must remain polite. It should reduce wall-clock time without
increasing burst pressure on NCBI, PMC, or Europe PMC.

### 5. Passage-Level Addressability Is Missing

LLM consumers often need a targeted follow-up after retrieval:

- expand one truncated passage,
- fetch neighboring passages from the same section,
- verify one citation key,
- retrieve an exact passage by `passage_id`.

Recommended tools:

- `pubtator.get_review_passages_by_id`
  - Inputs: `review_id`, `passage_ids`, `max_chars_per_passage`, `include_metadata`
  - Output: exact passages or not-found diagnostics.
- `pubtator.get_neighboring_review_passages`
  - Inputs: `review_id`, `passage_id`, `before`, `after`, `same_section`
  - Output: ordered local context around the passage.
- `pubtator.expand_review_passage`
  - Inputs: `review_id`, `passage_id`, `max_chars`, optional `center_on_query`
  - Output: larger window from the stored original passage text.

These tools should operate only on the review index. They should not perform new
network retrieval.

### 6. Review Index Lifecycle Is Not Exposed

The `review_id` abstraction is right, but LLM consumers need inventory and cleanup
for long-running work.

Recommended lifecycle tools:

- `pubtator.list_review_indexes`
  - Include review ID, creation time, updated time, source counts, passage counts,
    preparation status, and approximate bytes.
- `pubtator.get_review_index_summary`
  - Similar to inspect, but optimized for high-level inventory.
- `pubtator.delete_review_index`
  - Expose only for local/private deployments, or guard behind config.
- TTL cleanup
  - Background cleanup for stale indexes in hosted deployments.

For public hosted MCP, destructive lifecycle operations should remain disabled by
default.

### 7. Tool Output Schemas Are Too Generic

FastMCP currently exposes output schemas, but the generated schemas for these MCP
tools are effectively generic objects because the tool functions return
`dict[str, Any]`.

Recommended behavior:

- Return typed Pydantic models from MCP tools where possible.
- Use FastMCP output schemas or explicit `output_schema` values for key tools.
- Keep response JSON backward compatible while making schema discoverable.
- Prioritize schemas for:
  - `search_literature`
  - `index_review_evidence`
  - `inspect_review_index`
  - `retrieve_review_context_batch`
  - new passage-by-ID tools

This should improve LLM self-correction and downstream client validation.

### 8. Stringly-Typed Search Friction Remains

The current search tool has better flat filters than before, but `sort` and raw
`filters` remain partially stringly typed.

Recommended behavior:

- Replace free `sort` strings with enum-like arguments:
  - `sort_by: "score" | "date"`
  - `sort_direction: "asc" | "desc"`
- Keep raw `filters` as an escape hatch.
- Add structured filter fields for common biomedical workflows:
  - `publication_types`
  - `year_min`
  - `year_max`
  - `has_pmcid`
  - `open_access_only`
  - `journal`
  - `article_types`
- Add a search preflight response section:
  - `candidate_pmids`
  - `coverage_hints`
  - `recommended_index_pmids`
  - `excluded_or_weak_candidates`

## Scientific And Reproducibility Upgrade

### Evidence Tiers

Every returned passage should carry an evidence tier derived from source coverage
and source type:

- `PASSAGE_FULL_TEXT`: full text passage.
- `PASSAGE_ABSTRACT`: abstract passage.
- `METADATA_TITLE`: title-only or metadata-only.
- `CURATED_FULL_TEXT`: user-provided full text source.
- `UNVERIFIED_EXTERNAL`: explicit external URL source not validated through
  approved literature APIs.

This lets an LLM tag claims without cross-referencing `inspect_review_index`.

### Claim Support Objects

Add optional deterministic claim-support records:

```json
{
  "claim_id": "claim_001",
  "claim_text": "Colchicine is recommended after clinical diagnosis of FMF.",
  "support_level": "direct",
  "evidence_tier": "PASSAGE_FULL_TEXT",
  "passage_ids": ["PMID:37747561:discuss:59"],
  "coverage": "full_text",
  "limitations": []
}
```

The backend should not use an LLM to judge claims. Instead, it should provide a
schema so clients can store their claim-to-evidence mapping reproducibly.

### PRISMA-Style Audit Trail

Add review metadata for reproducibility:

- search queries,
- search dates,
- filters,
- source databases/APIs,
- returned counts,
- deduplication counts,
- indexed PMIDs,
- excluded PMIDs with reasons,
- failed source attempts,
- coverage distribution,
- retrieval query batches,
- final passage IDs used.

This supports PRISMA-style reporting without claiming full PRISMA compliance.

### GRADE-Style Evidence Certainty Metadata

Add optional fields for evidence synthesis workflows:

- outcome or question,
- study design,
- risk of bias notes,
- inconsistency notes,
- indirectness notes,
- imprecision notes,
- publication bias notes,
- overall certainty label,
- certainty rationale,
- linked passage IDs.

The backend should store these judgments, not compute them. GRADE judgments are
contextual and should remain human/LLM-client supplied with auditable evidence.

## Recommended Implementation Slices

### Slice 1: Coverage Preflight And Resolver Audit

Goal: make source coverage predictable before indexing and explain fallback
outcomes after indexing.

Deliverables:

- Add source preflight models:
  - `SourceCoverageHint`
  - `CoverageReason`
  - `ResolverAttemptSummary`
- Add `coverage_reason`, `pmc_fallback_available`, `pmcid`, `doi`, and
  `license_or_access_hint` where known.
- Add PMC ID Converter client.
- Add BioC-PMC client.
- Add optional PMC OAI-PMH metadata/full-text probe.
- Add tests for abstract-only, full-text, no-PMC, embargo/unavailable, timeout,
  and upstream error cases.

Suggested public surface:

- `pubtator.preflight_review_sources`
- Add optional `include_coverage_hints=true` to `search_literature`
- Add coverage summary to `index_review_evidence` response when cheap.

### Slice 2: Retry, Backoff, And API Resilience

Goal: make upstream failures transparent and recoverable.

Deliverables:

- Central retry policy in the API client layer.
- Endpoint-specific retry configs.
- `Retry-After` support.
- Full-jitter exponential backoff.
- Attempt telemetry in logs and source attempts.
- Tests with `respx` for 429, 503, timeout, retry exhaustion, and success after
  retry.

### Slice 3: Async Parallel Batch Retrieval

Goal: reduce multi-query retrieval latency while preserving deterministic output.

Deliverables:

- Bounded concurrent per-query retrieval in `retrieve_context_batch`.
- Deterministic merge order by original query index.
- Configurable concurrency, default low.
- Tests proving output order stability and faster concurrent scheduling with
  fake delayed repositories.

### Slice 4: Passage Addressability

Goal: make targeted evidence re-grounding cheap.

Deliverables:

- Repository methods:
  - `get_passages_by_id`
  - `neighboring_passages`
- MCP tools:
  - `pubtator.get_review_passages_by_id`
  - `pubtator.get_neighboring_review_passages`
- REST route equivalents if desired.
- Tests for not-found passage IDs, section boundaries, ordering, and char budgets.

### Slice 5: Typed MCP Outputs

Goal: make schemas precise and machine-validated.

Deliverables:

- Return Pydantic models instead of `dict[str, Any]` for high-use tools.
- Verify generated MCP output schemas are specific.
- Add facade tests that fail if key output schemas degrade to generic objects.

### Slice 6: Review Audit And Scientific Metadata

Goal: make reviews reproducible across sessions.

Deliverables:

- Persist search runs and retrieval runs.
- Add PRISMA-style flow summary.
- Add optional GRADE-style evidence certainty records.
- Add exportable audit bundle:
  - JSON
  - Markdown
  - possibly RIS/BibTeX later.

## Async And Backoff Design Notes

### Concurrency Controls

Use separate semaphores per class of work:

- PubTator API calls.
- PMC ID Converter calls.
- BioC-PMC calls.
- PMC OAI-PMH calls.
- Europe PMC calls.
- curated URL fetches.

Avoid a single global semaphore that lets one slow source class starve all other
work. Keep defaults conservative.

Suggested defaults:

- PubTator: existing rate limit, no more than 2-3 requests/second.
- PMC OAI-PMH: no more than 3 requests/second and avoid high-concurrency
  requests, consistent with PMC guidance.
- BioC-PMC: conservative per-host limit.
- Europe PMC: conservative per-host limit with documented config.

### Retry Policy

Use one reusable policy object:

```python
class RetryPolicy(BaseModel):
    max_attempts: int = 3
    base_delay_ms: int = 500
    max_delay_ms: int = 10000
    retry_status_codes: set[int] = {408, 429, 500, 502, 503, 504}
    respect_retry_after: bool = True
    jitter: Literal["full"] = "full"
```

The implementation should expose the final attempt metadata to callers where it
affects evidence coverage.

### Idempotency Rules

Safe to retry by default:

- Search.
- Publication export.
- PMC export.
- Entity autocomplete.
- Relations.
- Metadata/preflight lookups.
- Full-text fetches from approved APIs.

Retry with caution:

- Text annotation submission.
- Any future mutation-like operation.

Do not retry:

- Validation errors.
- 401/403 unless the endpoint explicitly documents transient auth behavior.
- 404 unless there is evidence of eventual consistency and the request is inside
  a preparation retry loop.

## Usability Improvements For LLM Consumers

### Better Top-Level Batch Summary

Add fields to `retrieve_review_context_batch`:

- `passages`: alias to `merged_context_pack.passages` for compact modes, or a
  documented replacement for empty `results`.
- `not_found_summary`: one-line summary of zero-result queries.
- `budget_explanation`: compact explanation of how `max_passages_per_query`,
  `max_total_passages`, `max_chars`, and `max_response_chars` interacted.
- `covered_by_other_queries`: for zero-result or all-over-budget queries, list
  other query indices or PMIDs that already covered overlapping passages.

### Improve `prepare_mode`

Current code accepts `prepare_mode="selected" | "candidate_fast"` but does not
appear to alter queue behavior. Options:

- Remove `candidate_fast` from the public MCP schema until implemented.
- Or document it as reserved/currently equivalent.
- Or implement `candidate_fast` as a real mode that indexes top-N search
  candidates with cheap coverage preflight and stricter timeout.

Preferred: implement real semantics or hide it.

### Tool Name Token Cost

The `mcp__pubtator-link__...` prefix observed by consumers is mostly a client
harness display issue. The server public tool names are already reasonably
compact (`pubtator.retrieve_review_context_batch`). The server can help by:

- keeping public tool names stable and canonical,
- avoiding duplicate aliases,
- improving descriptions,
- exposing prompts/resources for workflow discovery.

Short aliases should be considered only if measurement shows real token savings
inside target clients. They can create ambiguity and duplicate discovery cost.

## Measurement Plan

Track before/after metrics with repeatable tasks:

- First useful passage latency.
- End-to-end review build latency.
- Index preparation latency per PMID.
- Percent of PMIDs with preflight coverage hints.
- Percent of abstract-only sources with explicit reason.
- Retry success rate after transient upstream errors.
- Number of tool calls per final grounded answer.
- Tokens returned per useful cited passage.
- Citation audit completeness:
  - passage ID,
  - source coverage,
  - source reason,
  - stable citation key,
  - retrieval query,
  - review ID.

Recommended recurring benchmark tasks:

- FMF/colchicine guideline synthesis.
- Variant/pathogenicity evidence mining.
- Drug-gene-disease relation review.
- Rare disease guideline update search.
- Mixed full-text and abstract-only corpus.

## Risk Register

### Upstream Load Risk

Parallelism can unintentionally increase request bursts. Mitigation: per-host
semaphores, rate limiters, backoff, and conservative defaults.

### Copyright And License Risk

Publisher scraping is risky for hosted tools. Mitigation: default to PubTator,
PMC ID Converter, BioC-PMC, PMC OAI-PMH, Europe PMC open-access APIs, and user
curated URLs.

### False Coverage Confidence

Coverage hints can be wrong if metadata is stale. Mitigation: distinguish
`expected_coverage` from `actual_coverage`, and always record resolver attempts.

### Schema Churn

Adding typed output schemas may expose breaking assumptions in clients.
Mitigation: preserve JSON field names and add schema tests.

### Scientific Overclaiming

GRADE/PRISMA-aligned metadata must not imply the backend has performed expert
appraisal. Mitigation: store and export judgments; do not compute clinical
recommendations.

## Prioritized Roadmap

1. Coverage preflight, resolver attempts, and coverage reasons.
2. Retry/backoff and transient failure transparency.
3. Bounded async parallelism for batch retrieval and source preflight.
4. Passage-by-ID and neighboring passage tools.
5. Typed MCP output schemas for high-use tools.
6. Review index inventory and TTL cleanup.
7. PRISMA-style audit bundle.
8. GRADE-style evidence certainty storage.
9. Optional Europe PMC fallback.
10. Real `candidate_fast` prepare mode or public removal.

## Acceptance Criteria For The Next Major Upgrade

- For every indexed PMID, `inspect_review_index` reports `coverage`,
  `coverage_reason`, source attempts, and actual fallback source.
- Preflight can tell an LLM whether a PMID is likely full-text, abstract-only,
  title-only, or unknown before indexing.
- Transient 429/5xx failures are retried with exponential backoff and visible
  retry diagnostics.
- Batch retrieval runs independent query retrieval concurrently while preserving
  deterministic response ordering.
- A caller can fetch or expand a passage by `passage_id` without re-running a
  search query.
- Key MCP tools expose specific output schemas.
- Retrieval responses include evidence tier metadata on each passage.
- Review runs can export a reproducible audit bundle containing search queries,
  source coverage, resolver attempts, retrieval queries, passage IDs, and stable
  citation keys.

## Primary Sources Consulted

- Model Context Protocol tools specification:
  <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
- Model Context Protocol schema reference:
  <https://modelcontextprotocol.io/specification/2025-06-18/schema>
- MCP server concepts:
  <https://modelcontextprotocol.io/docs/learn/server-concepts>
- FastMCP tools and output schemas:
  <https://gofastmcp.com/servers/tools>
- PubTator 3.0 article:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC11223843/>
- NCBI text mining web APIs:
  <https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/>
- NCBI BioC-PMC API:
  <https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/>
- PMC ID Converter API:
  <https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/>
- PMC OAI-PMH API:
  <https://pmc.ncbi.nlm.nih.gov/tools/oai/>
- Europe PMC open-access downloads:
  <https://europepmc.org/downloads/openaccess>
- PRISMA 2020:
  <https://www.prisma-statement.org/prisma-2020>
- GRADE Working Group:
  <https://www.gradeworkinggroup.org/>
- GRADE Book:
  <https://help.gradepro.org/support/solutions/articles/204000075707-grade-book>
- Cochrane RoB 2 guidance:
  <https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2>
