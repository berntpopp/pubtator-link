import asyncio
from collections.abc import Sequence

import pytest

from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    InspectReviewIndexRequest,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewPassageSample,
    ReviewSourceSummary,
)
from pubtator_link.services.review_context_service import ReviewContextService


class FakeReviewContextRepository:
    def __init__(
        self,
        passages: list[ReviewPassageRow],
        preparation_status: dict[str, int] | None = None,
    ) -> None:
        self.passages = passages
        self.preparation_status_value = preparation_status or {"complete": 1}
        self.search_calls: list[dict[str, object]] = []
        self.source_summaries: list[ReviewSourceSummary] = []
        self.source_coverages: dict[str, str] = {}
        self.failed_source_summaries: list[FailedSourceSummary] = []
        self.index_totals = ReviewIndexTotals()
        self.inspect_calls: list[dict[str, object]] = []
        self.available_sections_value: list[str] = []
        self.indexed_pmids_value: list[str] = []
        self.session_exists = True

    async def research_session_exists(self, review_id: str, session_id: str) -> bool:
        return self.session_exists

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        session_id: str | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        self.search_calls.append(
            {
                "review_id": review_id,
                "query": query,
                "entity_ids": entity_ids,
                "pmids": pmids,
                "sections": sections,
                "session_id": session_id,
                "limit": limit,
            }
        )
        return self.passages

    async def preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> dict[str, int]:
        return self.preparation_status_value

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
        min_sample_chars: int = 80,
        sample_section_policy: str = "evidence_first",
        session_id: str | None = None,
    ) -> list[ReviewSourceSummary]:
        self.inspect_calls.append(
            {
                "method": "list_review_sources",
                "review_id": review_id,
                "pmids": pmids,
                "include_passage_samples": include_passage_samples,
                "sample_per_pmid": sample_per_pmid,
                "min_sample_chars": min_sample_chars,
                "sample_section_policy": sample_section_policy,
                "session_id": session_id,
            }
        )
        if self.source_summaries:
            if pmids:
                pmid_set = set(pmids)
                return [summary for summary in self.source_summaries if summary.pmid in pmid_set]
            return self.source_summaries
        seen_pmids = list(dict.fromkeys(row.pmid for row in self.passages if row.pmid is not None))
        if pmids:
            pmid_set = set(pmids)
            seen_pmids = [pmid for pmid in seen_pmids if pmid in pmid_set]
        return [
            ReviewSourceSummary(
                source_id=f"source-{pmid}",
                pmid=pmid,
                source_kind="pubtator_full_bioc",
                job_status="complete",
                coverage=self.source_coverages.get(pmid, "unknown"),
            )
            for pmid in seen_pmids
        ]

    async def list_review_failed_sources(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[FailedSourceSummary]:
        self.inspect_calls.append(
            {
                "method": "list_review_failed_sources",
                "review_id": review_id,
                "session_id": session_id,
            }
        )
        return self.failed_source_summaries

    async def review_index_totals(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewIndexTotals:
        self.inspect_calls.append(
            {"method": "review_index_totals", "review_id": review_id, "session_id": session_id}
        )
        return self.index_totals

    async def available_sections(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        return self.available_sections_value

    async def indexed_pmids(self, review_id: str, *, session_id: str | None = None) -> list[str]:
        return self.indexed_pmids_value

    async def get_passages_by_id(
        self,
        review_id: str,
        passage_ids: Sequence[str],
        *,
        session_id: str | None = None,
    ) -> list[ReviewPassageRow]:
        by_id = {passage.passage_id: passage for passage in self.passages}
        return [by_id[passage_id] for passage_id in passage_ids if passage_id in by_id]

    async def neighboring_passages(
        self,
        review_id: str,
        passage_id: str,
        before: int,
        after: int,
        same_section: bool,
        *,
        session_id: str | None = None,
    ) -> list[ReviewPassageRow]:
        by_id = {passage.passage_id: passage for passage in self.passages}
        anchor = by_id.get(passage_id)
        if anchor is None:
            return []
        candidates = [
            passage
            for passage in self.passages
            if passage.source_id == anchor.source_id
            and (not same_section or passage.section == anchor.section)
        ]
        anchor_index = next(
            index for index, passage in enumerate(candidates) if passage.passage_id == passage_id
        )
        start = max(0, anchor_index - before)
        stop = anchor_index + after + 1
        return candidates[start:stop]


class FakeMetadataService:
    def __init__(self) -> None:
        self.requests = []

    async def get_metadata(self, request):
        self.requests.append(request)
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid="111",
                    title="Citation title",
                    journal="Citation journal",
                )
            ],
            _meta={"next_commands": []},
        )


