from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pubtator_link.benchmarks.cases import load_cases, load_suite, sample_cases
from pubtator_link.benchmarks.models import BenchmarkCase, BenchmarkMode


def test_load_suite_resolves_case_file_from_repo_root() -> None:
    suite = load_suite(Path("benchmarks/suites/pubmedqa_smoke.yaml"))

    assert suite.name == "pubmedqa_smoke"
    assert suite.case_file == Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl")


def test_load_full_text_smoke_suite_and_cases() -> None:
    suite = load_suite(Path("benchmarks/suites/pubmedqa_full_text_smoke.yaml"))
    cases = load_cases(suite.case_file)

    assert suite.name == "pubmedqa_full_text_smoke"
    assert suite.sampling_mode == "full_text_smoke_balanced"
    assert len(cases) == 12
    assert {case.gold_label for case in cases} == {"yes", "no", "maybe"}
    assert all(case.case_metadata["full_text_expected"] is True for case in cases)


def test_case_prompt_context_excludes_gold_label() -> None:
    case = load_cases(Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl"))[0]

    context = case.to_prompt_context(mode=BenchmarkMode.NO_TOOLS)

    assert "gold_label" not in context.model_dump()
    assert context.target_pmids == []


def test_seeded_sampling_is_stable() -> None:
    cases = load_cases(Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl"))

    assert [c.case_id for c in sample_cases(cases, seed=20260509, count=3)] == [
        "pubmedqa_21618245",
        "pubmedqa_12630042",
        "pubmedqa_24142776",
    ]


def test_pubmedqa_gold_label_is_constrained() -> None:
    with pytest.raises(ValidationError):
        BenchmarkCase(
            dataset="pubmedqa",
            dataset_version="pqa_l_article_local_v1",
            case_id="bad",
            question="Bad label?",
            gold_label="unclear",
            dataset_license="test",
            dataset_use_restriction="research_use",
        )
