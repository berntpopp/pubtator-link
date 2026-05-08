# Internal PubMed Metadata Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared internal PubMed metadata batching so internal services can enrich more than 100 PMIDs without changing the public metadata request cap.

**Architecture:** Keep `PublicationMetadataRequest` as the public validation boundary capped at 100 PMIDs. Add one module-level helper in `pubtator_link/services/publication_metadata.py` that normalizes, deduplicates, chunks, calls `get_metadata()` with public-sized requests, and merges responses. Internal review, related evidence, topic map, and MCP search enrichment paths call the helper; direct REST and MCP publication metadata requests keep constructing `PublicationMetadataRequest` directly.

**Tech Stack:** Python 3.11, Pydantic v2 models, FastAPI route tests, MCP adapter tests, pytest with `pytest.mark.asyncio`, Ruff, mypy.

---

## File Structure

- Modify: `pubtator_link/services/publication_metadata.py`
  - Add `PublicationMetadataLookup` protocol.
  - Add `lookup_metadata_batched()` module-level helper.
  - Add private helper functions for internal PMID normalization, chunking, warning merging, and empty responses.
  - Keep `PublicationMetadataService.get_metadata()` unchanged.

- Modify: `pubtator_link/services/review_context_service.py`
  - Remove the local `PublicationMetadataLookup` protocol.
  - Import `PublicationMetadataLookup` and `lookup_metadata_batched()` from `pubtator_link.services.publication_metadata`.
  - Update `_attach_source_metadata()` to use the helper.

- Modify: `pubtator_link/services/related_evidence.py`
  - Keep direct single-PMID `_source_paper()` lookup unchanged.
  - Replace candidate local chunking in `_metadata_candidates()` with `lookup_metadata_batched()`.
  - Remove private `_chunks()` after `_metadata_candidates()` stops calling it.
  - Convert merged metadata response warnings and `failed_pmids` into existing `ProviderWarning` entries.

- Modify: `pubtator_link/services/topic_literature_map.py`
  - Replace `_metadata_papers()` direct `PublicationMetadataRequest(pmids=list(pmids))` call with `lookup_metadata_batched()`.
  - Convert helper warnings and `failed_pmids` into existing `ProviderWarning` entries.

- Modify: `pubtator_link/mcp/service_adapters.py`
  - Update private MCP search metadata enrichment `_search_metadata_by_pmid()` to use `lookup_metadata_batched()`.
  - Keep `get_publication_metadata_impl()` direct and capped by `PublicationMetadataRequest`.

- Do not modify production code in `pubtator_link/services/citation_graph.py`
  - Its current metadata path is single-PMID only.
  - Add only a compatibility test proving it remains single-PMID.

- Modify: `tests/unit/test_publication_metadata_service.py`
  - Add core helper tests.

- Modify: `tests/unit/test_review_context_service.py`
  - Add review index metadata batching and mode preservation tests.

- Modify: `tests/unit/test_related_evidence_service.py`
  - Keep `test_related_evidence_batches_large_metadata_candidate_sets` expecting request sizes `[1, 100, 100, 10]`.
  - Add helper migration tests for partial failures and option preservation.

- Modify: `tests/unit/test_topic_literature_map_service.py`
  - Add `_metadata_papers()` batching and partial failure tests.

- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
  - Add MCP search `limit=None` batching test.
  - Add public MCP metadata cap preservation test.

- Modify: `tests/unit/test_citation_graph_service.py`
  - Add compatibility test for the unchanged single-PMID metadata path.

- Run existing route compatibility test in `tests/test_routes/test_search.py`
  - No production REST search change is planned because route `limit` remains capped at 50.

---

### Task 1: Core Batched Lookup Helper

**Files:**
- Modify: `tests/unit/test_publication_metadata_service.py`
- Modify: `pubtator_link/services/publication_metadata.py`

- [ ] **Step 1: Write failing helper tests**

Add `PublicationMetadata` and `lookup_metadata_batched` to the imports in `tests/unit/test_publication_metadata_service.py`:

```python
from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)
from pubtator_link.services.publication_metadata import (
    NcbiPublicationMetadataClient,
    PublicationMetadataService,
    lookup_metadata_batched,
)
```

Add these tests after `_fetch_metadata()`:

