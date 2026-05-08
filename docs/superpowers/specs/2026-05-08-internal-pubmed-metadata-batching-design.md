# Internal PubMed Metadata Batching Design

## Purpose

This sprint adds shared internal PubMed metadata batching so PubTator-Link can
enrich large internal PMID sets without weakening the public metadata request
contract. It is the next P0 sprint after the MCP payload-controls work and the
optional dense-rerank merge.

The public `PublicationMetadataRequest.pmids` validation remains capped at 100
PMIDs. Internal services that naturally gather larger source, seed, or
candidate PMID lists will call a shared batching helper that chunks requests
into public-cap-sized batches and merges partial results.

## Goals

- Keep public REST and MCP publication metadata requests capped at 100 PMIDs.
- Add a shared internal metadata batching helper for larger PMID sequences.
- Preserve first-seen input order while deduplicating repeated PMIDs.
- Chunk internal lookups into batches no larger than the public metadata request
  cap. This reuses PubTator-Link's public contract and validation path; it is
  not an upstream PubMed limit.
- Merge successful metadata records, `failed_pmids`, and provider warnings from
  every batch.
- Treat a failed batch as a partial failure, not an all-or-nothing failure.
- Replace related-evidence local metadata chunking with the shared helper.
- Make `inspect_review_index(include_metadata=True)` work when the inspected
  page contains more than 100 sources.
- Make topic map metadata enrichment tolerate more than 100 seed and candidate
  PMIDs.
- Use the helper in citation graph's existing source metadata path for
  consistency, without adding new neighbor metadata enrichment in this sprint.
- Preserve existing REST and MCP compatibility.

## Non-Goals

- Raising the public `PublicationMetadataRequest.pmids` cap.
- Changing PubMed ESummary or EFetch parsing behavior.
- Adding concurrency, retry policy changes, caching, or rate-limit orchestration.
- Changing graph ranking, compact payload budgets, or dense-rerank behavior.
- Adding new public API fields for batch metadata lookup.
- Reworking review index pagination beyond metadata attachment behavior.

## Current Code Findings

`pubtator_link/models/publication_metadata.py` defines
`PublicationMetadataRequest.pmids` with `max_length=100`. The validator also
normalizes `PMID:` prefixes, strips whitespace, drops blank entries, rejects
non-numeric IDs, and deduplicates within the public request.

`pubtator_link/services/publication_metadata.py` exposes only
`PublicationMetadataService.get_metadata(request)`. That method expects an
already-valid `PublicationMetadataRequest`, fetches ESummary for the request
PMIDs, optionally fetches MeSH headings and coverage, builds citation fields,
and returns a `PublicationMetadataResponse`.

Current oversized or duplicated internal patterns:

- `ReviewContextService._attach_source_metadata()` collects inspected source
  PMIDs and sends one `PublicationMetadataRequest`. If the page contains more
  than 100 unique PMIDs, validation can fail before metadata attachment.
- `RelatedEvidenceService._metadata_candidates()` already chunks candidate
  PMIDs locally in groups of 100. This is the desired behavior, but it is ad hoc
  and duplicates batching policy.
- `TopicLiteratureMapService._metadata_papers()` sends `list(pmids)` directly
  to `PublicationMetadataRequest`, so seed and backfill enrichment can fail when
  candidate sets exceed 100.
- `CitationGraphService._metadata_for_pmid()` performs single-PMID metadata
  lookup today. Future graph enrichment or DOI resolution paths should use the
  same helper whenever a multi-PMID lookup is introduced.
- `pubtator_link/mcp/service_adapters.py` and
  `pubtator_link/api/routes/search.py` keep public metadata and search
  enrichment behavior. These paths should preserve public request validation and
  route/tool compatibility.

Existing tests already cover the public 100-PMID cap
(`test_publication_metadata_request_rejects_too_many_pmids`) and
related-evidence batching behavior
(`test_related_evidence_batches_large_metadata_candidate_sets`). The
implementation sprint needs focused tests for the new shared helper and for
every service path that can exceed one public metadata request.

## Recommended Design

Add one module-level internal batching helper in
`pubtator_link/services/publication_metadata.py`:

```python
class PublicationMetadataLookup(Protocol):
    async def get_metadata(self, request: PublicationMetadataRequest) -> PublicationMetadataResponse:
        """Return publication metadata for PMIDs."""

async def lookup_metadata_batched(
    metadata_service: PublicationMetadataLookup,
    pmids: Sequence[str],
    *,
    include_mesh: bool = False,
    include_publication_types: bool = True,
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "none",
    include_coverage: bool = True,
    batch_size: int = 100,
) -> PublicationMetadataResponse:
    ...
```

