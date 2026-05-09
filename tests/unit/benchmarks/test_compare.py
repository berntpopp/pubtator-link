from __future__ import annotations

from decimal import Decimal

import pytest

from pubtator_link.benchmarks.compare import ComparableRun, compare_runs


def test_pairwise_comparison_requires_aligned_cases() -> None:
    left_run = ComparableRun(
        dataset="pubmedqa", dataset_version="v1", sample_seed=1, case_ids=["a"]
    )
    right_run = ComparableRun(
        dataset="pubmedqa", dataset_version="v1", sample_seed=1, case_ids=["b"]
    )

    with pytest.raises(ValueError, match="same case order"):
        compare_runs(left_run, right_run)


def test_mcnemar_counts_and_accuracy_delta() -> None:
    left_run = ComparableRun(
        dataset="pubmedqa",
        dataset_version="v1",
        sample_seed=1,
        case_ids=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        correct_by_case={
            "a": True,
            "b": True,
            "c": True,
            "d": True,
            "e": True,
            "f": True,
            "g": True,
            "h": False,
            "i": False,
            "j": False,
        },
    )
    right_run = ComparableRun(
        dataset="pubmedqa",
        dataset_version="v1",
        sample_seed=1,
        case_ids=left_run.case_ids,
        correct_by_case={
            "a": True,
            "b": True,
            "c": True,
            "d": True,
            "e": True,
            "f": False,
            "g": False,
            "h": False,
            "i": False,
            "j": False,
        },
    )

    comparison = compare_runs(left_run, right_run)

    assert comparison.mcnemar_b == 2
    assert comparison.mcnemar_c == 0
    assert comparison.accuracy_diff == Decimal("0.200000")
