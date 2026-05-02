from pubtator_link.models.responses import SearchResponse, SearchResult
from pubtator_link.models.review_rerag import PreparationStatus, SourceCoverageHint
from pubtator_link.services.research_session import ResearchSessionService


class FakeRepository:
    def __init__(self) -> None:
        self.sessions = {}
        self.candidates = []

    async def upsert_research_session(self, **kwargs):
        self.sessions[(kwargs["review_id"], kwargs["session_id"])] = kwargs

    async def upsert_research_session_candidate(self, **kwargs):
        self.candidates.append(kwargs["candidate"])

    async def get_research_session(self, review_id, session_id):
        from pubtator_link.models.review_rerag import ResearchSessionManifest

        return ResearchSessionManifest(
            review_id=review_id,
            session_id=session_id,
            candidates=self.candidates,
            candidate_count=len(self.candidates),
            queued_count=sum(1 for item in self.candidates if item.status == "queued"),
            skipped_count=sum(1 for item in self.candidates if item.status == "skipped"),
        )


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
    async def preflight_pmids(self, pmids):
        return [
            SourceCoverageHint(
                pmid=pmid,
                expected_coverage="full_text" if pmid == "1" else "abstract_only",
                coverage_reason="full_text_available" if pmid == "1" else "no_pmcid",
            )
            for pmid in pmids
        ]


class FakeQueue:
    class Repository:
        async def preparation_status(self, review_id):
            return PreparationStatus(queued=1)

    repository = Repository()

    async def enqueue_pmid(self, review_id, pmid):
        return pmid == "1"


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