The helper accepts large internal sequences, normalizes and validates PMIDs with
the same rules as `PublicationMetadataRequest`, deduplicates repeated IDs while
preserving first-seen order, chunks unique PMIDs into batches of at most 100, and
calls `metadata_service.get_metadata(PublicationMetadataRequest(...))` for each
batch.

The helper accepts `Sequence[str]` for internal ergonomics, but every chunk is
converted to `list[str]` before constructing `PublicationMetadataRequest`.

The helper defaults match the dominant internal enrichment path: no MeSH EFetch
and no generated NLM/BibTeX citations unless a caller opts in. Review index
metadata can still pass `include_mesh=True` and `include_citations="both"` for
full metadata mode, and topic maps can still pass `include_mesh=include_entities`.

`PublicationMetadataService` keeps its existing public method unchanged:

```python
async def get_metadata(
    self,
    request: PublicationMetadataRequest,
) -> PublicationMetadataResponse:
    ...
```

Public REST and MCP callers continue to construct `PublicationMetadataRequest`
directly and therefore keep the 100-PMID cap. Internal services call
`lookup_metadata_batched(...)` instead of calling `get_metadata()` directly for
PMID lists that can exceed one public request.

This design keeps protocol-like metadata dependencies simple. For example,
the existing `PublicationMetadataLookup` protocol shape can move to
`publication_metadata.py` and continue requiring only `get_metadata()`. Test
doubles do not need to implement a second method. There is one merge
implementation: the module-level helper.

## Helper Semantics

### Input Normalization

The helper uses the same PMID normalization rules as the public model:

- Trim whitespace.
- Strip a leading `PMID:` prefix case-insensitively.
- Drop blank values.
- Reject non-numeric PMIDs.
- Preserve the first occurrence of each valid PMID.

If normalization leaves no valid PMID because the input is empty or contains only
blank values, the helper returns `PublicationMetadataResponse(success=True,
metadata=[], failed_pmids={}, _meta={"next_commands": []})`. This mirrors the
existing internal call sites, which already early-return on empty input, and
makes the helper safe for future callers.

Internal non-numeric PMIDs raise `ValueError("PMID must be numeric")` rather
than being soft-dropped. This intentionally fails loud because non-numeric PMIDs
indicate upstream source hygiene problems in review, graph, or search flows.
Direct public calls still receive Pydantic validation errors from
`PublicationMetadataRequest`.

### Chunking

The helper chunks normalized unique PMIDs into batches of 100 by default. This
is PubTator-Link's public metadata request cap, not an upstream PubMed limit.
The implementation may keep `batch_size` configurable for tests, but production
call sites should rely on the default.

Every batch should still be represented by a public `PublicationMetadataRequest`
so the lower-level client behavior and public cap remain exercised.

Batched calls multiply the existing per-request side effects: `include_mesh=True`
means one EFetch XML call per batch, and `include_coverage=True` means one
coverage-provider call per batch. This is accepted for this sprint because the
goal is correctness and public-cap safety. A 1,000-PMID internal lookup becomes
about 10 sequential metadata batches. If this becomes too slow for hot paths,
the follow-up should optimize the helper executor or coverage aggregation
without changing service call sites.

Batches run sequentially in this sprint. The loop should be isolated in the
helper so a future concurrency change can replace the sequential executor
without changing service call sites. Warning merge order is therefore
deterministic first-seen order in this sprint.

### Merge Order

The helper returns metadata in the order of the first occurrence of each PMID in
the original input sequence. If a provider returns metadata records out of order,
the helper reorders them by the normalized input order.

Duplicate PMIDs are looked up once and appear once in the merged response.

### Partial Failures

One failed batch must not discard successful batches. If `get_metadata()` raises
for a batch, the helper:

- Adds each PMID in that failed batch to `failed_pmids` with reason
  `batch_request_failed`.
- Adds a warning string `pubmed_metadata_batch_failed`.
- Continues with later batches.

If a batch returns normally with `failed_pmids`, those failures are merged into
the final response. Batch-level `_meta.warnings` are appended and deduplicated in
first-seen order.

The final `PublicationMetadataResponse.success` uses the existing metadata
service convention: `success=True` means the helper returned a structured
response, not that every PMID resolved. Consumers must use `metadata`,
`failed_pmids`, and `_meta.warnings` for data availability. If every batch
raises, the helper still returns `success=True`, an empty `metadata` list,
`failed_pmids` containing every normalized PMID with `batch_request_failed`, and
`_meta.warnings` containing `pubmed_metadata_batch_failed`.

