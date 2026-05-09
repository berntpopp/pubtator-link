from __future__ import annotations

from pubtator_link.benchmarks.models import BenchmarkCase, PredictionRecord, SourceAccess
from pubtator_link.benchmarks.scoring import score_bioasq_ideal


def _gold_case() -> BenchmarkCase:
    return BenchmarkCase(
        dataset="bioasq_ideal",
        dataset_version="jmhb_bioasq_summary_smoke_v1",
        case_id="bioasq_1",
        question="What is the effect?",
        target_pmids=["1", "2"],
        gold_label=None,
        gold_answer={"reference_ideal_answer": "alpha beta gamma"},
        gold_evidence_pmids=["1", "2"],
        source_access={"1": SourceAccess.ABSTRACT_ONLY, "2": SourceAccess.ABSTRACT_ONLY},
        dataset_license="test",
        dataset_use_restriction="research_use",
    )


def test_bioasq_citation_precision_recall_and_source_access() -> None:
    predictions = [
        PredictionRecord(case_id="bioasq_1", predicted_answer="alpha beta", cited_pmids=["1", "2"])
    ]

    scores = score_bioasq_ideal([_gold_case()], predictions)

    assert scores.score_details["citation_recall"] == 1.0
    assert scores.score_details["citation_precision"] == 1.0
    assert scores.gold_source_access_rate["abstract_only"] == 1.0


def test_dangerous_error_counts_are_separate_from_lexical_scores() -> None:
    predictions = [
        PredictionRecord(
            case_id="bioasq_1",
            predicted_answer="wrong",
            cited_pmids=["1"],
            score_details={"wrong_direction": True, "unsupported_claim": True},
        )
    ]

    scores = score_bioasq_ideal([_gold_case()], predictions)

    assert scores.wrong_direction_count == 1
    assert scores.unsupported_claim_count == 1
