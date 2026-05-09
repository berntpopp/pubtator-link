from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from pubtator_link.benchmarks.models import PairwiseComparison


class ComparableRun(BaseModel):
    dataset: str
    dataset_version: str
    sample_seed: int
    case_ids: list[str]
    correct_by_case: dict[str, bool] = Field(default_factory=dict)
    prompt_version: str | None = None


def compare_runs(left: ComparableRun, right: ComparableRun) -> PairwiseComparison:
    if (
        left.dataset != right.dataset
        or left.dataset_version != right.dataset_version
        or left.sample_seed != right.sample_seed
    ):
        raise ValueError("runs must share dataset, dataset version, and sample seed")
    if left.case_ids != right.case_ids:
        raise ValueError("runs must have the same case order")
    b = 0
    c = 0
    left_correct = 0
    right_correct = 0
    for case_id in left.case_ids:
        left_value = left.correct_by_case.get(case_id, False)
        right_value = right.correct_by_case.get(case_id, False)
        left_correct += int(left_value)
        right_correct += int(right_value)
        if left_value and not right_value:
            b += 1
        elif right_value and not left_value:
            c += 1
    total = len(left.case_ids) or 1
    return PairwiseComparison(
        accuracy_diff=Decimal(str((left_correct - right_correct) / total)).quantize(
            Decimal("0.000001")
        ),
        mcnemar_b=b,
        mcnemar_c=c,
        mcnemar_p_value=_exact_mcnemar_p(b, c),
    )


def _exact_mcnemar_p(b: int, c: int) -> float | None:
    n = b + c
    if n == 0:
        return None
    smaller = min(b, c)
    probability = sum(_comb(n, index) * (0.5**n) for index in range(smaller + 1))
    return min(1.0, 2 * probability)


def _comb(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    result = 1
    for index in range(1, k + 1):
        result = result * (n - index + 1) // index
    return result