### Response Metadata

The merged response keeps the existing metadata response shape:

- `metadata`: ordered successful `PublicationMetadata` records.
- `failed_pmids`: merged per-PMID failure reasons.
- `_meta.source`: existing PubMed metadata source string when available.
- `_meta.next_commands`: existing next-command guidance based on whether any
  metadata was returned.
- `_meta.warnings`: merged warning strings when any batch or sub-provider warns.

`_meta.source` should use the first non-empty batch source. `_meta.next_commands`
should be derived once from the final merged metadata list, not concatenated from
each batch, to avoid duplicate guidance.

Warning strings are deduplicated in first-seen order. This means one
`mesh_lookup_failed` warning may represent one failed batch or many failed
batches. That lossy warning merge is acceptable for this sprint. If observability
needs to improve later, add ignorable `_meta` diagnostics such as `batch_count`
and `failed_batch_count`.

## Shared Helper Boundary

Several services type their metadata dependency as a protocol-like object with a
`get_metadata()` method. The shared helper is deliberately a free function so
those protocols stay minimal and alternate metadata services can be used without
duck-typing for optional methods.

The helper should live with publication metadata service code, not inside an
individual graph or review service. It is the only internal batching and merge
implementation for this sprint.

## Service Integration

### Review Index Metadata

`ReviewContextService._attach_source_metadata()` should call the shared helper
instead of constructing one `PublicationMetadataRequest`. This makes
`inspect_review_index(include_metadata=True)` work for pages with more than 100
sources while preserving existing compact/full serialization behavior.

The method should continue attaching metadata only to sources returned on the
current page. It should not fetch metadata for omitted pages.

### Related Evidence

`RelatedEvidenceService._metadata_candidates()` should remove its local
`_chunks(pmids, 100)` loop and call the shared helper once. Existing behavior
must remain:

- Large candidate sets are resolved in PubMed-sized batches.
- Candidate PMIDs preserve ranking input order before final scoring and limits.
- Metadata failures become provider warnings.
- Candidates without metadata remain unresolved references rather than being
  dropped solely due to metadata failure.

Remove `related_evidence.py`'s private `_chunks()` helper if it becomes unused.

### Topic Literature Map

`TopicLiteratureMapService._metadata_papers()` should call the shared helper for
seed and backfill metadata enrichment. More than 100 seed or candidate PMIDs
must not raise a public request validation error. Partial metadata failures
should add PubMed metadata provider warnings and still return papers/entities
from successful batches.

### Citation Graph

`CitationGraphService` currently fetches metadata one PMID at a time. This
sprint should update `_metadata_for_pmid()` to call `lookup_metadata_batched()`
with a one-item sequence so citation graph source resolution uses the shared
metadata boundary without introducing new graph enrichment behavior.

The sprint should not add neighbor metadata enrichment for references or
`cited_by` papers. That is a separate graph-quality feature with ranking and
payload implications. The acceptance criterion for citation graph in this sprint
is compatibility: the existing source metadata path still works and uses the
shared helper. Because `_metadata_for_pmid()` already returns `None` when the
metadata response has no records, a helper response with
`failed_pmids[pmid] = "batch_request_failed"` preserves the existing
None-on-failure behavior.

### REST And MCP Adapters

`get_publication_metadata` REST/MCP behavior remains public and capped at 100.
Route and MCP compatibility tests should prove that sending more than 100 PMIDs
to the public metadata request still fails validation.

Search enrichment in `pubtator_link/api/routes/search.py` is bounded by the
route `limit` query parameter with `le=50` before metadata enrichment. MCP
search enrichment in `pubtator_link/mcp/service_adapters.py` defaults to
`limit=5`; if callers pass `limit=None`, it enriches the current PubTator page.
These paths are not the primary implementation targets for this sprint. Add
compatibility tests that keep their response shapes stable and keep direct
public metadata requests capped at 100. Do not broaden search batching scope
unless a focused test proves an existing search path can construct more than 100
metadata PMIDs.

## Error Handling

The helper should make failures observable without turning partial metadata
availability into complete feature loss:

- Public validation errors still happen for direct public metadata requests over
  100 PMIDs.
- Internal non-numeric PMIDs still raise validation errors instead of being
  silently dropped.
- A provider exception for one batch marks only that batch as failed with
  `batch_request_failed`; PubMed records that are not found in a successful batch
  keep the existing `metadata_not_found` reason.
- Existing `mesh_lookup_failed` and `coverage_lookup_failed` warnings merge
  across batches.
