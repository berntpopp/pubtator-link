import pytest

from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.models.review_rerag import PreparationStatus, SourceCoverageHint
from pubtator_link.services.research_session import ResearchSessionService


class FakeRepository:
    def __init__(self) -> None:
        self.sessions = {}
        self.candidates = []
        self.return_none = False

    async def upsert_research_session(
        self,
        *,
        review_id,
        session_id,
        query,
        status,
        request,
    ):
        key = (review_id, session_id)
        kwargs = {
            "review_id": review_id,
            "session_id": session_id,
            "query": query,
            "status": status,
            "request": request,
        }
        current = self.sessions.get(key, {})
        self.sessions[key] = {**current, **kwargs}

    async def upsert_research_session_candidate(self, **kwargs):
        self.candidates.append(kwargs["candidate"])

    async def get_research_session(self, review_id, session_id):
        from pubtator_link.models.review_rerag import ResearchSessionManifest

        if self.return_none:
            return None
        session = self.sessions[(review_id, session_id)]
        return ResearchSessionManifest(
            review_id=review_id,
            session_id=session_id,
            query=session.get("query"),
            status=session.get("status", "active"),
            candidates=self.candidates,
            candidate_count=len(self.candidates),
            queued_count=sum(1 for item in self.candidates if item.status == "queued"),
            skipped_count=sum(1 for item in self.candidates if item.status == "skipped"),
        )

    async def list_research_sessions(self, review_id):
        manifests = []
        for session_review_id, session_id in self.sessions:
            if session_review_id == review_id:
                manifests.append(await self.get_research_session(review_id, session_id))
        return manifests


class FakeSearch:
    async def search(self, request):
        return SearchResponse(
            success=True,
            query=request.query or "",
            results=[
                SearchResult(pmid="1", title="first"),
                SearchResult(pmid="2", title="second"),
            ],
            total_results=2,
            page=1,
            per_page=20,
            total_pages=1,
        )


class FakePreflight:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def preflight_pmids(self, pmids):
        if self.fail:
            raise RuntimeError("preflight unavailable")
        return [
            SourceCoverageHint(
                pmid=pmid,
                expected_coverage="full_text" if pmid == "1" else "abstract_only",
                coverage_reason="full_text_available" if pmid == "1" else "no_pmcid",
            )
            for pmid in pmids
        ]


class FakeQueue:
    def __init__(
        self, *, fail_on: str | None = None, accepted_pmids: set[str] | None = None
    ) -> None:
        self.fail_on = fail_on
        self.accepted_pmids = accepted_pmids or {"1"}

    class Repository:
        async def preparation_status(self, review_id):
            return PreparationStatus(queued=1)

    repository = Repository()

    async def enqueue_pmid(self, review_id, pmid):
        if pmid == self.fail_on:
            raise RuntimeError(f"queue unavailable for {pmid}")
        return pmid in self.accepted_pmids


async def test_stage_session_searches_preflights_and_queues_candidates() -> None:
    repository = FakeRepository()
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(),
        queue=FakeQueue(),
    )

    response = await service.stage(
        review_id="review-1",
        request={"query": "FMF", "max_candidates": 2, "stage_full_text": True},
    )

    assert response.manifest.review_id == "review-1"
    assert response.manifest.candidate_count == 2
    assert response.manifest.queued_count == 1
    assert response.manifest.candidates[0].status == "queued"
    assert response.manifest.candidates[1].status == "skipped"
    assert response.manifest.candidates[1].decision_reason == "queue_rejected"


async def test_stage_preserves_explicit_pmid_order_and_reason() -> None:
    repository = FakeRepository()
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(),
        queue=FakeQueue(accepted_pmids={"1", "2"}),
    )

    response = await service.stage(
        review_id="review-1",
        request={"pmids": ["2", "1", "2"], "query": "FMF", "max_candidates": 3},
    )

    assert [candidate.pmid for candidate in response.manifest.candidates] == ["2", "1"]
    assert [candidate.decision_reason for candidate in response.manifest.candidates] == [
        "explicit_pmid",
        "explicit_pmid",
    ]


async def test_stage_without_full_text_records_metadata_only_skips() -> None:
    repository = FakeRepository()
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(),
        queue=FakeQueue(),
    )

    response = await service.stage(
        review_id="review-1",
        request={"query": "FMF", "max_candidates": 2, "stage_full_text": False},
    )

    assert [candidate.status for candidate in response.manifest.candidates] == [
        "skipped",
        "skipped",
    ]
    assert [candidate.decision_reason for candidate in response.manifest.candidates] == [
        "metadata_only",
        "metadata_only",
    ]


async def test_stage_preflight_failure_marks_session_failed_and_raises() -> None:
    repository = FakeRepository()
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(fail=True),
        queue=FakeQueue(),
    )

    with pytest.raises(RuntimeError, match="preflight failed"):
        await service.stage(
            review_id="review-1",
            request={"query": "FMF", "session_id": "session-1"},
        )

    assert repository.sessions[("review-1", "session-1")]["status"] == "failed"
    assert repository.candidates == []


async def test_stage_queue_failure_marks_partial_and_records_candidate_error() -> None:
    repository = FakeRepository()
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(),
        queue=FakeQueue(fail_on="2"),
    )

    with pytest.raises(RuntimeError, match="queue failed"):
        await service.stage(
            review_id="review-1",
            request={"query": "FMF", "session_id": "session-1", "max_candidates": 2},
        )

    assert repository.sessions[("review-1", "session-1")]["status"] == "partial"
    assert repository.candidates[0].status == "queued"
    assert repository.candidates[1].status == "failed"
    assert repository.candidates[1].decision_reason == "queue_rejected"
    assert repository.candidates[1].error == "queue unavailable for 2"


async def test_stage_missing_manifest_raises_clear_service_error() -> None:
    repository = FakeRepository()
    repository.return_none = True
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(),
        queue=FakeQueue(),
    )

    with pytest.raises(RuntimeError, match="Research session manifest was not found"):
        await service.stage(
            review_id="review-1",
            request={"query": "FMF", "session_id": "session-1"},
        )


async def test_list_sessions_attaches_preparation_status() -> None:
    repository = FakeRepository()
    await repository.upsert_research_session(
        review_id="review-1",
        session_id="session-1",
        query="FMF",
        status="active",
        request={"query": "FMF"},
    )
    service = ResearchSessionService(
        repository=repository,
        search_provider=FakeSearch(),
        preflight_service=FakePreflight(),
        queue=FakeQueue(),
    )

    response = await service.list_sessions(review_id="review-1")

    assert response.sessions[0].preparation_status == PreparationStatus(queued=1)