class QueryMappedReviewContextRepository(FakeReviewContextRepository):
    def __init__(self, passages_by_query: dict[str, list[ReviewPassageRow]]) -> None:
        super().__init__([])
        self.passages_by_query = passages_by_query

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        session_id: str | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        self.search_calls.append(
            {
                "review_id": review_id,
                "query": query,
                "entity_ids": entity_ids,
                "pmids": pmids,
                "sections": sections,
                "session_id": session_id,
                "limit": limit,
            }
        )
        return self.passages_by_query[query]

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
        min_sample_chars: int = 80,
        sample_section_policy: str = "evidence_first",
        session_id: str | None = None,
    ) -> list[ReviewSourceSummary]:
        self.inspect_calls.append(
            {
                "method": "list_review_sources",
                "review_id": review_id,
                "pmids": pmids,
                "include_passage_samples": include_passage_samples,
                "sample_per_pmid": sample_per_pmid,
                "min_sample_chars": min_sample_chars,
                "sample_section_policy": sample_section_policy,
                "session_id": session_id,
            }
        )
        if self.source_summaries:
            if pmids:
                pmid_set = set(pmids)
                return [summary for summary in self.source_summaries if summary.pmid in pmid_set]
            return self.source_summaries
        seen_pmids = list(
            dict.fromkeys(
                row.pmid
                for passages in self.passages_by_query.values()
                for row in passages
                if row.pmid is not None
            )
        )
        if pmids:
            pmid_set = set(pmids)
            seen_pmids = [pmid for pmid in seen_pmids if pmid in pmid_set]
        return [
            ReviewSourceSummary(
                source_id=f"source-{pmid}",
                pmid=pmid,
                source_kind="pubtator_full_bioc",
                job_status="complete",
                coverage=self.source_coverages.get(pmid, "unknown"),
            )
            for pmid in seen_pmids
        ]


class BlockingQueryRepository(QueryMappedReviewContextRepository):
    def __init__(self, passages_by_query: dict[str, list[ReviewPassageRow]]) -> None:
        super().__init__(passages_by_query)
        self.started_queries: list[str] = []
        self.three_started = asyncio.Event()
        self.release = asyncio.Event()

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        session_id: str | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        self.started_queries.append(query)
        if len(self.started_queries) >= 3:
            self.three_started.set()
        await self.release.wait()
        return await super().search_passages(
            review_id,
            query,
            entity_ids=entity_ids,
            pmids=pmids,
            sections=sections,
            session_id=session_id,
            limit=limit,
        )


class CoroutineCountingReviewContextService(ReviewContextService):
    def __init__(self, repository: object, *, retrieval_concurrency: int) -> None:
        super().__init__(repository, retrieval_concurrency=retrieval_concurrency)
        self.created_count = 0
        self.max_created_before_release = 0
        self.release = asyncio.Event()

    async def retrieve_context(
        self,
        review_id: str,
        request: RetrieveReviewContextRequest,
    ) -> RetrieveReviewContextResponse:
        self.created_count += 1
        self.max_created_before_release = max(
            self.max_created_before_release,
            self.created_count,
        )
        await self.release.wait()
        return await super().retrieve_context(review_id, request)


def _passage(
    passage_id: str,
    *,
    pmid: str | None,
    text: str,
    lexical_rank: float = 0.0,
    section: str = "results",
    source_kind: str = "pubtator_full_bioc",
    source_id: str | None = None,
) -> ReviewPassageRow:
    return ReviewPassageRow(
        passage_id=passage_id,
        review_id="review-1",
        source_id=source_id or f"source-{pmid}",
        source_kind=source_kind,
        section=section,
        text=text,
        pmid=pmid,
        lexical_rank=lexical_rank,
    )


@pytest.mark.asyncio
async def test_retrieve_context_rejects_unknown_session() -> None:
    repository = FakeReviewContextRepository([])
    repository.session_exists = False
    service = ReviewContextService(repository)

    with pytest.raises(ValueError, match="session_not_found"):
        await service.retrieve_context(
            "review-1",
            RetrieveReviewContextRequest(question="MEFV", session_id="missing"),
        )


@pytest.mark.asyncio
async def test_retrieve_context_passes_session_and_status_lists() -> None:
    repository = FakeReviewContextRepository(
        [_passage("p1", pmid="111", text="session passage")],
        preparation_status={"complete": 1},
    )
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id="PMID:111",
            pmid="111",
            source_kind="pubtator_full_bioc",
            job_status="complete",
        ),
        ReviewSourceSummary(
            source_id="PMID:222",
            pmid="222",
            source_kind="pubtator_full_bioc",
            job_status="queued",
        ),
    ]
    repository.failed_source_summaries = [
        FailedSourceSummary(
            source_id="PMID:333",
            pmid="333",
            source_kind="pubtator_full_bioc",
            job_status="failed",
        )
    ]
    service = ReviewContextService(repository)

    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(question="MEFV", session_id="session-1"),
    )

    assert repository.search_calls[0]["session_id"] == "session-1"
    assert response.prepared_pmids == ["111"]
    assert response.still_preparing_pmids == ["222"]
    assert response.failed_pmids == ["333"]


