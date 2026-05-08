# Internal PubMed Metadata Batching Design

## Purpose

This sprint adds shared internal PubMed metadata batching so PubTator-Link can
enrich large internal PMID sets without weakening the public metadata request
contract. It is the next P0 sprint after the MCP payload-controls work and the
optional dense-rerank merge.

The public `PublicationMetadataRequest.pmids` validation remains capped at 100
PMIDs. Internal services that naturally gather larger source, seed, candidate,
or graph PMID lists will call a shared batching helper that chunks requests into
PubMed-sized batches and merges partial results.

## Goals

- Keep public REST and MCP publication metadata requests capped at 100 PMIDs.
- Add a shared internal metadata batching helper for larger PMID sequences.
- Preserve first-seen input order while deduplicating repeated PMIDs.
- Chunk internal lookups into batches no larger than the public PubMed metadata
  request size.
- Merge successful metadata records, `failed_pmids`, and provider warnings from
  every batch.
- Treat a failed batch as a partial failure, not an all-or-nothing failure.
- Replace related-evidence local metadata chunking with the shared helper.
- Make `inspect_review_index(include_metadata=True)` work when the inspected
  page contains more than 100 sources.
- Make topic map metadata enrichment tolerate more than 100 seed and candidate
  PMIDs.
- Use the helper in citation graph code where metadata enrichment could grow
  beyond one PMID.
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

Existing tests already cover the public 100-PMID cap and some related-evidence
batching behavior. The implementation sprint needs focused tests for the new
shared helper and for every service path that can exceed one public metadata
request.

## Recommended Design

Add a service-level internal batching API on `PublicationMetadataService`:

```python
async def get_metadata_batched(
    self,
    pmids: Sequence[str],
    *,
    include_mesh: bool = True,
    include_publication_types: bool = True,
    include_citations: IncludeCitations = "both",
    include_coverage: bool = True,
    batch_size: int = 100,
) -> PublicationMetadataResponse:
    ...
```

The method accepts large internal sequences, normalizes and validates PMIDs with
the same rules as `PublicationMetadataRequest`, deduplicates repeated IDs while
preserving first-seen order, chunks unique PMIDs into batches of at most 100, and
calls existing `get_metadata(PublicationMetadataRequest(...))` for each batch.

The public method remains unchanged:

```python
async def get_metadata(
    self,
    request: PublicationMetadataRequest,
) -> PublicationMetadataResponse:
    ...
```

Public REST and MCP callers continue to construct `PublicationMetadataRequest`
directly and therefore keep the 100-PMID cap.

## Helper Semantics

### Input Normalization

The helper uses the same PMID normalization rules as the public model:

- Trim whitespace.
- Strip a leading `PMID:` prefix case-insensitively.
- Drop blank values.
- Reject non-numeric PMIDs.
- Preserve the first occurrence of each valid PMID.

If normalization leaves no valid PMID, the helper raises the same validation
error shape as constructing `PublicationMetadataRequest` with no usable PMIDs.
This keeps internal misuse visible during development.

### Chunking

The helper chunks normalized unique PMIDs into batches of 100 by default. The
implementation may keep `batch_size` configurable for tests, but production call
sites should rely on the default.

Every batch should still be represented by a public `PublicationMetadataRequest`
so the lower-level client behavior and public cap remain exercised.

### Merge Order

The helper returns metadata in the order of the first occurrence of each PMID in
the original input sequence. If a provider returns metadata records out of order,
the helper reorders them by the normalized input order.

Duplicate PMIDs are looked up once and appear once in the merged response.

### Partial Failures

One failed batch must not discard successful batches. If `get_metadata()` raises
for a batch, the helper:

- Adds each PMID in that failed batch to `failed_pmids`.
- Adds a provider warning indicating `pubmed_metadata_batch_failed`.
- Continues with later batches.

If a batch returns normally with `failed_pmids`, those failures are merged into
the final response. Batch-level `_meta.warnings` are appended and deduplicated in
first-seen order.

The final `PublicationMetadataResponse.success` remains `True` because the
helper response can contain partial data and explicit failures. Consumers should
use `metadata`, `failed_pmids`, and `_meta.warnings` for status.

### Response Metadata

The merged response keeps the existing metadata response shape:

- `metadata`: ordered successful `PublicationMetadata` records.
- `failed_pmids`: merged per-PMID failure reasons.
- `_meta.source`: existing PubMed metadata source string when available.
- `_meta.next_commands`: existing next-command guidance based on whether any
  metadata was returned.
- `_meta.warnings`: merged warning strings when any batch or sub-provider warns.

The implementation should avoid adding public-facing schema fields for internal
batch diagnostics. If internal diagnostics are needed, they can use `_meta` keys
that are safe for clients to ignore, such as `batch_count`.

## Internal Compatibility Helper

Several services type their metadata dependency as a protocol-like object with a
`get_metadata()` method. To avoid brittle test rewrites and to support alternate
internal metadata services, add a small shared helper that prefers
`get_metadata_batched()` when present and otherwise performs the same chunked
fallback around `get_metadata()`.

