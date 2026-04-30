from __future__ import annotations

from pubtator_link.models.review_rerag import (
    ContextPack,
    PreparationStatus,
    RetrieveReviewContextResponse,
)
from pubtator_link.services.review_context.diagnostics import (
    query_summary,
    query_tokens,
    suggested_queries,
)


def test_query_tokens_deduplicates_and_limits_short_tokens() -> None:
    assert query_tokens("MEFV and FMF colchicine MEFV in children") == [
        "mefv",
        "and",
        "fmf",
        "colchicine",
        "children",
    ]


def test_suggested_queries_removes_section_tokens() -> None:
    assert suggested_queries(["mefv", "abstract", "colchicine"], ["abstract"]) == [
        "mefv colchicine"
    ]


def test_query_summary_marks_unindexed_review() -> None:
    result = RetrieveReviewContextResponse(
        review_id="r1",
        context_pack=ContextPack(question="MEFV", passages=[], citation_map={}),
        preparation_status=PreparationStatus(),
        diagnostics=None,
    )

    summary = query_summary(query="MEFV", result=result, returned_count=0, dropped_count=0)

    assert summary.zero_result_reason == "review_not_indexed"
    assert summary.next_steps == ["index_review_evidence", "inspect_review_index"]