@pytest.mark.asyncio
async def test_retrieve_context_packs_deterministic_diverse_context() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p-high-same-pmid", pmid="111", text="highest same PMID", lexical_rank=9.0),
            _passage("p-second-same-pmid", pmid="111", text="second same PMID", lexical_rank=8.0),
            _passage("p-other-pmid", pmid="222", text="other PMID", lexical_rank=7.0),
            _passage(
                "p-abstract-tie",
                pmid="333",
                text="abstract tie",
                lexical_rank=6.0,
                section="abstract",
            ),
            _passage(
                "p-results-tie", pmid="333", text="results tie", lexical_rank=6.0, section="results"
            ),
        ],
        preparation_status={"queued": 1, "complete": 2},
    )
    service = ReviewContextService(repository)
    request = RetrieveReviewContextRequest(
        question="Does colchicine reduce attacks?",
        entity_ids=["MESH:D003106"],
        max_passages=4,
        max_passages_per_pmid=1,
    )

    response = await service.retrieve_context("review-1", request)

    assert repository.search_calls == [
        {
            "review_id": "review-1",
            "query": "Does colchicine reduce attacks?",
            "entity_ids": ["MESH:D003106"],
            "pmids": [],
            "sections": [],
            "session_id": None,
            "limit": 80,
        }
    ]
    assert [passage.passage_id for passage in response.context_pack.passages] == [
        "p-high-same-pmid",
        "p-other-pmid",
        "p-abstract-tie",
    ]
    assert [passage.citation_key for passage in response.context_pack.passages] == [
        "S1",
        "S2",
        "S3",
    ]
    assert response.context_pack.citation_map == {
        "S1": "p-high-same-pmid",
        "S2": "p-other-pmid",
        "S3": "p-abstract-tie",
    }
    assert response.index_snapshot_date is not None
    assert response.preparation_status.queued == 1
    assert response.preparation_status.complete == 2


@pytest.mark.asyncio
async def test_get_passages_by_id_preserves_order_reports_missing_and_truncates() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p1", pmid="111", text="a" * 500, lexical_rank=1.0),
            _passage("p2", pmid="222", text="short", lexical_rank=1.0),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.get_passages_by_id(
        review_id="review-1",
        passage_ids=["p2", "missing", "p1"],
        max_chars_per_passage=300,
    )

    assert [passage.passage_id for passage in response.passages] == ["p2", "p1"]
    assert response.not_found == ["missing"]
    assert response.passages[1].truncated is True
    assert len(response.passages[1].text) <= 300


@pytest.mark.asyncio
async def test_get_audit_trail_returns_copy_ready_items() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage(
                "PMID:40234174:abstract:0",
                pmid="40234174",
                text="MEFV variants respond to colchicine in familial Mediterranean fever.",
                section="abstract",
                source_kind="pubtator_abstract",
            )
        ]
    )
    service = ReviewContextService(repository)

    response = await service.get_audit_trail(
        review_id="review-1",
        passage_ids=["PMID:40234174:abstract:0", "missing"],
        max_chars_per_passage=500,
    )

    assert response.items[0].pmid == "40234174"
    assert response.items[0].stable_citation_key.startswith("c_")
    assert response.not_found == ["missing"]
    assert "PMID:40234174:abstract:0" in response.audit_block


@pytest.mark.asyncio
async def test_get_neighboring_passages_honors_window_and_same_section() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p0", pmid="111", text="intro", section="intro", source_id="s1"),
            _passage("p1", pmid="111", text="before", section="results", source_id="s1"),
            _passage("p2", pmid="111", text="anchor", section="results", source_id="s1"),
            _passage("p3", pmid="111", text="after", section="results", source_id="s1"),
            _passage("p4", pmid="111", text="discussion", section="discussion", source_id="s1"),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.get_neighboring_passages(
        review_id="review-1",
        passage_id="p2",
        before=1,
        after=1,
        same_section=True,
        max_chars_per_passage=300,
    )

    assert [passage.passage_id for passage in response.passages] == ["p1", "p2", "p3"]
    assert response.not_found == []


@pytest.mark.asyncio
async def test_get_neighboring_passages_reports_missing_anchor() -> None:
    service = ReviewContextService(FakeReviewContextRepository([]))

    response = await service.get_neighboring_passages(
        review_id="review-1",
        passage_id="missing",
        before=1,
        after=1,
        same_section=True,
        max_chars_per_passage=300,
    )

    assert response.passages == []
    assert response.not_found == ["missing"]


@pytest.mark.asyncio
async def test_single_pmid_filter_disables_diversity_cap() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p1", pmid="111", text="first", lexical_rank=9.0),
            _passage("p2", pmid="111", text="second", lexical_rank=8.0),
            _passage("p3", pmid="222", text="other", lexical_rank=7.0),
        ]
    )
    service = ReviewContextService(repository)
    request = RetrieveReviewContextRequest(
        question="What is the evidence?",
        pmids=["111"],
        max_passages=3,
        max_passages_per_pmid=1,
    )

    response = await service.retrieve_context("review-1", request)

    assert [passage.passage_id for passage in response.context_pack.passages] == [
        "p1",
        "p2",
        "p3",
    ]


@pytest.mark.asyncio
async def test_max_chars_drops_over_budget_passages_without_truncating() -> None:
    text_450 = "a" * 450
    text_100 = "b" * 100
    text_50 = "c" * 50
    repository = FakeReviewContextRepository(
        [
            _passage("p-fits", pmid="111", text=text_450, lexical_rank=9.0),
            _passage("p-over-budget", pmid="222", text=text_100, lexical_rank=8.0),
            _passage("p-still-fits", pmid="333", text=text_50, lexical_rank=7.0),
        ]
    )
    service = ReviewContextService(repository)
    request = RetrieveReviewContextRequest(
        question="What is the evidence?",
        max_passages=3,
        max_chars=500,
    )

    response = await service.retrieve_context("review-1", request)

    assert [passage.passage_id for passage in response.context_pack.passages] == [
        "p-fits",
        "p-still-fits",
    ]
    assert response.context_pack.passages[0].text == text_450
    assert response.context_pack.passages[1].text == text_50