This helper should live with publication metadata service code, not inside an
individual graph or review service. A suitable private helper name is:

```python
async def get_metadata_batched(
    metadata_service: Any,
    pmids: Sequence[str],
    *,
    include_mesh: bool,
    include_publication_types: bool,
    include_citations: IncludeCitations,
    include_coverage: bool,
) -> PublicationMetadataResponse:
    ...
```

The public service method and the module-level helper can share one internal
merge implementation to avoid divergent behavior.

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

### Topic Literature Map

`TopicLiteratureMapService._metadata_papers()` should call the shared helper for
seed and backfill metadata enrichment. More than 100 seed or candidate PMIDs
must not raise a public request validation error. Partial metadata failures
should add PubMed metadata provider warnings and still return papers/entities
from successful batches.

### Citation Graph

`CitationGraphService` currently fetches metadata one PMID at a time. The
implementation should leave single-PMID source resolution behavior compatible,
but use the shared helper if metadata enrichment is refactored or extended to
multiple PMIDs in the sprint. Tests should cover the citation graph path where
metadata enrichment could grow beyond one PMID, even if the first implementation
only verifies the helper-compatible single-PMID behavior.

### REST And MCP Adapters

`get_publication_metadata` REST/MCP behavior remains public and capped at 100.
Route and MCP compatibility tests should prove that sending more than 100 PMIDs
to the public metadata request still fails validation.

Search enrichment in `pubtator_link/api/routes/search.py` and
`pubtator_link/mcp/service_adapters.py` may continue using public requests if
their selected result limits remain within the cap. If a search path can exceed
100 enriched PMIDs, it should use the shared internal helper without changing
the public metadata endpoint cap.

## Error Handling

The helper should make failures observable without turning partial metadata
availability into complete feature loss:

- Public validation errors still happen for direct public metadata requests over
  100 PMIDs.
- Internal non-numeric PMIDs still raise validation errors instead of being
  silently dropped.
- A provider exception for one batch marks only that batch as failed.
- Existing `mesh_lookup_failed` and `coverage_lookup_failed` warnings merge
  across batches.
- Duplicate warnings are collapsed in first-seen order.
- Services that already convert PubMed metadata problems into `ProviderWarning`
  entries should continue doing so after receiving merged helper warnings.

## Testing Strategy

Use TDD in the implementation sprint. Add failing tests before implementation
for each behavioral requirement.

Core helper tests in `tests/unit/test_publication_metadata_service.py`:

- Public `PublicationMetadataRequest` still rejects 101 PMIDs.
- Internal helper accepts more than 100 PMIDs and calls `get_metadata()` in
  batches no larger than 100.
- Metadata output preserves first-seen input order.
- Duplicate input PMIDs are fetched once and returned once.
- Batch `failed_pmids` are merged.
- Batch `_meta.warnings` are merged and deduplicated.
- One raised batch records only that batch's PMIDs as failed and preserves
  successful batches.

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

- Existing large candidate batching behavior still passes after local chunking
  is replaced.
- Partial metadata batch failure still returns candidates from successful
  batches and emits PubMed metadata warnings.

Topic map tests in `tests/unit/test_topic_literature_map_service.py`:

- More than 100 seed/candidate PMIDs do not raise validation errors.
- Successful batch metadata still enriches papers and entities when a later
  batch fails.

Citation graph tests in `tests/unit/test_citation_graph_service.py`:

- Metadata enrichment remains compatible for source PMID resolution.
- Any multi-PMID metadata enrichment path introduced in the sprint uses the
  shared helper and tolerates more than 100 PMIDs.

MCP and route tests:

- `tests/unit/mcp/test_mcp_service_adapters.py` keeps public
  `get_publication_metadata_impl()` capped at 100.
- MCP service paths that call review inspect, related evidence, topic map, or
  citation graph continue returning compatible response shapes.
- `tests/test_routes/test_search.py` preserves search metadata enrichment
  compatibility and does not loosen the public metadata endpoint contract.

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
- Citation graph metadata enrichment uses the helper wherever it handles more
  than one PMID.
- `inspect_review_index(include_metadata=True)` works for more than 100 sources.
- Topic map enrichment works for more than 100 seed/candidate PMIDs.
- REST and MCP public metadata compatibility is preserved.
- Focused unit, route, and MCP tests pass.
- Future implementation verification ends with `make ci-local`.

## Design Rationale

The service-level helper keeps the public/private boundary clear. Public clients
still receive fast validation and a manageable request contract, while internal
services get a single correct implementation for larger workflows. Reusing
`PublicationMetadataRequest` inside each chunk keeps the existing PubMed lookup
behavior and cap exercised, and a shared merge path prevents related evidence,
review inspection, and topic maps from drifting into subtly different failure
semantics.

This sprint deliberately avoids concurrency and caching. The immediate risk is
correctness and compatibility when internal lists exceed 100 PMIDs. Performance
improvements can be added later once the shared contract is tested and stable.
