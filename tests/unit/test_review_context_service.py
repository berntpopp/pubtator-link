from collections.abc import Sequence

import pytest

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    InspectReviewIndexRequest,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextRequest,
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

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        self.search_calls.append(
            {
                "review_id": review_id,
                "query": query,
                "entity_ids": entity_ids,
                "pmids": pmids,
                "sections": sections,
                "limit": limit,
            }
        )
        return self.passages

    async def preparation_status(self, review_id: str) -> dict[str, int]:
        return self.preparation_status_value

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
    ) -> list[ReviewSourceSummary]:
        self.inspect_calls.append(
            {
                "method": "list_review_sources",
                "review_id": review_id,
                "pmids": pmids,
                "include_passage_samples": include_passage_samples,
                "sample_per_pmid": sample_per_pmid,
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

    async def list_review_failed_sources(self, review_id: str) -> list[FailedSourceSummary]:
        self.inspect_calls.append({"method": "list_review_failed_sources", "review_id": review_id})
        return self.failed_source_summaries

    async def review_index_totals(self, review_id: str) -> ReviewIndexTotals:
        self.inspect_calls.append({"method": "review_index_totals", "review_id": review_id})
        return self.index_totals

    async def available_sections(self, review_id: str) -> list[str]:
        return self.available_sections_value

    async def indexed_pmids(self, review_id: str) -> list[str]:
        return self.indexed_pmids_value


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
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        self.search_calls.append(
            {
                "review_id": review_id,
                "query": query,
                "entity_ids": entity_ids,
                "pmids": pmids,
                "sections": sections,
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
    ) -> list[ReviewSourceSummary]:
        self.inspect_calls.append(
            {
                "method": "list_review_sources",
                "review_id": review_id,
                "pmids": pmids,
                "include_passage_samples": include_passage_samples,
                "sample_per_pmid": sample_per_pmid,
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


def _passage(
    passage_id: str,
    *,
    pmid: str,
    text: str,
    lexical_rank: float = 0.0,
    section: str = "results",
    source_kind: str = "pubtator_full_bioc",
) -> ReviewPassageRow:
    return ReviewPassageRow(
        passage_id=passage_id,
        review_id="review-1",
        source_id=f"source-{pmid}",
        source_kind=source_kind,
        section=section,
        text=text,
        pmid=pmid,
        lexical_rank=lexical_rank,
    )


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
    assert response.preparation_status.queued == 1
    assert response.preparation_status.complete == 2


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
        ),
    )

    assert response.success is True
    assert response.review_id == "review-1"
    assert response.preparation_status.complete == 1
    assert response.preparation_status.failed == 1
    assert response.totals.passage_count == 2
    assert response.sources[0].sample_passages[0].passage_id == "p1"
    assert response.failed_sources[0].error == "not available"
    assert repository.inspect_calls == [
        {
            "method": "list_review_sources",
            "review_id": "review-1",
            "pmids": ["111"],
            "include_passage_samples": True,
            "sample_per_pmid": 1,
        },
        {"method": "review_index_totals", "review_id": "review-1"},
        {"method": "list_review_failed_sources", "review_id": "review-1"},
    ]


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
            _passage("p2", pmid="222", text="b" * 100, lexical_rank=9.0),
            _passage("p3", pmid="333", text="c" * 100, lexical_rank=8.0),
            _passage("p4", pmid="444", text="d" * 100, lexical_rank=7.0),
            _passage("p5", pmid="555", text="e" * 100, lexical_rank=6.0),
        ]
    )
    service = ReviewContextService(repository)

    response = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["guideline"],
            budget_strategy="source_fair",
            min_passages_per_source=2,
            max_total_passages=3,
            max_chars=10000,
            max_response_chars=100000,
        ),
    )

    assert len(response.merged_context_pack.passages) == 3
    assert response.merged_context_pack.dropped
    assert any(
        drop.reason in {"max_total_passages_exceeded", "source_budget_exceeded"}
        for drop in response.merged_context_pack.dropped
    )