@pytest.mark.asyncio
async def test_reference_passages_rank_after_body_sections_when_scores_tie() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("a-ref", pmid="111", text="reference title", lexical_rank=5.0, section="REF"),
            _passage(
                "z-discuss",
                pmid="111",
                text="discussion content",
                lexical_rank=5.0,
                section="DISCUSS",
            ),
        ]
    )
    service = ReviewContextService(repository)
    request = RetrieveReviewContextRequest(
        question="colchicine response", pmids=["111"], include_references=True
    )

    response = await service.retrieve_context("review-1", request)

    assert [passage.passage_id for passage in response.context_pack.passages] == [
        "z-discuss",
        "a-ref",
    ]


@pytest.mark.asyncio
async def test_inspect_review_index_returns_sources_totals_and_failures() -> None:
    repository = FakeReviewContextRepository(
        [],
        preparation_status={"complete": 1, "failed": 1},
    )
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id="111",
            pmid="111",
            source_kind="pubtator_abstract",
            job_status="complete",
            attempt_statuses=["success"],
            sections=["abstract"],
            passage_count=2,
            char_count=30,
            sample_passages=[
                ReviewPassageSample(
                    passage_id="p1",
                    section="abstract",
                    text="Indexed passage.",
                    char_count=16,
                )
            ],
        )
    ]
    repository.failed_source_summaries = [
        FailedSourceSummary(
            source_id="222",
            pmid="222",
            source_kind="pubtator_full_bioc",
            job_status="failed",
            error="not available",
            attempt_statuses=["not_available"],
        )
    ]
    repository.index_totals = ReviewIndexTotals(
        pmid_count=1,
        source_count=1,
        passage_count=2,
        char_count=30,
        failed_source_count=1,
    )
    service = ReviewContextService(repository)

    response = await service.inspect_review_index(
        review_id="review-1",
        request=InspectReviewIndexRequest(
            pmids=["111"],
            include_passage_samples=True,
            sample_per_pmid=1,
            min_sample_chars=90,
            sample_section_policy="original_order",
        ),
    )

    assert response.success is True
    assert response.review_id == "review-1"
    assert response.preparation_status.complete == 1
    assert response.preparation_status.failed == 1
    assert response.totals.passage_count == 2
    assert response.sources[0].sample_passages[0].passage_id == "p1"
    assert response.failed_sources[0].error == "not available"
    assert response.index_snapshot_date is not None
    assert repository.inspect_calls == [
        {
            "method": "list_review_sources",
            "review_id": "review-1",
            "pmids": ["111"],
            "include_passage_samples": True,
            "sample_per_pmid": 1,
            "min_sample_chars": 90,
            "sample_section_policy": "original_order",
            "session_id": None,
        },
        {"method": "review_index_totals", "review_id": "review-1", "session_id": None},
        {"method": "list_review_failed_sources", "review_id": "review-1", "session_id": None},
    ]


@pytest.mark.asyncio
async def test_inspect_review_index_includes_coverage_summary() -> None:
    repository = FakeReviewContextRepository([])
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id="s1",
            pmid="1",
            source_kind="pubtator_full_bioc",
            job_status="complete",
            coverage="full_text",
        ),
        ReviewSourceSummary(
            source_id="s2",
            pmid="2",
            source_kind="pubtator_abstract",
            job_status="complete",
            coverage="abstract_only",
        ),
        ReviewSourceSummary(
            source_id="s3",
            pmid="3",
            source_kind="pubtator_abstract",
            job_status="complete",
            coverage="title_only",
        ),
    ]
    service = ReviewContextService(repository)

    response = await service.inspect_review_index("review-1", InspectReviewIndexRequest())

    assert response.coverage_summary == {
        "full_text": 1,
        "abstract_only": 1,
        "title_only": 1,
        "unknown": 0,
    }


@pytest.mark.asyncio
async def test_inspect_review_index_attaches_citation_metadata() -> None:
    repository = FakeReviewContextRepository([], preparation_status={"complete": 1})
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id="111",
            pmid="111",
            source_kind="pubtator_abstract",
            job_status="complete",
        )
    ]
    metadata_service = FakeMetadataService()
    service = ReviewContextService(repository, metadata_service=metadata_service)

    response = await service.inspect_review_index(
        review_id="review-1",
        request=InspectReviewIndexRequest(include_metadata=True, metadata="basic"),
    )

    assert response.sources[0].citation_metadata is not None
    assert response.sources[0].citation_metadata.title == "Citation title"
    assert metadata_service.requests[0].pmids == ["111"]
    assert metadata_service.requests[0].include_mesh is False


@pytest.mark.asyncio
async def test_zero_result_retrieval_includes_actionable_diagnostics() -> None:
    repository = FakeReviewContextRepository(
        [],
        preparation_status={"complete": 2, "failed": 1},
    )
    repository.available_sections_value = ["abstract", "discussion", "table"]
    repository.indexed_pmids_value = ["111", "222"]
    repository.failed_source_summaries = [
        FailedSourceSummary(
            source_id="333",
            pmid="333",
            source_kind="pubtator_full_bioc",
            job_status="failed",
            error="not available",
            attempt_statuses=["not_available"],
        )
    ]
    service = ReviewContextService(repository)

    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(question="Does colchicine reduce attacks in children?"),
    )

    assert response.context_pack.passages == []
    assert response.diagnostics is not None
    assert response.diagnostics.candidate_count == 0
    assert response.diagnostics.selected_count == 0
    assert response.diagnostics.indexed_pmids == ["111", "222"]
    assert response.diagnostics.available_sections == ["abstract", "discussion", "table"]
    assert response.diagnostics.failed_sources[0].pmid == "333"
    assert "Try shorter keyword queries" in response.diagnostics.message
    assert response.diagnostics.suggested_queries


