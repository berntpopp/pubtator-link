from __future__ import annotations

import pytest

from pubtator_link.models.review_rerag import IndexReviewEvidenceRequest, PreparationStatus
from pubtator_link.services.review_indexing import ReviewIndexingService


class FakeIndexRepository:
    def __init__(
        self,
        existing: dict[str, str] | None = None,
        session_exists: bool = True,
        terminal_after_first_poll: bool = True,
    ) -> None:
        self.existing = existing or {}
        self.session_exists = session_exists
        self.terminal_after_first_poll = terminal_after_first_poll
        self.linked: list[tuple[str, str, str]] = []
        self.status_calls = 0

    async def research_session_exists(self, review_id: str, session_id: str) -> bool:
        return self.session_exists

    async def preparation_job_statuses(
        self, review_id: str, source_ids: list[str]
    ) -> dict[str, str]:
        return {
            source_id: self.existing[source_id]
            for source_id in source_ids
            if source_id in self.existing
        }

    async def preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> PreparationStatus:
        self.status_calls += 1
        if self.terminal_after_first_poll and self.status_calls > 1:
            return PreparationStatus(complete=1)
        return PreparationStatus(queued=1)

    async def link_review_session_source(
        self, review_id: str, session_id: str, source_id: str
    ) -> None:
        self.linked.append((review_id, session_id, source_id))


class FakeQueue:
    def __init__(self, result: str = "newly_queued") -> None:
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    async def enqueue_pmid(self, review_id: str, pmid: str) -> str:
        self.calls.append(("pmid", review_id, pmid))
        return self.result

    async def enqueue_curated_url(self, review_id: str, url: str) -> str:
        self.calls.append(("url", review_id, url))
        return self.result


@pytest.mark.asyncio
async def test_dry_run_reports_counts_without_enqueueing() -> None:
    repository = FakeIndexRepository(existing={"PMID:1": "complete"})
    queue = FakeQueue()
    service = ReviewIndexingService(repository=repository, queue=queue)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1", "2"], dry_run=True),
    )

    assert response.dry_run is True
    assert response.already_indexed == 1
    assert response.estimated_source_count == 2
    assert queue.calls == []


@pytest.mark.asyncio
async def test_index_includes_source_coverage_summary_before_enqueue() -> None:
    class Repository(FakeIndexRepository):
        def __init__(self) -> None:
            super().__init__()
            self.coverage_source_ids: list[str] = []

        async def source_coverage_summary(self, review_id, source_ids):
            self.coverage_source_ids = source_ids
            return {
                "total_sources": 2,
                "full_text": 1,
                "abstract_only": 1,
                "title_only": 0,
                "failed": 0,
            }

    repository = Repository()
    service = ReviewIndexingService(repository=repository, queue=FakeQueue())

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1", "2"], dry_run=True),
    )

    assert repository.coverage_source_ids == ["PMID:1", "PMID:2"]
    assert response.source_preflight_summary["total_sources"] == 2
    assert "abstract_only" in response.source_preflight_message


@pytest.mark.asyncio
async def test_index_continues_when_source_coverage_summary_raises() -> None:
    class Repository(FakeIndexRepository):
        async def source_coverage_summary(self, review_id, source_ids):
            raise RuntimeError("coverage store unavailable")

    queue = FakeQueue()
    service = ReviewIndexingService(repository=Repository(), queue=queue)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1"], dry_run=False),
    )

    assert queue.calls == [("pmid", "review-1", "1")]
    assert response.queued == 1
    assert response.source_preflight_summary == {}
    assert any(
        "source_coverage_summary_unavailable" in warning
        for warning in response.source_preflight_warnings
    )


@pytest.mark.asyncio
async def test_index_continues_when_source_coverage_summary_is_malformed() -> None:
    class Repository(FakeIndexRepository):
        async def source_coverage_summary(self, review_id, source_ids):
            return {"total_sources": "unknown", "full_text": None}

    queue = FakeQueue()
    service = ReviewIndexingService(repository=Repository(), queue=queue)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1"], dry_run=False),
    )

    assert queue.calls == [("pmid", "review-1", "1")]
    assert response.queued == 1
    assert response.source_preflight_summary == {}
    assert any(
        "source_coverage_summary_unavailable" in warning
        for warning in response.source_preflight_warnings
    )


@pytest.mark.asyncio
async def test_wait_for_terminal_times_out_with_retry_after() -> None:
    repository = FakeIndexRepository(
        existing={"PMID:1": "queued"},
        terminal_after_first_poll=False,
    )
    queue = FakeQueue(result="already_queued")
    service = ReviewIndexingService(repository=repository, queue=queue, poll_interval_ms=10)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1"], wait_for_status="terminal", timeout_ms=1),
    )

    assert response.timed_out is True
    assert response.retry_after_ms is not None


@pytest.mark.asyncio
async def test_wait_for_completion_uses_default_timeout_when_timeout_omitted() -> None:
    repository = FakeIndexRepository(existing={"PMID:1": "queued"})
    queue = FakeQueue(result="already_queued")
    service = ReviewIndexingService(repository=repository, queue=queue, poll_interval_ms=1)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1"], wait_for_completion=True, timeout_ms=0),
    )

    assert repository.status_calls == 2
    assert response.preparation_status.complete == 1
    assert response.timed_out is False


@pytest.mark.asyncio
async def test_index_links_sources_to_session() -> None:
    repository = FakeIndexRepository()
    queue = FakeQueue()
    service = ReviewIndexingService(repository=repository, queue=queue)

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1"], session_id="session-1"),
    )

    assert response.newly_queued == 1
    assert repository.linked == [("review-1", "session-1", "PMID:1")]


@pytest.mark.asyncio
async def test_index_rejects_bookshelf_url_before_enqueue() -> None:
    service = ReviewIndexingService(repository=FakeIndexRepository(), queue=FakeQueue())

    with pytest.raises(ValueError, match="bookshelf_url_not_indexable"):
        await service.index_review_evidence(
            "review-1",
            IndexReviewEvidenceRequest(
                curated_urls=["https://www.ncbi.nlm.nih.gov/books/NBK1139/"]
            ),
        )


@pytest.mark.asyncio
async def test_index_rejects_bookshelf_url_without_nbk_before_enqueue() -> None:
    queue = FakeQueue()
    service = ReviewIndexingService(repository=FakeIndexRepository(), queue=queue)

    with pytest.raises(ValueError, match="bookshelf_url_not_indexable"):
        await service.index_review_evidence(
            "review-1",
            IndexReviewEvidenceRequest(curated_urls=["https://www.ncbi.nlm.nih.gov/books/"]),
        )

    assert queue.calls == []


@pytest.mark.asyncio
async def test_index_rejects_unknown_session() -> None:
    service = ReviewIndexingService(
        repository=FakeIndexRepository(session_exists=False),
        queue=FakeQueue(),
    )

    with pytest.raises(ValueError, match="session_not_found"):
        await service.index_review_evidence(
            "review-1",
            IndexReviewEvidenceRequest(pmids=["1"], session_id="missing"),
        )
