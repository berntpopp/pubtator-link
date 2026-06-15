from __future__ import annotations

from pathlib import Path

import pytest

from pubtator_link.benchmarks.log_parser import analyze_events, parse_cli_events
from pubtator_link.benchmarks.models import BenchmarkScore, RunMetadata
from pubtator_link.benchmarks.summaries import render_combined_summary, render_summary


def test_codex_event_parser_extracts_mcp_tool_calls() -> None:
    events = parse_cli_events(Path("tests/fixtures/benchmarks/codex_mcp.events.jsonl"))

    assert events.tool_calls[0].tool_name == "get_publication_passages"
    assert events.tool_calls[0].coverage_summary["abstract_only"] == 10


def test_no_tools_summary_records_zero_mcp_calls() -> None:
    analysis = analyze_events([])

    assert analysis.mcp_tool_call_count == 0


def test_summary_includes_source_access_and_dangerous_errors() -> None:
    run = RunMetadata(
        run_id="run-1",
        suite="bioasq_ideal_smoke",
        dataset="bioasq_ideal",
        mode="no_tools",
        sample_seed=20260509,
    )
    scores = BenchmarkScore(
        dataset="bioasq_ideal",
        score_details={"citation_recall": 1.0},
        gold_source_access_rate={"abstract_only": 1.0},
        wrong_direction_count=0,
    )
    analysis = analyze_events([])

    text = render_summary(run, scores, analysis)

    assert "Source Access" in text
    assert "abstract_only" in text
    assert "wrong_direction_count" in text


def test_summary_highlights_source_coverage_counts_before_scores() -> None:
    run = RunMetadata(
        run_id="run-coverage",
        suite="pubmedqa_full_text_smoke",
        dataset="pubmedqa",
        mode="mcp_oracle_pmid",
        sample_seed=20260509,
    )
    scores = BenchmarkScore(
        dataset="pubmedqa",
        accuracy=0.75,
        macro_f1=0.74,
        gold_source_access_rate={"full_text": 0.5, "abstract_only": 0.5},
        score_details={"source_access_counts": {"full_text": 6, "abstract_only": 6}},
    )
    analysis = analyze_events([])

    text = render_summary(run, scores, analysis)

    assert text.index("## Source Coverage Counts") < text.index("## Label Metrics")
    assert "- full_text: 6" in text
    assert "- abstract_only: 6" in text


def test_summary_refuses_mixed_dataset_combined_accuracy() -> None:
    pubmedqa_scores = BenchmarkScore(dataset="pubmedqa")
    bioasq_scores = BenchmarkScore(dataset="bioasq_ideal")

    with pytest.raises(ValueError, match="mixed datasets"):
        render_combined_summary([pubmedqa_scores, bioasq_scores], combine_mixed_task=False)