@pytest.mark.asyncio
async def test_nonzero_retrieval_includes_diagnostics_when_requested() -> None:
    repository = FakeReviewContextRepository(
        [_passage("p1", pmid="111", text="colchicine response", lexical_rank=9.0)]
    )
    repository.available_sections_value = ["abstract"]
    repository.indexed_pmids_value = ["111"]
    service = ReviewContextService(repository)

    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(
            question="colchicine response",
            include_diagnostics=True,
        ),
    )

    assert response.context_pack.passages[0].passage_id == "p1"
    assert response.diagnostics is not None
    assert response.diagnostics.candidate_count == 1
    assert response.diagnostics.selected_count == 1


@pytest.mark.asyncio
async def test_batch_retrieval_deduplicates_and_preserves_per_query_diagnostics() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p1", pmid="111", text="first passage", lexical_rank=9.0),
            _passage("p1", pmid="111", text="first passage duplicate", lexical_rank=8.0),
            _passage("p2", pmid="222", text="second passage", lexical_rank=7.0),
        ]
    )
    repository.available_sections_value = ["abstract"]
    repository.indexed_pmids_value = ["111", "222"]
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["colchicine children", "FMF phenotype"],
            response_mode="compact",
            max_passages_per_query=3,
            max_total_passages=3,
            max_chars=1000,
        ),
    )

    assert response.results == []
    assert [summary.query for summary in response.query_summaries] == [
        "colchicine children",
        "FMF phenotype",
    ]
    assert response.query_summaries[0].returned_count == 2
    assert [passage.passage_id for passage in response.merged_context_pack.passages] == [
        "p1",
        "p2",
    ]
    assert response.merged_context_pack.citation_map == {"S1": "p1", "S2": "p2"}
    assert response.budget is not None
    assert response.budget.text_chars == len("first passage") + len("second passage")


@pytest.mark.asyncio
async def test_batch_retrieval_returns_next_context_resource_links() -> None:
    repository = FakeReviewContextRepository(
        [_passage("p 1/frag", pmid="111", text="MEFV colchicine evidence", lexical_rank=9.0)]
    )
    service = ReviewContextService(repository)

    result = await service.retrieve_context_batch(
        "review 1",
        RetrieveReviewContextBatchRequest(
            queries=["mefv colchicine"],
            max_total_passages=2,
            session_id="session 1",
        ),
    )

    options = {option.kind: option for option in result.next_context_options}
    assert options["passage"].resource == (
        "pubtator://reviews/review%201/passages/p%201%2Ffrag?session_id=session+1"
    )
    assert options["neighboring_passages"].resource == (
        "pubtator://reviews/review%201/passages/p%201%2Ffrag?before=1&after=1&session_id=session+1"
    )
    assert options["audit"].resource == (
        "pubtator://reviews/review%201/audit/p%201%2Ffrag?session_id=session+1"
    )


@pytest.mark.asyncio
async def test_batch_retrieval_runs_queries_with_bounded_concurrency_and_preserves_order() -> None:
    repository = BlockingQueryRepository(
        {
            "q1": [_passage("p1", pmid="111", text="one", lexical_rank=9.0)],
            "q2": [_passage("p2", pmid="222", text="two", lexical_rank=9.0)],
            "q3": [_passage("p3", pmid="333", text="three", lexical_rank=9.0)],
        }
    )
    service = ReviewContextService(repository, retrieval_concurrency=3)

    task = asyncio.create_task(
        service.retrieve_context_batch(
            "review-1",
            RetrieveReviewContextBatchRequest(
                queries=["q1", "q2", "q3"],
                max_passages_per_query=1,
                max_total_passages=3,
            ),
        )
    )
    await asyncio.wait_for(repository.three_started.wait(), timeout=0.5)
    repository.release.set()
    response = await task

    assert repository.started_queries == ["q1", "q2", "q3"]
    assert [summary.query for summary in response.query_summaries] == ["q1", "q2", "q3"]
    assert [passage.passage_id for passage in response.merged_context_pack.passages] == [
        "p1",
        "p2",
        "p3",
    ]


@pytest.mark.asyncio
async def test_batch_retrieval_bounds_created_query_coroutines() -> None:
    repository = QueryMappedReviewContextRepository(
        {
            "q1": [_passage("p1", pmid="111", text="one", lexical_rank=9.0)],
            "q2": [_passage("p2", pmid="222", text="two", lexical_rank=9.0)],
            "q3": [_passage("p3", pmid="333", text="three", lexical_rank=9.0)],
            "q4": [_passage("p4", pmid="444", text="four", lexical_rank=9.0)],
        }
    )
    service = CoroutineCountingReviewContextService(repository, retrieval_concurrency=2)

    task = asyncio.create_task(
        service.retrieve_context_batch(
            "review-1",
            RetrieveReviewContextBatchRequest(
                queries=["q1", "q2", "q3", "q4"],
                max_passages_per_query=1,
                max_total_passages=4,
            ),
        )
    )
    while service.created_count < 2:
        await asyncio.sleep(0)

    assert service.max_created_before_release == 2

    service.release.set()
    response = await task

    assert [summary.query for summary in response.query_summaries] == ["q1", "q2", "q3", "q4"]