```python
@pytest.mark.asyncio
async def test_lookup_metadata_batched_accepts_large_inputs_and_preserves_order() -> None:
    class RecordingLookup:
        def __init__(self) -> None:
            self.requests: list[PublicationMetadataRequest] = []

        async def get_metadata(
            self, request: PublicationMetadataRequest
        ) -> PublicationMetadataResponse:
            self.requests.append(request)
            warnings = ["coverage_lookup_failed"] if len(self.requests) == 2 else []
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(pmid=pmid, title=f"Paper {pmid}")
                    for pmid in reversed(request.pmids)
                ],
                _meta={
                    "source": "fake-source",
                    "next_commands": [],
                    "warnings": warnings,
                },
            )

    lookup = RecordingLookup()
    expected_pmids = [str(100000 + index) for index in range(105)]
    response = await lookup_metadata_batched(
        lookup,
        [" PMID:100000 ", *expected_pmids, "100003"],
    )

    assert [request.pmids for request in lookup.requests] == [
        expected_pmids[:100],
        expected_pmids[100:],
    ]
    assert all(request.include_mesh is False for request in lookup.requests)
    assert all(request.include_publication_types is True for request in lookup.requests)
    assert all(request.include_citations == "none" for request in lookup.requests)
    assert all(request.include_coverage is True for request in lookup.requests)
    assert [item.pmid for item in response.metadata] == expected_pmids
    assert response.failed_pmids == {}
    assert response.meta["source"] == "fake-source"
    assert response.meta["warnings"] == ["coverage_lookup_failed"]
    assert response.meta["warning_counts"] == {"coverage_lookup_failed": 1}
    assert response.meta["batch_count"] == 2
    assert response.meta["failed_batch_count"] == 0


@pytest.mark.asyncio
async def test_lookup_metadata_batched_merges_partial_failures_and_warnings() -> None:
    class PartiallyFailingLookup:
        def __init__(self) -> None:
            self.requests: list[PublicationMetadataRequest] = []

        async def get_metadata(
            self, request: PublicationMetadataRequest
        ) -> PublicationMetadataResponse:
            self.requests.append(request)
            if request.pmids == ["3", "4"]:
                raise RuntimeError("provider body with PMID 3 and URL https://example.test")
            if request.pmids == ["1", "2"]:
                return PublicationMetadataResponse(
                    metadata=[PublicationMetadata(pmid="1", title="Paper 1")],
                    failed_pmids={"2": "metadata_not_found"},
                    _meta={
                        "source": "fake-source",
                        "next_commands": [],
                        "warnings": [
                            "coverage_lookup_failed",
                            "coverage_lookup_failed",
                        ],
                    },
                )
            return PublicationMetadataResponse(
                metadata=[PublicationMetadata(pmid="5", title="Paper 5")],
                _meta={
                    "source": "fake-source",
                    "next_commands": [],
                    "warnings": ["mesh_lookup_failed"],
                },
            )

    response = await lookup_metadata_batched(
        PartiallyFailingLookup(),
        ["1", "2", "3", "4", "5"],
        batch_size=2,
    )

    assert [item.pmid for item in response.metadata] == ["1", "5"]
    assert response.failed_pmids == {
        "2": "metadata_not_found",
        "3": "batch_request_failed",
        "4": "batch_request_failed",
    }
    assert response.meta["warnings"] == [
        "coverage_lookup_failed",
        "pubmed_metadata_batch_failed",
        "mesh_lookup_failed",
    ]
    assert response.meta["warning_counts"] == {
        "coverage_lookup_failed": 2,
        "pubmed_metadata_batch_failed": 1,
        "mesh_lookup_failed": 1,
    }
    assert response.meta["batch_count"] == 3
    assert response.meta["failed_batch_count"] == 1
    assert response.meta["batch_failure_exception_types"] == ["RuntimeError"]
    assert "https://example.test" not in str(response.meta)
    assert "PMID 3" not in str(response.meta)


@pytest.mark.asyncio
async def test_lookup_metadata_batched_empty_or_blank_input_returns_empty_success() -> None:
    class UnexpectedLookup:
        async def get_metadata(
            self, request: PublicationMetadataRequest
        ) -> PublicationMetadataResponse:
            raise AssertionError("empty internal metadata lookup should not call provider")

    response = await lookup_metadata_batched(UnexpectedLookup(), [" ", "PMID: "])

    assert response.success is True
    assert response.metadata == []
    assert response.failed_pmids == {}
    assert response.meta == {"next_commands": []}


@pytest.mark.asyncio
async def test_lookup_metadata_batched_rejects_nonnumeric_pmids_before_requests() -> None:
    class RecordingLookup:
        def __init__(self) -> None:
            self.requests: list[PublicationMetadataRequest] = []

        async def get_metadata(
            self, request: PublicationMetadataRequest
        ) -> PublicationMetadataResponse:
            self.requests.append(request)
            return PublicationMetadataResponse(metadata=[], _meta={"next_commands": []})

    lookup = RecordingLookup()
    with pytest.raises(ValueError, match="PMID must be numeric"):
        await lookup_metadata_batched(lookup, ["1", "not-a-pmid"])

    assert lookup.requests == []
```

- [ ] **Step 2: Run tests and verify they fail for the missing helper**

Run:

```bash
uv run pytest tests/unit/test_publication_metadata_service.py -q
```

Expected: FAIL with an import error for `lookup_metadata_batched`.

- [ ] **Step 3: Implement the helper and moved protocol**

In `pubtator_link/services/publication_metadata.py`, update imports:

```python
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, Protocol
```

Add this block after the `CoverageProvider` alias:

```python
PUBLICATION_METADATA_BATCH_SIZE = 100


class PublicationMetadataLookup(Protocol):
    async def get_metadata(
        self,
        request: PublicationMetadataRequest,
    ) -> PublicationMetadataResponse:
        """Return publication metadata for PMIDs."""


async def lookup_metadata_batched(
    metadata_service: PublicationMetadataLookup,
    pmids: Sequence[str],
    *,
    include_mesh: bool = False,
    include_publication_types: bool = True,
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "none",
    include_coverage: bool = True,
    batch_size: int = PUBLICATION_METADATA_BATCH_SIZE,
) -> PublicationMetadataResponse:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    normalized_pmids = _normalize_metadata_batch_pmids(pmids)
    if not normalized_pmids:
        return _empty_metadata_batch_response()

    request_batch_size = min(batch_size, PUBLICATION_METADATA_BATCH_SIZE)
    metadata_by_pmid: dict[str, PublicationMetadata] = {}
    failed_pmids: dict[str, str] = {}
    warnings: list[str] = []
    warning_counts: Counter[str] = Counter()
    exception_types: list[str] = []
    source: str | None = None
    batch_count = 0
    failed_batch_count = 0

    for batch in _metadata_batches(normalized_pmids, request_batch_size):
        batch_count += 1
        try:
            response = await metadata_service.get_metadata(
                PublicationMetadataRequest(
                    pmids=list(batch),
                    include_mesh=include_mesh,
                    include_publication_types=include_publication_types,
                    include_citations=include_citations,
                    include_coverage=include_coverage,
                )
            )
        except Exception as exc:
            failed_batch_count += 1
            for pmid in batch:
                failed_pmids[pmid] = "batch_request_failed"
            _record_metadata_batch_warning(
                "pubmed_metadata_batch_failed",
                warnings,
                warning_counts,
            )
            exception_type = exc.__class__.__name__
            if exception_type not in exception_types:
                exception_types.append(exception_type)
            continue

        if source is None:
            response_source = response.meta.get("source")
            if isinstance(response_source, str) and response_source:
                source = response_source
        for metadata in response.metadata:
            metadata_by_pmid[metadata.pmid] = metadata
        failed_pmids.update(response.failed_pmids)
        for warning in _metadata_response_warnings(response):
            _record_metadata_batch_warning(warning, warnings, warning_counts)

    metadata_records = [
        metadata_by_pmid[pmid] for pmid in normalized_pmids if pmid in metadata_by_pmid
    ]
    meta: dict[str, Any] = {
        "next_commands": _next_commands(has_metadata=bool(metadata_records)),
        "batch_count": batch_count,
        "failed_batch_count": failed_batch_count,
    }
    if source is not None:
        meta["source"] = source
    if warnings:
        meta["warnings"] = warnings
        meta["warning_counts"] = dict(warning_counts)
    if exception_types:
        meta["batch_failure_exception_types"] = exception_types

    return PublicationMetadataResponse(
        success=True,
        metadata=metadata_records,
        failed_pmids=failed_pmids,
        _meta=meta,
    )


def _normalize_metadata_batch_pmids(pmids: Sequence[str]) -> list[str]:
    normalized_pmids: list[str] = []
    seen_pmids: set[str] = set()
    for pmid in pmids:
        clean_pmid = pmid.strip()
        if clean_pmid.upper().startswith("PMID:"):
            clean_pmid = clean_pmid[5:].strip()
        if not clean_pmid:
            continue
        if not clean_pmid.isdigit():
            raise ValueError("PMID must be numeric")
        if clean_pmid not in seen_pmids:
            normalized_pmids.append(clean_pmid)
            seen_pmids.add(clean_pmid)
    return normalized_pmids


def _metadata_batches(pmids: Sequence[str], size: int) -> list[list[str]]:
    return [list(pmids[index : index + size]) for index in range(0, len(pmids), size)]


def _empty_metadata_batch_response() -> PublicationMetadataResponse:
    return PublicationMetadataResponse(
        success=True,
        metadata=[],
        failed_pmids={},
        _meta={"next_commands": []},
    )


def _metadata_response_warnings(response: PublicationMetadataResponse) -> list[str]:
    raw_warnings = response.meta.get("warnings", [])
    if not isinstance(raw_warnings, list):
        return []
    return [warning for warning in raw_warnings if isinstance(warning, str) and warning]


def _record_metadata_batch_warning(
    warning: str,
    warnings: list[str],
    warning_counts: Counter[str],
) -> None:
    warning_counts[warning] += 1
    if warning not in warnings:
        warnings.append(warning)
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/test_publication_metadata_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the helper task**

Run:

```bash
git add pubtator_link/services/publication_metadata.py tests/unit/test_publication_metadata_service.py
git commit -m "feat: add internal metadata batching helper"
```

---

### Task 2: Review Index Metadata Uses Shared Helper

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing review index tests**

Add this test helper after `FakeMetadataService` in `tests/unit/test_review_context_service.py`:

```python
class RecordingMetadataService:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def get_metadata(self, request):
        self.requests.append(request)
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Citation title {pmid}",
                    journal="Citation journal",
                )
                for pmid in request.pmids
            ],
            _meta={"next_commands": []},
        )
