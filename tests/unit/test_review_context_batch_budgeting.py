from __future__ import annotations

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    PreparationStatus,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
)
from pubtator_link.services.review_context.batch_budgeting import merge_batch_context


def _passage(
    passage_id: str,
    text: str,
    pmid: str = "1",
    section: str = "abstract",
) -> ContextPassage:
    return ContextPassage(
        citation_key="S1",
        passage_id=passage_id,
        source_id=f"source-{pmid}",
        pmid=pmid,
        pmcid=None,
        section=section,
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


def test_compact_batch_response_omits_empty_results_when_merged_pack_is_primary() -> None:
    response = RetrieveReviewContextBatchResponse(
        review_id="r1",
        response_mode="compact",
        results=[],
        merged_context_pack=ContextPack(question="q1", passages=[], citation_map={}),
        preparation_status=PreparationStatus(),
    )
    dumped = response.model_dump(exclude_none=True, exclude_defaults=True)

    assert "merged_context_pack" in dumped
    assert "results" not in dumped


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


def test_merge_batch_context_diagnostics_mode_skips_merged_passages() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        response_mode="diagnostics",
        max_total_passages=5,
        max_chars=1000,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[_result("q1", [_passage("p1", "one")])],
        coverage_by_source={},
    )

    assert merged.passages == []


def test_batch_response_truncates_large_dropped_list_with_summary() -> None:
    response = merge_batch_context(
        request=RetrieveReviewContextBatchRequest(
            queries=["q1"],
            response_mode="compact",
            max_total_passages=1,
            max_chars=1000,
        ),
        query_results=[_result("q1", [_passage(f"p{index}", "x") for index in range(30)])],
        coverage_by_source={},
    )

    assert len(response.dropped) <= 10
    assert response.dropped_summary.truncated_count > 0


def test_batch_budgeting_honors_min_passages_per_pmid() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        max_total_passages=2,
        max_chars=1000,
        min_passages_per_pmid=1,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[
            _result(
                "q1",
                [
                    _passage("p1", "one", pmid="1"),
                    _passage("p2", "two", pmid="1"),
                    _passage("p3", "three", pmid="2"),
                ],
            )
        ],
        coverage_by_source={},
    )

    assert {passage.pmid for passage in merged.passages} == {"1", "2"}


def test_batch_response_includes_pmid_status_summary() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        max_total_passages=1,
        max_chars=1000,
        min_passages_per_pmid=1,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[_result("q1", [_passage("p1", "one", pmid="1")])],
        coverage_by_source={},
    )

    assert merged.pmid_status_summary[0].pmid == "1"
    assert merged.pmid_status_summary[0].passages_returned == 1


def test_merge_batch_context_structures_dropped_summary_with_filter_advice() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["MEFV colchicine"],
        max_total_passages=1,
        max_chars=500,
        max_response_chars=2000,
    )
    result = _result(
        "MEFV colchicine",
        [
            _passage("p1", "A" * 100, pmid="40234174", section="abstract"),
            _passage("p2", "B" * 100, pmid="40234174", section="results"),
            _passage("p3", "C" * 100, pmid="26802180", section="discussion"),
        ],
    )

    merged = merge_batch_context(
        request=request,
        query_results=[result],
        coverage_by_source={},
    )

    assert hasattr(merged.dropped_summary, "by_reason")
    assert merged.dropped_summary.by_reason["max_total_passages_exceeded"] >= 1
    assert merged.dropped_summary.suggested_filters is not None
    assert merged.dropped_summary.suggested_filters.sections