@pytest.mark.asyncio
async def test_batch_retrieval_gathers_no_more_than_concurrency_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = QueryMappedReviewContextRepository(
        {
            "q1": [_passage("p1", pmid="111", text="one", lexical_rank=9.0)],
            "q2": [_passage("p2", pmid="222", text="two", lexical_rank=9.0)],
            "q3": [_passage("p3", pmid="333", text="three", lexical_rank=9.0)],
            "q4": [_passage("p4", pmid="444", text="four", lexical_rank=9.0)],
        }
    )
    service = ReviewContextService(repository, retrieval_concurrency=2)
    original_gather = asyncio.gather
    gather_widths: list[int] = []

    async def recording_gather(*aws, **kwargs):
        gather_widths.append(len(aws))
        return await original_gather(*aws, **kwargs)

    monkeypatch.setattr(
        "pubtator_link.services.review_context_service.asyncio.gather",
        recording_gather,
    )

    await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["q1", "q2", "q3", "q4"],
            max_passages_per_query=1,
            max_total_passages=4,
        ),
    )

    assert gather_widths == [2, 2]


@pytest.mark.asyncio
async def test_batch_compact_mode_enforces_max_response_chars() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p1", pmid="111", text="a" * 500, lexical_rank=9.0),
            _passage("p2", pmid="222", text="b" * 500, lexical_rank=8.0),
            _passage("p3", pmid="333", text="c" * 500, lexical_rank=7.0),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["colchicine"],
            max_chars=5000,
            max_response_chars=2000,
        ),
    )

    assert [passage.passage_id for passage in response.merged_context_pack.passages] == ["p1"]
    assert response.budget is not None
    assert response.budget.estimated_total_chars <= 2000
    assert response.merged_context_pack.dropped[-1].reason == "response_char_budget_exceeded"


@pytest.mark.asyncio
async def test_batch_retrieval_reserves_budget_for_later_queries() -> None:
    repository = QueryMappedReviewContextRepository(
        {
            "query one": [
                _passage("q1-a", pmid="111", text="a" * 300, lexical_rank=10.0),
                _passage("q1-b", pmid="112", text="b" * 300, lexical_rank=9.0),
                _passage("q1-c", pmid="113", text="c" * 300, lexical_rank=8.0),
            ],
            "query two": [_passage("q2-a", pmid="221", text="d" * 300, lexical_rank=10.0)],
            "query three": [_passage("q3-a", pmid="331", text="e" * 300, lexical_rank=10.0)],
        }
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["query one", "query two", "query three"],
            max_chars=900,
            max_response_chars=100000,
            max_passages_per_query=3,
            max_total_passages=6,
        ),
    )

    assert [passage.passage_id for passage in response.merged_context_pack.passages] == [
        "q1-a",
        "q2-a",
        "q3-a",
    ]
    assert [summary.returned_count for summary in response.query_summaries] == [1, 1, 1]
    assert response.query_summaries[1].zero_result_reason is None
    assert response.query_summaries[2].zero_result_reason is None


@pytest.mark.asyncio
async def test_single_retrieval_excerpts_oversized_passage() -> None:
    long_text = "intro " + ("background " * 200) + " MEFV colchicine " + ("evidence " * 200)
    repository = FakeReviewContextRepository(
        [_passage("p-long", pmid="123", text=long_text, lexical_rank=9.0, section="DISCUSS")]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(
            question="MEFV colchicine",
            max_chars=1000,
            max_chars_per_passage=500,
            allow_truncated_passages=True,
        ),
    )

    passage = response.context_pack.passages[0]
    assert passage.truncated is True
    assert passage.char_count == len(passage.text)
    assert passage.start_char is not None
    assert passage.end_char is not None
    assert "MEFV colchicine" in passage.text
    assert len(passage.text) <= 500


@pytest.mark.asyncio
async def test_single_retrieval_reports_oversized_drop_when_truncation_disabled() -> None:
    repository = FakeReviewContextRepository(
        [_passage("p-long", pmid="123", text="MEFV " + ("x" * 1000), lexical_rank=9.0)]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(
            question="MEFV",
            max_chars=2000,
            max_chars_per_passage=500,
            allow_truncated_passages=False,
        ),
    )

    assert response.context_pack.passages == []
    assert response.context_pack.dropped[0].reason == "passage_over_max_chars_per_passage"


@pytest.mark.asyncio
async def test_review_retrieval_excludes_tables_and_references_by_default() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage(
                "p-table",
                pmid="123",
                text="MEFV colchicine table row",
                lexical_rank=10.0,
                section="TABLE",
            ),
            _passage(
                "p-ref",
                pmid="123",
                text="MEFV colchicine reference title",
                lexical_rank=9.0,
                section="REF",
            ),
            _passage(
                "p-abstract",
                pmid="123",
                text="MEFV colchicine abstract evidence",
                lexical_rank=8.0,
                section="ABSTRACT",
            ),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context(
        "review-1",
        RetrieveReviewContextRequest(question="MEFV colchicine"),
    )

    assert [passage.section for passage in response.context_pack.passages] == ["ABSTRACT"]


