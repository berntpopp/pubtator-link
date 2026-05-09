from __future__ import annotations

from pubtator_link.benchmarks.log_parser import EventAnalysis
from pubtator_link.benchmarks.models import BenchmarkScore, RunMetadata


def render_summary(run: RunMetadata, scores: BenchmarkScore, analysis: EventAnalysis) -> str:
    lines = [
        f"# Benchmark Summary: {run.suite}",
        "",
        f"- run_id: {run.run_id}",
        f"- dataset: {run.dataset}",
        f"- mode: {run.mode}",
        f"- sample_seed: {run.sample_seed}",
        f"- answer_stack: {run.answer_stack or ''}",
        f"- mcp_tool_call_count: {analysis.mcp_tool_call_count}",
        "",
    ]
    if scores.accuracy is not None:
        lines.extend(
            [
                "## Label Metrics",
                f"- accuracy: {scores.accuracy}",
                f"- wilson_ci: [{scores.wilson_ci_low}, {scores.wilson_ci_high}]",
                f"- macro_f1: {scores.macro_f1}",
                "",
            ]
        )
    lines.extend(["## Source Access"])
    for key, value in sorted(scores.gold_source_access_rate.items()):
        lines.append(f"- {key}: {value:.6f}")
    lines.extend(
        [
            "",
            "## Dangerous Error Counts",
            f"- unsupported_claim_count: {scores.unsupported_claim_count}",
            f"- contradicted_claim_count: {scores.contradicted_claim_count}",
            f"- wrong_direction_count: {scores.wrong_direction_count}",
            f"- wrong_endpoint_count: {scores.wrong_endpoint_count}",
            f"- wrong_comparator_count: {scores.wrong_comparator_count}",
            f"- wrong_population_count: {scores.wrong_population_count}",
            f"- wrong_significance_count: {scores.wrong_significance_count}",
            f"- wrong_measure_count: {scores.wrong_measure_count}",
            f"- scope_inflation_count: {scores.scope_inflation_count}",
            "",
        ]
    )
    if scores.score_details:
        lines.append("## Score Details")
        for key, value in sorted(scores.score_details.items()):
            lines.append(f"- {key}: {value}")
        lines.append("")
    if run.dataset_drift_detected:
        lines.append("PubTator drift warning: dataset drift detected for this run.")
    return "\n".join(lines)


def render_combined_summary(
    scores: list[BenchmarkScore],
    *,
    combine_mixed_task: bool = False,
) -> str:
    datasets = {score.dataset for score in scores}
    if len(datasets) > 1 and not combine_mixed_task:
        raise ValueError("mixed datasets cannot be combined by default")
    return "\n".join(f"- {score.dataset}: {score.accuracy}" for score in scores)
