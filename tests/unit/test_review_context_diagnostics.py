from __future__ import annotations

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    PreparationStatus,
    RetrieveReviewContextResponse,
)
from pubtator_link.services.review_context.diagnostics import (
    query_summary,
    query_tokens,
    recovery_from_query_summary,
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


def test_zero_result_reason_includes_coverage_abstract_only() -> None:
    from pubtator_link.models.review_rerag import QueryDiagnosticsSummary

    summary = QueryDiagnosticsSummary(
        query="dose table",
        query_tokens=["dose", "table"],
        zero_result_reason="coverage_abstract_only",
    )

    assert summary.zero_result_reason == "coverage_abstract_only"


def test_high_drop_nonzero_query_summary_has_next_steps() -> None:
    result = RetrieveReviewContextResponse(
        review_id="r1",
        context_pack=ContextPack(
            question="MEFV",
            passages=[
                ContextPassage(
                    citation_key="S1",
                    passage_id="p1",
                    section="abstract",
                    text="evidence",
                )
            ],
            citation_map={},
        ),
        preparation_status=PreparationStatus(complete=1),
        diagnostics=None,
    )

    summary = query_summary(
        query="MEFV colchicine", result=result, returned_count=1, dropped_count=9
    )

    assert summary.next_steps == ["increase_budget", "narrow_query", "inspect_review_index"]


def test_recovery_from_zero_result_query_summary_promotes_next_steps() -> None:
    from pubtator_link.models.review_rerag import QueryDiagnosticsSummary

    summary = QueryDiagnosticsSummary(
        query="MEFV colchicine",
        query_tokens=["mefv", "colchicine"],
        candidate_count=0,
        selected_count=0,
        returned_count=0,
        dropped_count=0,
        zero_result_reason="no_candidate_matches",
        suggested_queries=["mefv"],
        next_steps=["shorten_query", "drop_filters"],
    )

    recovery = recovery_from_query_summary(summary)

    assert recovery is not None
    assert recovery.reason == "no_candidate_matches"
    assert recovery.suggested_queries == ["mefv"]
    assert recovery.next_steps == ["shorten_query", "drop_filters"]


def test_recovery_from_high_drop_query_summary_suggests_budget() -> None:
    from pubtator_link.models.review_rerag import QueryDiagnosticsSummary

    summary = QueryDiagnosticsSummary(
        query="MEFV colchicine",
        query_tokens=["mefv", "colchicine"],
        candidate_count=20,
        selected_count=8,
        returned_count=2,
        dropped_count=8,
        top_sections=["abstract"],
        top_pmids=["40234174"],
        next_steps=["increase_budget", "narrow_query"],
    )

    recovery = recovery_from_query_summary(summary)

    assert recovery is not None
    assert recovery.reason == "high_drop_pressure"
    assert recovery.suggested_filters is not None
    assert recovery.suggested_filters.sections == ["abstract"]
    assert recovery.budget_advice is not None
