"""Analyze focused provider benchmark artifacts and write a Markdown report."""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

LOGGER = logging.getLogger(__name__)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _provider_failed(row: dict[str, Any]) -> bool:
    if int(row.get("exit_status", 99)) == 0:
        return False
    stdout = str(row.get("stdout", ""))
    if stdout.strip().startswith("{"):
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return True
        return bool(parsed.get("is_error"))
    return True


def _raw_stats(path: Path, slowest_case_count: int) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    seconds = [float(row.get("seconds", 0.0)) for row in rows]
    errors = [row for row in rows if _provider_failed(row)]
    stderr_text = "\n".join(str(row.get("stderr", "")) for row in rows)
    stdout_text = "\n".join(str(row.get("stdout", "")) for row in rows)
    return {
        "rows": rows,
        "seconds_total": round(sum(seconds), 1),
        "seconds_mean": round(statistics.mean(seconds), 2) if seconds else 0.0,
        "seconds_median": round(statistics.median(seconds), 2) if seconds else 0.0,
        "error_count": len(errors),
        "error_cases": [row["case_id"] for row in errors],
        "tool_mentions": stderr_text.count("mcp_") + stdout_text.count("mcp_"),
        "quota_mentions": stderr_text.lower().count("quota")
        + stderr_text.lower().count("capacity"),
        "timeout_mentions": stderr_text.lower().count("timeout")
        + "\n".join(str(row.get("message", "")) for row in rows).lower().count("timed out"),
        "slowest_cases": [
            {"case_id": row["case_id"], "seconds": row.get("seconds", 0.0)}
            for row in sorted(rows, key=lambda item: float(item.get("seconds", 0.0)), reverse=True)[
                :slowest_case_count
            ]
        ],
    }