```

Add these tests after `test_inspect_review_index_attaches_citation_metadata()`:

```python
@pytest.mark.asyncio
async def test_inspect_review_index_batches_metadata_for_pages_over_public_cap() -> None:
    repository = FakeReviewContextRepository([], preparation_status={"complete": 105})
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id=f"s{index}",
            pmid=str(100000 + index),
            source_kind="pubtator_abstract",
            job_status="complete",
        )
        for index in range(105)
    ]
    metadata_service = RecordingMetadataService()
    service = ReviewContextService(repository, metadata_service=metadata_service)

    response = await service.inspect_review_index(
        review_id="review-1",
        request=InspectReviewIndexRequest(include_metadata=True, metadata="basic"),
    )

    assert [len(request.pmids) for request in metadata_service.requests] == [100, 5]
    assert response.sources[0].citation_metadata is not None
    assert response.sources[0].citation_metadata.title == "Citation title 100000"
    assert response.sources[-1].citation_metadata is not None
    assert response.sources[-1].citation_metadata.title == "Citation title 100104"


@pytest.mark.asyncio
async def test_inspect_review_index_metadata_only_fetches_current_page() -> None:
    repository = FakeReviewContextRepository([], preparation_status={"complete": 120})
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id=f"s{index}",
            pmid=str(200000 + index),
            source_kind="pubtator_abstract",
            job_status="complete",
        )
        for index in range(120)
    ]
    metadata_service = RecordingMetadataService()
    service = ReviewContextService(repository, metadata_service=metadata_service)

    response = await service.inspect_review_index(
        review_id="review-1",
        request=InspectReviewIndexRequest(
            include_metadata=True,
            metadata="basic",
            limit=25,
        ),
    )

    assert response.page_source_count == 25
    assert [request.pmids for request in metadata_service.requests] == [
        [str(200000 + index) for index in range(25)]
    ]


@pytest.mark.asyncio
async def test_inspect_review_index_full_metadata_preserves_full_options() -> None:
    repository = FakeReviewContextRepository([], preparation_status={"complete": 1})
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id="s1",
            pmid="300001",
            source_kind="pubtator_abstract",
            job_status="complete",
        )
    ]
    metadata_service = RecordingMetadataService()
    service = ReviewContextService(repository, metadata_service=metadata_service)

    await service.inspect_review_index(
        review_id="review-1",
        request=InspectReviewIndexRequest(include_metadata=True, metadata="full"),
    )

    assert metadata_service.requests[0].include_mesh is True
    assert metadata_service.requests[0].include_publication_types is True
    assert metadata_service.requests[0].include_citations == "both"
    assert metadata_service.requests[0].include_coverage is True
```

- [ ] **Step 2: Run tests and verify the oversized page fails**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: FAIL in `test_inspect_review_index_batches_metadata_for_pages_over_public_cap` with a Pydantic validation error from constructing one oversized `PublicationMetadataRequest`.

- [ ] **Step 3: Move protocol import and use helper**

In `pubtator_link/services/review_context_service.py`, replace:

```python
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
```

with:

```python
from pubtator_link.services.publication_metadata import (
    PublicationMetadataLookup,
    lookup_metadata_batched,
)
```

Delete the local `PublicationMetadataLookup` class.

Replace `_attach_source_metadata()` with:

```python
    async def _attach_source_metadata(
        self,
        sources: list[ReviewSourceSummary],
        metadata_mode: str,
    ) -> None:
        pmids = list(dict.fromkeys(source.pmid for source in sources if source.pmid))
        metadata_service = self.metadata_service
        if not pmids or metadata_service is None:
            return
        response = await lookup_metadata_batched(
            metadata_service,
            pmids,
            include_mesh=metadata_mode == "full",
            include_publication_types=True,
            include_citations="both" if metadata_mode == "full" else "none",
            include_coverage=True,
        )
        metadata_by_pmid = {item.pmid: item for item in getattr(response, "metadata", [])}
        for source in sources:
            if source.pmid in metadata_by_pmid:
                source.citation_metadata = metadata_by_pmid[source.pmid]