- Duplicate warnings are collapsed in first-seen order.
- A coverage-provider failure in one batch does not drop metadata records from
  successful ESummary batches; it contributes a single deduplicated
  `coverage_lookup_failed` warning.
- Services that already convert PubMed metadata problems into `ProviderWarning`
  entries should continue doing so after receiving merged helper warnings.

## Testing Strategy

Use TDD in the implementation sprint. Add failing tests before implementation
for each behavioral requirement.

Core helper tests in `tests/unit/test_publication_metadata_service.py`:

- Existing `test_publication_metadata_request_rejects_too_many_pmids` continues
  proving the public cap rejects 101 PMIDs.
- Internal helper accepts more than 100 PMIDs and calls `get_metadata()` in
  batches no larger than 100.
- Metadata output preserves first-seen input order.
- Duplicate input PMIDs are fetched once and returned once.
- Batch `failed_pmids` are merged.
- Batch `_meta.warnings` are merged and deduplicated.
- One raised batch records only that batch's PMIDs as failed and preserves
  successful batches.
- Empty input and blank-only input return an empty successful response.
- A coverage-provider failure in one batch out of multiple batches returns
  metadata from successful batches and one deduplicated `coverage_lookup_failed`
  warning.

Model tests in `tests/unit/test_publication_metadata_models.py`:

- Keep the existing public cap regression test.
- Add any helper-facing normalization regression only if normalization logic is
  exposed from the model module.

Review tests in `tests/unit/test_review_context_service.py`:

- `inspect_review_index(include_metadata=True)` with more than 100 page sources
  attaches metadata without constructing an oversized public request.
- The service fetches metadata only for the current page when pagination omits
  later sources.

Related evidence tests in `tests/unit/test_related_evidence_service.py`:

- Existing `test_related_evidence_batches_large_metadata_candidate_sets` still
  passes after local chunking is replaced.
- Partial metadata batch failure still returns candidates from successful
  batches and emits PubMed metadata warnings.

Topic map tests in `tests/unit/test_topic_literature_map_service.py`:

- More than 100 seed/candidate PMIDs do not raise validation errors.
- Successful batch metadata still enriches papers and entities when a later
  batch fails.

Citation graph tests in `tests/unit/test_citation_graph_service.py`:

- Metadata enrichment remains compatible for source PMID resolution.
- Source PMID metadata resolution uses `lookup_metadata_batched()` and preserves
  the existing single-PMID response behavior.

MCP and route tests:

- `tests/unit/mcp/test_mcp_service_adapters.py`
  `test_get_publication_metadata_impl_returns_typed_payload` remains compatible,
  and a new public-cap regression keeps `get_publication_metadata_impl()` capped
  at 100.
- MCP service paths that call review inspect, related evidence, topic map, or
  citation graph continue returning compatible response shapes.
- `tests/test_routes/test_search.py`
  `test_search_publications_can_enrich_basic_metadata` preserves search metadata
  enrichment compatibility.

Focused implementation checks should run after each task. Final verification for
the future implementation must end with:

```bash
make ci-local
```

## Acceptance Criteria

- Public `PublicationMetadataRequest.pmids` remains capped at 100.
- A shared internal helper accepts larger PMID sequences.
- The helper chunks lookups into public-request-sized batches.
- The helper preserves input order and deduplicates PMIDs.
- The helper merges metadata, `failed_pmids`, and warnings.
- A failed batch does not discard successful batch results.
- `ReviewContextService._attach_source_metadata()` uses the helper.
- `RelatedEvidenceService._metadata_candidates()` uses the helper instead of
  local chunking.
- `TopicLiteratureMapService._metadata_papers()` uses the helper.
- `CitationGraphService._metadata_for_pmid()` uses the shared helper for its
  existing single-PMID source metadata path.
- `inspect_review_index(include_metadata=True)` works for more than 100 sources.
- Topic map enrichment works for more than 100 seed/candidate PMIDs.
- REST and MCP public metadata compatibility is preserved.
- Focused unit, route, and MCP tests pass.
- Future implementation verification ends with `make ci-local`.

## Design Rationale

The module-level helper keeps the public/private boundary clear. Public clients
still receive fast validation and a manageable request contract, while internal
services get a single correct implementation for larger workflows. Reusing
`PublicationMetadataRequest` inside each chunk keeps the existing PubMed lookup
behavior and cap exercised, and a shared merge path prevents related evidence,
review inspection, and topic maps from drifting into subtly different failure
semantics.

This sprint deliberately avoids concurrency and caching. The immediate risk is
correctness and compatibility when internal lists exceed 100 PMIDs. Performance
improvements can be added later once the shared contract is tested and stable.
