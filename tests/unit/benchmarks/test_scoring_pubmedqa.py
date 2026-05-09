from __future__ import annotations

from decimal import Decimal

from pubtator_link.benchmarks.models import BenchmarkCase, PredictionRecord
from pubtator_link.benchmarks.scoring import score_pubmedqa


def _case(case_id: str, label: str) -> BenchmarkCase:
    return BenchmarkCase(
        dataset="pubmedqa",
        dataset_version="pqa_l_article_local_v1",
        case_id=case_id,
        question=f"Question {case_id}?",
        target_pmids=[case_id],
        gold_label=label,
        gold_evidence_pmids=[case_id],
        dataset_license="test",
        dataset_use_restriction="research_use",
    )


def test_pubmedqa_accuracy_macro_f1_and_confusion() -> None:
    gold_cases = [
        _case(f"case_{i}", label)
        for i, label in enumerate(["yes"] * 4 + ["no"] * 3 + ["maybe"] * 3)
    ]
    predictions = [
        PredictionRecord(case_id="case_0", predicted_label="yes"),
        PredictionRecord(case_id="case_1", predicted_label="yes"),
        PredictionRecord(case_id="case_2", predicted_label="yes"),
        PredictionRecord(case_id="case_3", predicted_label="yes"),
        PredictionRecord(case_id="case_4", predicted_label="no"),
        PredictionRecord(case_id="case_5", predicted_label="no"),
        PredictionRecord(case_id="case_6", predicted_label="yes"),
        PredictionRecord(case_id="case_7", predicted_label="maybe"),
        PredictionRecord(case_id="case_8", predicted_label="no"),
        PredictionRecord(case_id="case_9", predicted_label="yes"),
    ]

    scores = score_pubmedqa(gold_cases, predictions)

    assert scores.accuracy == Decimal("0.700000")
    assert scores.confusion_matrix["yes"]["yes"] == 4
    assert "maybe" in scores.f1_by_class


def test_invalid_label_counts_incorrect_and_parse_failure() -> None:
    scores = score_pubmedqa(
        [_case("x", "yes")], [PredictionRecord(case_id="x", predicted_label="unclear")]
    )

    assert scores.empty_output_count == 0
    assert scores.score_details["invalid_label_count"] == 1


def test_pubmedqa_scores_decisive_overcall_rate_for_maybe_cases() -> None:
    cases = [
        _case("c1", "maybe"),
        _case("c2", "maybe"),
        _case("c3", "yes"),
    ]
    predictions = [
        PredictionRecord(case_id="c1", predicted_label="yes"),
        PredictionRecord(case_id="c2", predicted_label="maybe"),
        PredictionRecord(case_id="c3", predicted_label="yes"),
    ]

    score = score_pubmedqa(cases, predictions, mode="mcp_oracle_pmid")

    assert score.score_details["maybe_decisive_overcall_count"] == 1
    assert score.score_details["maybe_decisive_overcall_rate"] == 0.5