```

- [ ] **Step 4: Run focused review tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the review index task**

Run:

```bash
git add pubtator_link/services/review_context_service.py tests/unit/test_review_context_service.py
git commit -m "feat: batch review index metadata lookups"
```

---

### Task 3: Related Evidence Uses Shared Helper

**Files:**
- Modify: `pubtator_link/services/related_evidence.py`
- Modify: `tests/unit/test_related_evidence_service.py`

- [ ] **Step 1: Write failing related evidence tests**

Add these helpers after `RecordingMetadata` in `tests/unit/test_related_evidence_service.py`:

```python
class RecordingRequestMetadata:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def get_metadata(self, request):
        self.requests.append(request)
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Resolved metadata {pmid}",
                    pub_year=2024,
                    coverage="abstract_only",
                )
                for pmid in request.pmids
            ],
            _meta={"next_commands": []},
        )


class PartialFailureMetadata:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def get_metadata(self, request):
        self.requests.append(request)
        if len(self.requests) == 3:
            raise RuntimeError("metadata unavailable")
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Resolved metadata {pmid}",
                    pub_year=2024,
                    coverage="abstract_only",
                )
                for pmid in request.pmids
            ],
            _meta={"next_commands": []},
        )
```

Add these tests after `test_related_evidence_batches_large_metadata_candidate_sets()`:

```python
@pytest.mark.asyncio
async def test_related_evidence_candidate_metadata_preserves_internal_options() -> None:
    metadata = RecordingRequestMetadata()
    service = RelatedEvidenceService(
        discovery_service=ManyCandidateDiscovery(),
        metadata_service=metadata,
        citation_graph_service=ManyCandidateCitationGraph(),
    )

    await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=25,
            include_citation_neighbors=True,
        )
    )

    candidate_requests = metadata.requests[1:]
    assert [len(request.pmids) for request in candidate_requests] == [100, 100, 10]
    assert all(request.include_mesh is False for request in candidate_requests)
    assert all(request.include_publication_types is True for request in candidate_requests)
    assert all(request.include_citations == "none" for request in candidate_requests)
    assert all(request.include_coverage is True for request in candidate_requests)


@pytest.mark.asyncio
async def test_related_evidence_partial_metadata_batch_failure_keeps_successful_candidates() -> None:
    metadata = PartialFailureMetadata()
    service = RelatedEvidenceService(
        discovery_service=ManyCandidateDiscovery(),
        metadata_service=metadata,
        citation_graph_service=ManyCandidateCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=25,
            include_citation_neighbors=True,
        )
    )

    assert [len(request.pmids) for request in metadata.requests] == [1, 100, 100, 10]
    assert response.candidates
    assert any(candidate.paper.title for candidate in response.candidates)
    assert any(
        warning.provider == "pubmed_metadata" and warning.status == "provider_failed"
        for warning in response.meta.warnings
    )
```

- [ ] **Step 2: Run tests and verify current local chunking behavior is insufficient**

Run:

```bash
uv run pytest tests/unit/test_related_evidence_service.py -q
```

Expected: FAIL in the new partial batch failure test because the current local chunking drops metadata from the raised chunk without receiving merged helper diagnostics.

- [ ] **Step 3: Replace local candidate chunking with helper**

In `pubtator_link/services/related_evidence.py`, keep the existing model import for `_source_paper()` and add:

```python
from pubtator_link.services.publication_metadata import lookup_metadata_batched
```

Replace the request loop inside `_metadata_candidates()` with:

```python
        warnings: list[ProviderWarning] = []
        metadata_by_pmid: dict[str, Any] = {}
        failed_pmids: dict[str, Any] = {}
        try:
            metadata_response = await lookup_metadata_batched(
                self.metadata_service,
                pmids,
                include_mesh=False,
                include_publication_types=True,
                include_citations="none",
                include_coverage=True,
            )
        except Exception as exc:
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))
            metadata_response = None

        if metadata_response is not None:
            metadata_by_pmid.update(
                {metadata.pmid: metadata for metadata in metadata_response.metadata}
            )
            failed_pmids.update(getattr(metadata_response, "failed_pmids", {}))
            warnings.extend(_metadata_response_provider_warnings(metadata_response))
```

Add this helper near `_provider_failed_warning()`:

```python
def _metadata_response_provider_warnings(metadata_response: Any) -> list[ProviderWarning]:
    warning_values = getattr(metadata_response, "meta", {}).get("warnings", [])
    if not isinstance(warning_values, list):
        return []
    return [
        ProviderWarning(
            provider="pubmed_metadata",
            status="provider_failed",
            retryable=True,
            message=f"PubMed metadata warning: {warning}",
        )
        for warning in warning_values
        if isinstance(warning, str) and warning
    ]
