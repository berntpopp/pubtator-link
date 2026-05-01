from __future__ import annotations

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    PreparationStatus,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextResponse,
)
from pubtator_link.services.review_context.batch_budgeting import merge_batch_context


def _passage(passage_id: str, text: str, pmid: str = "1") -> ContextPassage:
    return ContextPassage(
        citation_key="S1",
        passage_id=passage_id,
        source_id=f"source-{pmid}",
        pmid=pmid,
        pmcid=None,
        section="abstract",
        text=text,
        source_kind="pubtator_abstract",
    )


def _result(query: str, passages: list[ContextPassage]) -> RetrieveReviewContextResponse:
    return RetrieveReviewContextResponse(
        review_id="r1",
        context_pack=ContextPack(question=query, passages=passages, citation_map={}),
        preparation_status=PreparationStatus(complete=1),
        diagnostics=None,
    )


def test_merge_batch_context_deduplicates_passages() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1", "q2"],
        max_total_passages=5,
        max_chars=1000,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[
            _result("q1", [_passage("p1", "one")]),
            _result("q2", [_passage("p1", "one")]),
        ],
        coverage_by_source={},
    )

    assert [passage.passage_id for passage in merged.passages] == ["p1"]
    assert merged.dropped[0].reason == "duplicate_passage"


def test_merge_batch_context_source_fair_represents_sources_before_overflow() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        budget_strategy="source_fair",
        max_total_passages=2,
        max_chars=1000,
        min_passages_per_source=1,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[
            _result(
                "q1",
                [
                    _passage("p1", "one", pmid="1"),
                    _passage("p2", "two", pmid="2"),
                    _passage("p3", "three", pmid="1"),
                ],
            )
        ],
        coverage_by_source={"1": "full_text", "2": "abstract_only"},
    )

    assert [passage.passage_id for passage in merged.passages] == ["p1", "p2"]
    assert merged.source_budget_summaries[0].candidate_count == 2
    assert merged.source_budget_summaries[0].returned_count == 1
    assert merged.source_budget_summaries[0].first_pass_eligible is True
    assert merged.source_budget_summaries[1].candidate_count == 1
    assert merged.source_budget_summaries[1].returned_count == 1


def test_merge_batch_context_scarcity_first_prioritizes_scarcer_coverage() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        budget_strategy="scarcity_first",
        max_total_passages=1,
        max_chars=1000,
        min_passages_per_source=1,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[
            _result(
                "q1",
                [
                    _passage("full", "full text", pmid="1"),
                    _passage("abstract", "abstract text", pmid="2"),
                ],
            )
        ],
        coverage_by_source={"1": "full_text", "2": "abstract_only"},
    )

    assert [passage.passage_id for passage in merged.passages] == ["abstract"]
    assert any(drop.reason == "max_total_passages_exceeded" for drop in merged.dropped)


def test_merge_batch_context_drops_when_response_budget_would_be_exceeded() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        max_total_passages=5,
        max_chars=1000,
        max_response_chars=2000,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[_result("q1", [_passage("p1", "x" * 1000)])],
        coverage_by_source={},
    )

    assert merged.passages == []
    assert merged.dropped[0].reason == "response_char_budget_exceeded"