def _prediction_stats(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    source_access: dict[str, int] = {}
    experience_totals: dict[str, list[float]] = {}
    retrieved_pmids = 0
    cited_pmids = 0
    for row in rows:
        retrieved_pmids += len(row.get("retrieved_pmids", []))
        cited_pmids += len(row.get("cited_pmids", []))
        for value in row.get("source_access", {}).values():
            source_access[str(value)] = source_access.get(str(value), 0) + 1
        experience = row.get("score_details", {}).get("mcp_experience", {})
        if isinstance(experience, dict):
            for key, value in experience.items():
                if isinstance(value, int | float):
                    experience_totals.setdefault(key, []).append(float(value))
    return {
        "retrieved_pmids": retrieved_pmids,
        "cited_pmids": cited_pmids,
        "source_access": source_access,
        "mcp_experience": {
            key: round(statistics.mean(values), 2)
            for key, values in sorted(experience_totals.items())
            if values
        },
    }


def _run_records(root: Path, slowest_case_count: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for run_dir in sorted(item for item in root.iterdir() if item.is_dir()):
        manifest_path = run_dir / "manifest.json"
        scores_path = run_dir / "scores.json"
        raw_path = run_dir / "raw.jsonl"
        predictions_path = run_dir / "predictions.jsonl"
        if (
            not manifest_path.exists()
            or not scores_path.exists()
            or not raw_path.exists()
            or not predictions_path.exists()
        ):
            continue
        manifest = _load_json(manifest_path)
        scores = _load_json(scores_path)
        records.append(
            {
                "run_dir": run_dir,
                "manifest": manifest,
                "scores": scores,
                "raw": _raw_stats(raw_path, slowest_case_count),
                "predictions": _prediction_stats(predictions_path),
            }
        )
    return records


def _score_summary(record: dict[str, Any]) -> str:
    scores = record["scores"]
    if record["manifest"]["dataset"] == "pubmedqa":
        return (
            f"accuracy {float(scores['accuracy']):.3f}, "
            f"macro F1 {float(scores['macro_f1']):.3f}, "
            f"invalid {scores['score_details']['invalid_label_count']}"
        )
    details = scores["score_details"]
    return (
        f"citation recall {details['citation_recall']:.3f}, "
        f"citation precision {details['citation_precision']:.3f}, "
        f"token F1 {details['mean_token_f1']:.3f}, "
        f"ROUGE-L {details['mean_rouge_l_f1']:.3f}"
    )


def _run_label(manifest: dict[str, Any]) -> str:
    prompt_version = manifest.get("prompt_version")
    if prompt_version:
        return f"{manifest['suite']} ({prompt_version})"
    return str(manifest["suite"])


def _pubmedqa_details(scores: dict[str, Any]) -> list[str]:
    lines = ["", "#### PubMedQA Class Metrics", ""]
    lines.append("| Class | F1 |")
    lines.append("| --- | ---: |")
    for label, value in scores["f1_by_class"].items():
        lines.append(f"| {label} | {float(value):.3f} |")
    lines.extend(["", "Confusion matrix rows are gold labels and columns are predictions.", ""])
    labels = list(scores["confusion_matrix"].keys())
    lines.append("| Gold | " + " | ".join(labels) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
    for gold_label, predictions in scores["confusion_matrix"].items():
        lines.append(
            f"| {gold_label} | "
            + " | ".join(str(predictions.get(predicted_label, 0)) for predicted_label in labels)
            + " |"
        )
    return lines


def _paired_deltas(records: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## No-MCP vs MCP Deltas", ""]
    by_pair: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    for record in records:
        manifest = record["manifest"]
        key = (manifest["suite"], manifest["dataset"], manifest["provider"])
        mode = "mcp" if manifest.get("tool_workflow") not in (None, "", "none") else "no_mcp"
        by_pair.setdefault(key, {})[mode] = record
    rows: list[str] = []
    for (_suite, dataset, provider), pair in sorted(by_pair.items()):
        if "no_mcp" not in pair or "mcp" not in pair:
            continue
        left = pair["no_mcp"]
        right = pair["mcp"]
        if dataset == "pubmedqa":
            left_score = float(left["scores"]["macro_f1"])
            right_score = float(right["scores"]["macro_f1"])
            metric = "macro F1"
        else:
            left_score = float(left["scores"]["score_details"]["mean_rouge_l_f1"])
            right_score = float(right["scores"]["score_details"]["mean_rouge_l_f1"])
            metric = "ROUGE-L"
        rows.append(
            "| "
            f"{dataset} | {provider} | {metric} | {left_score:.3f} | {right_score:.3f} | "
            f"{right_score - left_score:+.3f} | "
            f"{left['raw']['seconds_mean']:.2f} | {right['raw']['seconds_mean']:.2f} | "
            f"{right['predictions']['retrieved_pmids']} | {right['predictions']['cited_pmids']} |"
        )
    if not rows:
        lines.append("No paired no-MCP/MCP runs found yet.")
        return lines
    lines.append(
        "| Dataset | Provider | Metric | No MCP | MCP | Delta | No MCP sec/case | MCP sec/case | Retrieved PMIDs | Cited PMIDs |"
    )
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.extend(rows)
    return lines


def _mcp_experience_details(records: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## MCP Experience Signals", ""]
    any_experience = False
    for record in records:
        manifest = record["manifest"]
        if manifest.get("tool_workflow") in (None, "", "none"):
            continue
        predictions = record["predictions"]
        any_experience = True
        lines.append(f"### {_run_label(manifest)}")
        lines.append("")
        lines.append(f"- retrieved PMIDs: {predictions['retrieved_pmids']}")
        lines.append(f"- cited PMIDs: {predictions['cited_pmids']}")
        lines.append(f"- source access counts: {predictions['source_access']}")
        if predictions["mcp_experience"]:
            lines.append("")
            lines.append("| Dimension | Mean Rating |")
            lines.append("| --- | ---: |")
            for key, value in predictions["mcp_experience"].items():
                lines.append(f"| {key} | {value:.2f} |")
        lines.append("")
    if not any_experience:
        lines.append("No MCP runs with structured MCP experience fields found yet.")
    return lines


def render_report(records: list[dict[str, Any]], title: str) -> str:
    lines = [f"# {title}", ""]
    lines.append("## Runs")
    lines.append("")
    lines.append(
        "| Suite | Mode | Provider | Model | Cases | Deterministic Scores | Errors | Tool Mentions | Mean sec/case |"
    )
    lines.append("| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: |")
    for record in records:
        manifest = record["manifest"]
        raw = record["raw"]
        lines.append(
            "| "
            f"{_run_label(manifest)} | {manifest['mode']} | {manifest['provider']} | {manifest['model']} | "
            f"{manifest['case_count']} | {_score_summary(record)} | "
            f"{raw['error_count']} | {raw['tool_mentions']} | {raw['seconds_mean']:.2f} |"
        )
    lines.extend(["", "## Error And Logging Analysis", ""])
    for record in records:
        manifest = record["manifest"]
        raw = record["raw"]
        lines.append(f"### {_run_label(manifest)} / {manifest['provider']} / {manifest['model']}")
        lines.append("")
        if manifest.get("tool_workflow"):
            lines.append(f"- tool workflow: {manifest['tool_workflow']}")
        if manifest.get("prompt_path"):
            lines.append(f"- prompt path: {manifest['prompt_path']}")
        lines.append(f"- total runtime seconds: {raw['seconds_total']}")
        lines.append(f"- median seconds per case: {raw['seconds_median']}")
        lines.append(f"- provider error count: {raw['error_count']}")
        lines.append(f"- timeout mentions: {raw['timeout_mentions']}")
        lines.append(f"- quota/capacity mentions: {raw['quota_mentions']}")
        lines.append(f"- MCP/tool mentions in raw provider logs: {raw['tool_mentions']}")
        if raw["slowest_cases"]:
            slowest = ", ".join(
                f"{item['case_id']} ({float(item['seconds']):.1f}s)"
                for item in raw["slowest_cases"]
            )
            lines.append(f"- slowest cases: {slowest}")
        if raw["error_cases"]:
            lines.append(f"- error cases: {', '.join(raw['error_cases'])}")
        lines.append("")
    lines.extend(_paired_deltas(records))
    lines.extend(_mcp_experience_details(records))
    for record in records:
        if record["manifest"]["dataset"] == "pubmedqa":
            lines.extend(_pubmedqa_details(record["scores"]))
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--artifact-root")
    parser.add_argument("--output")
    parser.add_argument("--title")
    args = parser.parse_args()
    if args.config:
        config = yaml.safe_load(Path(args.config).read_text())
        args.artifact_root = args.artifact_root or config["artifact_root"]
        args.output = args.output or config["report_path"]
        analysis_config = config.get("analysis", {})
        args.title = args.title or analysis_config.get("title", "Focused Benchmark Report")
        slowest_case_count = int(analysis_config.get("slowest_case_count", 0))
    else:
        slowest_case_count = 0
    if not args.artifact_root or not args.output:
        parser.error("--artifact-root and --output are required without --config")
    title = args.title or "Focused Benchmark Report"
    records = _run_records(Path(args.artifact_root), slowest_case_count)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(render_report(records, title))
    LOGGER.info("%s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