@pytest.mark.asyncio
async def test_batch_full_mode_preserves_per_query_results() -> None:
    repository = FakeReviewContextRepository(
        [_passage("p1", pmid="111", text="MEFV colchicine evidence", lexical_rank=9.0)]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["MEFV"],
            response_mode="full",
            max_chars=12000,
        ),
    )

    assert response.response_mode == "full"
    assert response.results[0].context_pack.passages[0].text == "MEFV colchicine evidence"
    assert response.budget is not None
    assert response.budget.text_chars >= len("MEFV colchicine evidence") * 2


@pytest.mark.asyncio
async def test_batch_diagnostics_mode_returns_no_passage_text() -> None:
    repository = FakeReviewContextRepository([], preparation_status={})
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["MEFV colchicine"],
            response_mode="diagnostics",
            include_diagnostics=True,
        ),
    )

    assert response.response_mode == "diagnostics"
    assert response.results == []
    assert response.merged_context_pack.passages == []
    assert response.query_summaries[0].zero_result_reason in {
        "review_not_indexed",
        "no_candidate_matches",
    }
    assert response.query_summaries[0].next_steps


@pytest.mark.asyncio
async def test_batch_quotes_mode_returns_short_quotes_without_merged_passages() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage(
                "PMID:111:abstract:1",
                pmid="111",
                section="abstract",
                source_kind="pubtator_abstract",
                text=(
                    "MEFV evidence supports colchicine response in this cohort. "
                    + "Additional mechanistic context. " * 30
                ),
            )
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["MEFV"],
            response_mode="quotes",
            max_chars=12000,
        ),
    )

    assert response.response_mode == "quotes"
    assert response.quotes
    assert response.quotes[0].stable_citation_key.startswith("c_")
    assert response.quotes[0].pmid == "111"
    assert response.quotes[0].section == "abstract"
    assert response.quotes[0].matched_queries == ["MEFV"]
    assert response.quotes[0].coverage_status == "abstract_only"
    assert all(len(item.quote) <= 350 for item in response.quotes)
    assert response.merged_context_pack.passages == []


@pytest.mark.asyncio
async def test_batch_dry_run_returns_diagnostics_without_passage_text() -> None:
    repository = FakeReviewContextRepository(
        [_passage("p1", pmid="111", text="colchicine evidence", lexical_rank=9.0)]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["colchicine response"],
            dry_run=True,
            response_mode="diagnostics",
        ),
    )

    assert response.response_mode == "diagnostics"
    assert response.merged_context_pack.passages == []
    assert response.query_summaries[0].candidate_count == 1
    assert response.query_summaries[0].returned_count == 1
    assert response.cache_key is not None
    assert response.corpus_snapshot_date is not None
    assert response.index_snapshot_date is not None


@pytest.mark.asyncio
async def test_batch_context_pack_includes_stable_citation_map() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage(
                "PMID:40234174:abstract:1",
                pmid="40234174",
                text="guideline abstract",
            )
        ]
    )
    service = ReviewContextService(repository)
    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(queries=["guideline colchicine"]),
    )
    passage = response.merged_context_pack.passages[0]

    assert passage.stable_citation_key.startswith("c_")
    assert response.merged_context_pack.stable_citation_map == {
        passage.stable_citation_key: passage.passage_id
    }
    assert response.index_snapshot_date is not None


@pytest.mark.asyncio
async def test_batch_query_fair_preserves_existing_merge_order() -> None:
    repository = QueryMappedReviewContextRepository(
        {
            "query one": [
                _passage("q1-a", pmid="111", text="a" * 300, lexical_rank=10.0),
                _passage("q1-b", pmid="112", text="b" * 300, lexical_rank=9.0),
                _passage("q1-c", pmid="113", text="c" * 300, lexical_rank=8.0),
            ],
            "query two": [_passage("q2-a", pmid="221", text="d" * 300, lexical_rank=10.0)],
            "query three": [_passage("q3-a", pmid="331", text="e" * 300, lexical_rank=10.0)],
        }
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["query one", "query two", "query three"],
            budget_strategy="query_fair",
            max_chars=900,
            max_response_chars=100000,
            max_passages_per_query=3,
            max_total_passages=6,
        ),
    )

    assert [passage.passage_id for passage in response.merged_context_pack.passages] == [
        "q1-a",
        "q2-a",
        "q3-a",
    ]


@pytest.mark.asyncio
async def test_batch_source_fair_includes_later_pmids_before_overflow() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p1", pmid="111", text="a" * 100, lexical_rank=10.0),
            _passage("p2", pmid="111", text="b" * 100, lexical_rank=9.0),
            _passage("p3", pmid="222", text="c" * 100, lexical_rank=8.0),
            _passage("p4", pmid="333", text="d" * 100, lexical_rank=7.0),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["guideline"],
            budget_strategy="source_fair",
            max_chars=600,
            max_response_chars=100000,
            max_passages_per_query=4,
            max_total_passages=3,
        ),
    )

    assert [passage.pmid for passage in response.merged_context_pack.passages] == [
        "111",
        "222",
        "333",
    ]
    assert response.source_budget_summaries
    assert response.source_budget_summaries[0].first_pass_eligible is True


