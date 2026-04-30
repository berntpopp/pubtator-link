from collections.abc import Sequence

import pytest

from pubtator_link.models.review_rerag import RetrieveReviewContextRequest, ReviewPassageRow
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


def _passage(
    passage_id: str,
    *,
    pmid: str,
    text: str,
    lexical_rank: float,
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