```

Remove `_chunks()` from `pubtator_link/services/related_evidence.py` if no remaining references exist.

- [ ] **Step 4: Run focused related evidence tests**

Run:

```bash
uv run pytest tests/unit/test_related_evidence_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the related evidence task**

Run:

```bash
git add pubtator_link/services/related_evidence.py tests/unit/test_related_evidence_service.py
git commit -m "feat: batch related evidence metadata lookups"
```

---

### Task 4: Topic Map Metadata Uses Shared Helper

**Files:**
- Modify: `pubtator_link/services/topic_literature_map.py`
- Modify: `tests/unit/test_topic_literature_map_service.py`

- [ ] **Step 1: Write failing topic map tests**

Add these helpers after `FakeMetadata` in `tests/unit/test_topic_literature_map_service.py`:

```python
class RecordingTopicMetadata:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def get_metadata(self, request: object) -> PublicationMetadataResponse:
        self.requests.append(request)
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Paper {pmid}",
                    journal="Journal",
                    pub_year=2024,
                    mesh_headings=["Familial Mediterranean Fever"],
                )
                for pmid in request.pmids
            ],
            _meta={"next_commands": []},
        )


class PartialFailureTopicMetadata:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def get_metadata(self, request: object) -> PublicationMetadataResponse:
        self.requests.append(request)
        if len(self.requests) == 2:
            raise RuntimeError("metadata unavailable")
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title=f"Paper {pmid}",
                    journal="Journal",
                    pub_year=2024,
                    mesh_headings=["Familial Mediterranean Fever"],
                )
                for pmid in request.pmids
            ],
            _meta={"next_commands": []},
        )
```

Add these tests after `test_build_map_enforces_total_neighbor_bound_and_prefers_metadata()`:

```python
@pytest.mark.asyncio
async def test_topic_metadata_papers_batches_more_than_public_cap() -> None:
    metadata = RecordingTopicMetadata()
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=metadata,
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )
    warnings = []
    pmids = [str(300000 + index) for index in range(105)]

    papers, entities = await service._metadata_papers(
        pmids,
        include_entities=True,
        warnings=warnings,
    )

    assert [len(request.pmids) for request in metadata.requests] == [100, 5]
    assert all(request.include_mesh is True for request in metadata.requests)
    assert all(request.include_publication_types is True for request in metadata.requests)
    assert all(request.include_citations == "none" for request in metadata.requests)
    assert all(request.include_coverage is True for request in metadata.requests)
    assert set(papers) == set(pmids)
    assert set(entities) == set(pmids)
    assert warnings == []


@pytest.mark.asyncio
async def test_topic_metadata_papers_partial_batch_failure_preserves_successful_metadata() -> None:
    metadata = PartialFailureTopicMetadata()
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=metadata,
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )
    warnings = []
    pmids = [str(400000 + index) for index in range(105)]

    papers, entities = await service._metadata_papers(
        pmids,
        include_entities=True,
        warnings=warnings,
    )

    assert [len(request.pmids) for request in metadata.requests] == [100, 5]
    assert set(papers) == set(pmids[:100])
    assert set(entities) == set(pmids[:100])
    assert any(
        warning.provider == "pubmed_metadata" and warning.status == "provider_failed"
        for warning in warnings
    )
```

- [ ] **Step 2: Run tests and verify direct oversized request fails**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py -q
```

Expected: FAIL in `test_topic_metadata_papers_batches_more_than_public_cap` with a Pydantic validation error from constructing one oversized `PublicationMetadataRequest`.

- [ ] **Step 3: Update topic map metadata lookup**

In `pubtator_link/services/topic_literature_map.py`, replace:

```python
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
```

with:

```python
from pubtator_link.services.publication_metadata import lookup_metadata_batched
```

Replace the direct request in `_metadata_papers()` with:

```python
        try:
            response = await lookup_metadata_batched(
                self.metadata_service,
                pmids,
                include_mesh=include_entities,
                include_publication_types=True,
                include_citations="none",
                include_coverage=True,
            )
        except Exception as exc:
            warnings.append(_provider_failed_warning("pubmed_metadata", exc))
            return {}, {}
        warnings.extend(_metadata_response_provider_warnings(response))