@pytest.mark.asyncio
async def test_batch_source_fair_rounds_sources_before_second_passages() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("a1", pmid="111", text="a" * 100, lexical_rank=10.0),
            _passage("a2", pmid="111", text="b" * 100, lexical_rank=9.0),
            _passage("b1", pmid="222", text="c" * 100, lexical_rank=8.0),
            _passage("c1", pmid="333", text="d" * 100, lexical_rank=7.0),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["guideline"],
            budget_strategy="source_fair",
            min_passages_per_source=2,
            max_chars=10000,
            max_response_chars=100000,
            max_passages_per_query=4,
            max_total_passages=3,
        ),
    )

    assert [passage.passage_id for passage in response.merged_context_pack.passages] == [
        "a1",
        "b1",
        "c1",
    ]


@pytest.mark.asyncio
async def test_batch_source_fair_uses_source_id_for_non_pmid_sources() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage(
                "url-a-1",
                pmid=None,
                source_id="URL:https://example.test/a.pdf",
                source_kind="curated_pdf",
                text="a" * 100,
                lexical_rank=10.0,
            ),
            _passage(
                "url-a-2",
                pmid=None,
                source_id="URL:https://example.test/a.pdf",
                source_kind="curated_pdf",
                text="b" * 100,
                lexical_rank=9.0,
            ),
            _passage(
                "url-b-1",
                pmid=None,
                source_id="URL:https://example.test/b.pdf",
                source_kind="curated_pdf",
                text="c" * 100,
                lexical_rank=8.0,
            ),
            _passage(
                "url-c-1",
                pmid=None,
                source_id="URL:https://example.test/c.pdf",
                source_kind="curated_pdf",
                text="d" * 100,
                lexical_rank=7.0,
            ),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["guideline"],
            budget_strategy="source_fair",
            min_passages_per_source=2,
            max_chars=10000,
            max_response_chars=100000,
            max_passages_per_query=4,
            max_total_passages=3,
        ),
    )

    assert [passage.passage_id for passage in response.merged_context_pack.passages] == [
        "url-a-1",
        "url-b-1",
        "url-c-1",
    ]
    assert [passage.source_id for passage in response.merged_context_pack.passages] == [
        "URL:https://example.test/a.pdf",
        "URL:https://example.test/b.pdf",
        "URL:https://example.test/c.pdf",
    ]


@pytest.mark.asyncio
async def test_batch_source_fair_duplicate_does_not_consume_returned_quota() -> None:
    repository = QueryMappedReviewContextRepository(
        {
            "query one": [
                _passage("p111-keep", pmid="111", text="a" * 50, lexical_rank=10.0),
                _passage("p333-a", pmid="333", text="b" * 50, lexical_rank=9.0),
                _passage("p333-b", pmid="333", text="c" * 50, lexical_rank=8.0),
            ],
            "query two": [
                _passage("p111-keep", pmid="111", text="duplicate", lexical_rank=10.0),
                _passage("p333-c", pmid="333", text="d" * 50, lexical_rank=9.0),
            ],
            "query three": [_passage("p111-later", pmid="111", text="e" * 50, lexical_rank=10.0)],
        }
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["query one", "query two", "query three"],
            budget_strategy="source_fair",
            min_passages_per_source=2,
            max_chars=10000,
            max_response_chars=100000,
            max_passages_per_query=3,
            max_total_passages=4,
        ),
    )

    passage_ids = [passage.passage_id for passage in response.merged_context_pack.passages]
    assert passage_ids == ["p111-keep", "p333-a", "p333-b", "p111-later"]
    assert "p333-c" not in passage_ids


@pytest.mark.asyncio
async def test_batch_scarcity_first_prefers_low_coverage_sources() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p-full", pmid="333", text="full text evidence", lexical_rank=10.0),
            _passage("p-abstract", pmid="222", text="abstract evidence", lexical_rank=9.0),
            _passage("p-title", pmid="111", text="title evidence", lexical_rank=8.0),
        ]
    )
    repository.source_coverages = {
        "111": "title_only",
        "222": "abstract_only",
        "333": "full_text",
    }
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["guideline"],
            budget_strategy="scarcity_first",
            max_chars=10000,
            max_response_chars=100000,
            max_passages_per_query=3,
            max_total_passages=3,
        ),
    )

    assert [passage.pmid for passage in response.merged_context_pack.passages] == [
        "111",
        "222",
        "333",
    ]


@pytest.mark.asyncio
async def test_batch_source_fair_respects_global_budget_precedence() -> None:
    repository = FakeReviewContextRepository(
        [
            _passage("p1", pmid="111", text="a" * 100, lexical_rank=10.0),
            _passage("p2", pmid="111", text="b" * 100, lexical_rank=9.0),
            _passage("p3", pmid="222", text="c" * 100, lexical_rank=8.0),
            _passage("p4", pmid="333", text="d" * 100, lexical_rank=7.0),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["guideline"],
            budget_strategy="source_fair",
            min_passages_per_source=1,
            max_total_passages=3,
            max_chars=10000,
            max_response_chars=100000,
        ),
    )

    assert len(response.merged_context_pack.passages) == 3
    assert response.merged_context_pack.dropped
    assert any(
        drop.reason == "source_budget_exceeded" for drop in response.merged_context_pack.dropped
    )
