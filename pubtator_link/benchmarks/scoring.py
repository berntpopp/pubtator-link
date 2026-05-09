from __future__ import annotations

import math
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from pubtator_link.benchmarks.models import (
    BenchmarkCase,
    BenchmarkScore,
    PredictionRecord,
    SourceAccess,
)

PUBMEDQA_LABELS = ("yes", "no", "maybe")
DANGEROUS_FLAGS = (
    "unsupported_claim",
    "contradicted_claim",
    "wrong_direction",
    "wrong_endpoint",
    "wrong_comparator",
    "wrong_population",
    "wrong_significance",
    "wrong_measure",
    "scope_inflation",
)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _wilson(correct: int, total: int) -> tuple[Decimal, Decimal]:
    if total == 0:
        return Decimal("0.000000"), Decimal("0.000000")
    z = 1.96
    p = correct / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    half = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return _decimal(max(0.0, centre - half)), _decimal(min(1.0, centre + half))


def score_pubmedqa(
    gold_cases: list[BenchmarkCase],
    predictions: list[PredictionRecord],
    *,
    mode: str | None = None,
) -> BenchmarkScore:
    by_case = {prediction.case_id: prediction for prediction in predictions}
    confusion = {gold: dict.fromkeys(PUBMEDQA_LABELS, 0) for gold in PUBMEDQA_LABELS}
    invalid = 0
    empty = 0
    correct = 0
    gold_distribution: Counter[str] = Counter()
    predicted_distribution: Counter[str] = Counter()
    for case in gold_cases:
        gold = case.gold_label or "maybe"
        prediction = by_case.get(case.case_id)
        predicted = prediction.predicted_label if prediction else None
        if prediction is None or predicted in (None, ""):
            empty += 1
            predicted = "invalid"
        if predicted not in PUBMEDQA_LABELS:
            invalid += 1
            predicted_distribution["invalid"] += 1
            continue
        gold_distribution[gold] += 1
        predicted_distribution[predicted] += 1
        confusion[gold][predicted] += 1
        if predicted == gold:
            correct += 1
    total = len(gold_cases)
    f1_by_class: dict[str, Decimal] = {}
    for label in PUBMEDQA_LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[gold][label] for gold in PUBMEDQA_LABELS if gold != label)
        fn = sum(confusion[label][predicted] for predicted in PUBMEDQA_LABELS if predicted != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_by_class[label] = _decimal(f1)
    accuracy = correct / total if total else 0.0
    ci_low, ci_high = _wilson(correct, total)
    return BenchmarkScore(
        dataset="pubmedqa",
        accuracy=_decimal(accuracy),
        wilson_ci_low=ci_low,
        wilson_ci_high=ci_high,
        macro_f1=_decimal(sum(float(value) for value in f1_by_class.values()) / len(f1_by_class)),
        f1_by_class=f1_by_class,
        confusion_matrix=confusion,
        label_distribution=dict(gold_distribution),
        predicted_label_distribution=dict(predicted_distribution),
        empty_output_count=empty,
        score_details={"invalid_label_count": invalid},
        pubmedqa_memorization_risk="high" if mode == "no_tools" and accuracy > 0.70 else None,
    )


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _token_f1(reference: str, candidate: str) -> float:
    ref = Counter(_tokens(reference))
    cand = Counter(_tokens(candidate))
    if not ref or not cand:
        return 0.0
    overlap = sum((ref & cand).values())
    precision = overlap / sum(cand.values())
    recall = overlap / sum(ref.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _rouge_l_f1(reference: str, candidate: str) -> float:
    ref = _tokens(reference)
    cand = _tokens(candidate)
    if not ref or not cand:
        return 0.0
    previous = [0] * (len(cand) + 1)
    for ref_token in ref:
        current = [0]
        for index, cand_token in enumerate(cand, start=1):
            current.append(
                previous[index - 1] + 1
                if ref_token == cand_token
                else max(previous[index], current[-1])
            )
        previous = current
    lcs = previous[-1]
    precision = lcs / len(cand)
    recall = lcs / len(ref)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def score_bioasq_ideal(
    gold_cases: list[BenchmarkCase],
    predictions: list[PredictionRecord],
) -> BenchmarkScore:
    by_case = {prediction.case_id: prediction for prediction in predictions}
    cited_gold = 0
    cited_total = 0
    required_total = 0
    token_f1s: list[float] = []
    rouge_l_f1s: list[float] = []
    access_counts = {access.value: 0 for access in SourceAccess}
    dangerous_counts = dict.fromkeys(DANGEROUS_FLAGS, 0)
    for case in gold_cases:
        prediction = by_case.get(case.case_id, PredictionRecord(case_id=case.case_id))
        gold_pmids = set(case.gold_evidence_pmids)
        cited_pmids = set(prediction.cited_pmids)
        cited_gold += len(cited_pmids & gold_pmids)
        cited_total += len(cited_pmids)
        required_total += len(gold_pmids)
        reference = str(case.gold_answer.get("reference_ideal_answer", ""))
        candidate = prediction.predicted_answer or ""
        token_f1s.append(_token_f1(reference, candidate))
        rouge_l_f1s.append(_rouge_l_f1(reference, candidate))
        for pmid in case.gold_evidence_pmids:
            access = case.source_access.get(pmid, SourceAccess.ABSTRACT_ONLY)
            access_counts[access.value] += 1
        for flag in DANGEROUS_FLAGS:
            if prediction.score_details.get(flag):
                dangerous_counts[flag] += 1
    access_total = sum(access_counts.values()) or 1
    details = {
        "citation_recall": cited_gold / required_total if required_total else 0.0,
        "citation_precision": cited_gold / cited_total if cited_total else 0.0,
        "mean_token_f1": sum(token_f1s) / len(token_f1s) if token_f1s else 0.0,
        "mean_rouge_l_f1": sum(rouge_l_f1s) / len(rouge_l_f1s) if rouge_l_f1s else 0.0,
    }
    return BenchmarkScore(
        dataset="bioasq_ideal",
        score_details=details,
        gold_source_access_rate={
            access: count / access_total for access, count in access_counts.items()
        },
        unsupported_claim_count=dangerous_counts["unsupported_claim"],
        contradicted_claim_count=dangerous_counts["contradicted_claim"],
        wrong_direction_count=dangerous_counts["wrong_direction"],
        wrong_endpoint_count=dangerous_counts["wrong_endpoint"],
        wrong_comparator_count=dangerous_counts["wrong_comparator"],
        wrong_population_count=dangerous_counts["wrong_population"],
        wrong_significance_count=dangerous_counts["wrong_significance"],
        wrong_measure_count=dangerous_counts["wrong_measure"],
        scope_inflation_count=dangerous_counts["scope_inflation"],
    )