```

Add this helper near `_provider_failed_warning()`:

```python
def _metadata_response_provider_warnings(metadata_response: Any) -> list[ProviderWarning]:
    warning_values = getattr(metadata_response, "meta", {}).get("warnings", [])
    if not isinstance(warning_values, list):
        warning_values = []
    provider_warnings = [
        ProviderWarning(
            provider="pubmed_metadata",
            status="provider_failed",
            retryable=True,
            message=f"PubMed metadata warning: {warning}",
        )
        for warning in warning_values
        if isinstance(warning, str) and warning
    ]
    failed_pmids = getattr(metadata_response, "failed_pmids", {})
    if failed_pmids:
        provider_warnings.append(
            ProviderWarning(
                provider="pubmed_metadata",
                status="provider_failed",
                retryable=True,
                message=f"Metadata lookup failed for {len(failed_pmids)} PMID(s).",
            )
        )
    return provider_warnings
```

- [ ] **Step 4: Run focused topic map tests**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the topic map task**

Run:

```bash
git add pubtator_link/services/topic_literature_map.py tests/unit/test_topic_literature_map_service.py
git commit -m "feat: batch topic map metadata lookups"
```

---

### Task 5: MCP Search Metadata Batches When `limit=None`

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing MCP search test**

Add this test after `test_search_literature_metadata_respects_limit()` in `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_search_literature_metadata_batches_limit_none_over_public_cap() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.models.publication_metadata import (
        PublicationMetadata,
        PublicationMetadataResponse,
    )

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [
                    {"pmid": str(500000 + index), "title": f"Result {index}"}
                    for index in range(105)
                ],
                "count": 105,
                "total_pages": 1,
                "page_size": 105,
            }

    class RecordingMetadata:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def get_metadata(self, request):
            self.requests.append(request)
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid=pmid,
                        title=f"Metadata {pmid}",
                    )
                    for pmid in request.pmids
                ],
                _meta={"next_commands": []},
            )

    metadata = RecordingMetadata()
    result = await search_literature_impl(
        client=FakeClient(),
        text="MEFV",
        limit=None,
        metadata="basic",
        metadata_service=metadata,
    )

    assert result["success"] is True
    assert len(result["results"]) == 105
    assert [len(request.pmids) for request in metadata.requests] == [100, 5]
    assert all(request.include_mesh is False for request in metadata.requests)
    assert all(request.include_citations == "none" for request in metadata.requests)
    assert all(request.include_coverage is False for request in metadata.requests)
```

- [ ] **Step 2: Run MCP adapter tests and verify current direct request fails**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: FAIL in `test_search_literature_metadata_batches_limit_none_over_public_cap` with a Pydantic validation error from one oversized `PublicationMetadataRequest`.

- [ ] **Step 3: Use helper in MCP search metadata enrichment**

In `pubtator_link/mcp/service_adapters.py`, add this import near the existing `PublicationMetadataService` import:

```python
from pubtator_link.services.publication_metadata import (
    PublicationMetadataService,
    lookup_metadata_batched,
)
```

Remove the old single-name import of `PublicationMetadataService`.

Replace the request in `_search_metadata_by_pmid()` with:

```python
    response = await lookup_metadata_batched(
        metadata_service,
        pmids,
        include_mesh=metadata == "full",
        include_publication_types=True,
        include_citations=include_metadata_citations if metadata == "full" else "none",
        include_coverage=False,
    )
```

Keep `get_publication_metadata_impl()` unchanged so direct public MCP metadata requests still construct `PublicationMetadataRequest`.

- [ ] **Step 4: Run focused MCP search tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_search_literature_metadata_batches_limit_none_over_public_cap tests/unit/mcp/test_mcp_service_adapters.py::test_search_literature_impl_enriches_basic_metadata tests/unit/mcp/test_mcp_service_adapters.py::test_search_literature_full_metadata_requests_citations -q
```

Expected: PASS.

- [ ] **Step 5: Commit the MCP search task**

Run:

```bash
git add pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: batch MCP search metadata lookups"
```

---

### Task 6: Public Cap and Compatibility Tests

**Files:**
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `tests/unit/test_citation_graph_service.py`
- Verify existing: `tests/unit/test_publication_metadata_models.py`
- Verify existing: `tests/test_routes/test_search.py`

- [ ] **Step 1: Write public MCP cap test**

Add this test after `test_get_publication_metadata_impl_returns_typed_payload()` in `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_get_publication_metadata_impl_preserves_public_100_pmid_cap() -> None:
    from pydantic import ValidationError

    from pubtator_link.mcp import service_adapters

    class UnexpectedService:
        async def get_metadata(self, request):
            raise AssertionError("oversized public metadata request should fail validation first")

    with pytest.raises(ValidationError):
        await service_adapters.get_publication_metadata_impl(
            service=UnexpectedService(),
            pmids=[str(600000 + index) for index in range(101)],
            include_mesh=True,
            include_publication_types=True,
            include_citations="both",
            include_coverage=True,
        )
```

- [ ] **Step 2: Write citation graph compatibility test without changing production code**

Add this test after `class RecordingMetadata` in `tests/unit/test_citation_graph_service.py`:

```python
@pytest.mark.asyncio
async def test_citation_graph_metadata_resolution_remains_single_pmid_public_request() -> None:
    from pubtator_link.models.publication_metadata import PublicationMetadata

    class SinglePmidMetadata:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def get_metadata(self, request):
            self.requests.append(request)
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid="28386255",
                        title="Familial Mediterranean Fever",
                    )
                ],
                failed_pmids={},
            )

    metadata = SinglePmidMetadata()
    service = CitationGraphService(metadata_service=metadata)

    result = await service._metadata_for_pmid("28386255")

    assert result is not None
    assert result.pmid == "28386255"
    assert len(metadata.requests) == 1
    assert metadata.requests[0].pmids == ["28386255"]
    assert metadata.requests[0].include_mesh is False
    assert metadata.requests[0].include_citations == "none"
    assert metadata.requests[0].include_coverage is True
```

- [ ] **Step 3: Run compatibility tests**

Run:

```bash
uv run pytest tests/unit/test_publication_metadata_models.py::test_publication_metadata_request_rejects_too_many_pmids tests/unit/mcp/test_mcp_service_adapters.py::test_get_publication_metadata_impl_preserves_public_100_pmid_cap tests/unit/test_citation_graph_service.py::test_citation_graph_metadata_resolution_remains_single_pmid_public_request tests/test_routes/test_search.py::TestSearchRoutes::test_search_publications_can_enrich_basic_metadata -q
```

Expected: PASS.

- [ ] **Step 4: Run Ruff safe fixes and inspect the resulting diff**

Run:

```bash
make lint-fix
```

Expected: PASS or Ruff applies only import cleanup and safe fixes.

- [ ] **Step 5: Commit compatibility tests**

Run:

```bash
git add tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_citation_graph_service.py
git commit -m "test: preserve public metadata cap compatibility"
```

---

### Task 7: Final Focused Verification

**Files:**
- Verify all modified source and test files.

- [ ] **Step 1: Run focused unit tests for changed service areas**

Run:

```bash
uv run pytest tests/unit/test_publication_metadata_service.py tests/unit/test_review_context_service.py tests/unit/test_related_evidence_service.py tests/unit/test_topic_literature_map_service.py tests/unit/test_citation_graph_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused MCP and route tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_search.py::TestSearchRoutes::test_search_publications_can_enrich_basic_metadata -q
```

Expected: PASS.

- [ ] **Step 3: Run type checking**

Run:

```bash
make typecheck-fast
```

Expected: PASS.

- [ ] **Step 4: Run final local CI**

Run:

```bash
make ci-local
```

Expected: PASS.

---

## Scope Guardrails

- Do not raise `PublicationMetadataRequest.pmids` above `max_length=100`.
- Do not add public API fields for batched metadata lookup.
- Do not add concurrency, retries, caching, or rate-limit orchestration.
- Do not modify production code in `pubtator_link/services/citation_graph.py` for this sprint.
- Do not add reference or cited-by metadata enrichment to citation graph.
- Keep REST search direct because route `limit` remains capped at 50 before metadata enrichment.
- Keep public MCP `get_publication_metadata_impl()` direct because it is the public metadata request surface.

## Self-Review

- Spec coverage:
  - Shared module-level `lookup_metadata_batched()` helper: Task 1.
  - `PublicationMetadataLookup` protocol move: Task 1 and Task 2.
  - Public 100-PMID cap preservation: Task 6 and existing model test.
  - First-seen order and deduplication: Task 1.
  - Public-sized chunks and merged partial results: Task 1.
  - Failed batch handling with diagnostics and sanitized exception types: Task 1.
  - Review index metadata over 100 current-page sources: Task 2.
  - Related evidence local chunking replacement: Task 3.
  - Topic map metadata batching and partial failures: Task 4.
  - MCP search `limit=None` batching: Task 5.
  - REST and MCP compatibility: Task 6 and Task 7.
  - Citation graph production code out of scope: File Structure, Task 6, and Scope Guardrails.

- Marker scan:
  - No deferred implementation notes.
  - Each task names exact files, tests, commands, expected outcomes, and concrete code snippets.
  - Final verification ends with `make ci-local`.

- Type consistency:
  - `PublicationMetadataLookup.get_metadata()` accepts `PublicationMetadataRequest` and returns `PublicationMetadataResponse`.
  - `lookup_metadata_batched()` accepts `Sequence[str]`, builds `list[str]` chunks, and returns `PublicationMetadataResponse`.
  - `include_citations` consistently uses `Literal["none", "nlm", "bibtex", "both"]`.
  - Helper defaults are internal cheap defaults: `include_mesh=False`, `include_citations="none"`, `include_coverage=True`.
  - MCP search passes `include_coverage=False` to preserve existing search enrichment behavior.
