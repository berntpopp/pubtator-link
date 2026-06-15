"""Run benchmark cases one prediction at a time for live provider CLIs."""

from __future__ import annotations

import argparse
import ast
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from pubtator_link.benchmarks.cases import load_cases, load_suite
from pubtator_link.benchmarks.models import BenchmarkCase, BenchmarkMode, PredictionRecord
from pubtator_link.benchmarks.scoring import score_bioasq_ideal, score_pubmedqa

LOGGER = logging.getLogger(__name__)


def _json_object_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S)
    if fence:
        stripped = fence.group(1).strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(stripped)
            except (SyntaxError, ValueError):
                parsed = json.loads(stripped.replace("\\n", "\n").replace('\\"', '"'))
        if isinstance(parsed, dict):
            return parsed
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidate = stripped[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(candidate)
            except (SyntaxError, ValueError):
                parsed = json.loads(candidate.replace("\\n", "\n").replace('\\"', '"'))
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object found")


def _prompt_payload(case: BenchmarkCase, mode: BenchmarkMode) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "question": case.question,
    }
    if mode != BenchmarkMode.NO_TOOLS:
        payload["target_pmids"] = case.target_pmids
        payload["evidence_pmids"] = case.gold_evidence_pmids
    return payload


def _case_prompt(case: BenchmarkCase, mode: BenchmarkMode, prompt_template: str | None) -> str:
    payload = _prompt_payload(case, mode)
    if prompt_template is not None:
        return prompt_template.replace("{{ case_json }}", json.dumps(payload, sort_keys=True))
    if case.dataset == "pubmedqa":
        return (
            "Answer one PubMedQA article-local benchmark case. "
            "Return JSON only with exactly these keys: "
            '{"case_id":"...","predicted_label":"yes|no|maybe","cited_pmids":[],"reason_short":"..."}. '
            "Do not include markdown.\n\n"
            f"Case:\n{json.dumps(payload, sort_keys=True)}"
        )
    return (
        "Answer one BioASQ ideal-answer benchmark case for research diagnostics. "
        "Return JSON only with exactly these keys: "
        '{"case_id":"...","predicted_answer":"...","cited_pmids":[],"claims":[{"text":"...","cited_pmids":[]}]}. '
        "Do not provide clinical advice. Do not include markdown.\n\n"
        f"Case:\n{json.dumps(payload, sort_keys=True)}"
    )


def _prompt_references_pubtator_mcp(prompt: str) -> bool:
    """Detect whether a prompt asks the model to use the PubTator-Link MCP surface.

    Tool names are unprefixed under the GeneFoundry Tool-Naming Standard v1, so we
    match the gateway/client namespace token (``mcp__pubtator-link``) or any known
    registered tool name as a whole word. Plain mentions like "PubTator-Link MCP"
    in a *negative* instruction must not trigger MCP access.
    """
    from pubtator_link.mcp.profiles import tool_names_for_profile

    if "mcp__pubtator-link" in prompt:
        return True
    known_tools = tool_names_for_profile("full")
    tokens = set(re.findall(r"[a-z][a-z0-9_]*", prompt))
    return bool(tokens & known_tools)


def _provider_command(provider: str, model: str, prompt: str) -> list[str]:
    if provider == "claude":
        command = [
            "claude",
            "--print",
            "--disable-slash-commands",
            "--output-format",
            "json",
            "--permission-mode",
            "bypassPermissions",
            "--model",
            model,
            prompt,
        ]
        if _prompt_references_pubtator_mcp(prompt):
            command[2:2] = ["--allowedTools", "mcp__pubtator-link"]
        else:
            command[2:2] = ["--tools", "WebSearch,WebFetch"]
    elif provider == "codex":
        command = [
            "codex",
            "--ask-for-approval",
            "never",
            "exec",
            "--cd",
            ".",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--model",
            model,
            prompt,
        ]
    elif provider == "gemini":
        command = [
            "gemini",
            "--skip-trust",
            "--model",
            model,
            "--allowed-mcp-server-names",
            "",
            "--output-format",
            "json",
            "--prompt",
            prompt,
        ]
    else:
        raise ValueError(f"unknown provider: {provider}")
    return command


def _run_provider(provider: str, model: str, prompt: str, timeout_s: int) -> dict[str, Any]:
    command = _provider_command(provider, model, prompt)
    started = time.monotonic()
    completed = subprocess.run(  # noqa: S603 - provider command is selected from fixed adapters.
        command,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return {
        "command": command[:2],
        "exit_status": completed.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _prediction_from_raw(case: BenchmarkCase, raw: dict[str, Any]) -> PredictionRecord:
    if raw["exit_status"] != 0 and not raw.get("stdout"):
        return PredictionRecord(
            case_id=case.case_id, score_details={"provider_error": raw["stderr"]}
        )
    text = raw["stdout"]
    if text.strip().startswith("{"):
        outer = _json_object_from_text(text)
        text = str(outer.get("result") or outer.get("response") or outer.get("content") or text)
    parsed = _json_object_from_text(text)
    score_details = {
        key: parsed[key]
        for key in (
            "evidence_status",
            "confidence",
            "abstention_reason",
            "tool_workflow",
            "mcp_experience",
        )
        if key in parsed
    }
    return PredictionRecord(
        case_id=str(parsed.get("case_id") or case.case_id),
        predicted_label=parsed.get("predicted_label"),
        predicted_answer=parsed.get("predicted_answer") or parsed.get("answer"),
        cited_pmids=[str(value) for value in parsed.get("cited_pmids", [])],
        retrieved_pmids=[str(value) for value in parsed.get("retrieved_pmids", [])],
        source_access=parsed.get("source_access", {}),
        claims=list(parsed.get("claims", [])) if isinstance(parsed.get("claims", []), list) else [],
        reason_short=parsed.get("reason_short"),
        score_details=score_details,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--run-name")
    parser.add_argument("--suite")
    parser.add_argument(
        "--mode", default="no_tools", choices=[mode.value for mode in BenchmarkMode]
    )
    parser.add_argument("--provider", choices=["claude", "codex", "gemini"])
    parser.add_argument("--model")
    parser.add_argument("--artifact-dir", default="benchmarks/results/single-case-provider")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-version")
    parser.add_argument("--tool-workflow", default="none")
    args = parser.parse_args()

    if args.config:
        cli_max_cases = args.max_cases
        cli_timeout_s = args.timeout_s
        config = yaml.safe_load(Path(args.config).read_text())
        matching_runs = [
            run
            for run in config["runs"]
            if args.run_name is None or run["run_name"] == args.run_name
        ]
        if len(matching_runs) != 1:
            raise ValueError("--config requires exactly one matching --run-name")
        run_config = matching_runs[0]
        args.suite = run_config["suite"]
        args.mode = run_config.get("mode", args.mode)
        args.provider = run_config["provider"]
        args.model = run_config["model"]
        args.artifact_dir = config["artifact_root"]
        args.max_cases = run_config.get("max_cases")
        args.timeout_s = run_config.get("timeout_s", args.timeout_s)
        args.prompt_path = run_config["prompt"]
        args.prompt_version = run_config.get("prompt_version", Path(args.prompt_path).stem)
        args.tool_workflow = run_config.get("tool_workflow", "none")
        if cli_max_cases is not None:
            args.max_cases = cli_max_cases
        if cli_timeout_s != parser.get_default("timeout_s"):
            args.timeout_s = cli_timeout_s
        args.prompt_template = Path(args.prompt_path).read_text()
    else:
        args.prompt_path = args.prompt
        args.prompt_version = args.prompt_version or (
            Path(args.prompt_path).stem if args.prompt_path else None
        )
        args.prompt_template = Path(args.prompt_path).read_text() if args.prompt_path else None
    if not args.suite or not args.provider or not args.model:
        parser.error("--suite, --provider, and --model are required without --config")

    suite = load_suite(Path(args.suite))
    mode = BenchmarkMode(args.mode)
    cases = load_cases(suite.case_file)
    if args.max_cases is not None:
        cases = cases[: args.max_cases]

    run_id = f"{suite.name}-{mode.value}-{args.provider}-{int(time.time())}"
    out_dir = Path(args.artifact_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "suite": suite.name,
                "dataset": suite.dataset,
                "dataset_version": suite.dataset_version,
                "mode": mode.value,
                "provider": args.provider,
                "model": args.model,
                "case_count": len(cases),
                "prompt_path": args.prompt_path,
                "prompt_version": args.prompt_version,
                "tool_workflow": args.tool_workflow,
            },
            indent=2,
            sort_keys=True,
        )
    )

    predictions: list[PredictionRecord] = []
    with (
        (out_dir / "raw.jsonl").open("w") as raw_file,
        (out_dir / "predictions.jsonl").open("w") as pred_file,
    ):
        for index, case in enumerate(cases, start=1):
            prompt = _case_prompt(case, mode, args.prompt_template)
            raw: dict[str, Any] = {}
            try:
                raw = _run_provider(args.provider, args.model, prompt, args.timeout_s)
                prediction = _prediction_from_raw(case, raw)
            except Exception as exc:
                raw = {
                    **raw,
                    "parse_error": type(exc).__name__,
                    "parse_message": str(exc),
                }
                prediction = PredictionRecord(
                    case_id=case.case_id,
                    score_details={"provider_error": f"{type(exc).__name__}: {exc}"},
                )
            raw_file.write(json.dumps({"case_id": case.case_id, "index": index, **raw}) + "\n")
            pred_file.write(prediction.model_dump_json() + "\n")
            raw_file.flush()
            pred_file.flush()
            predictions.append(prediction)
            LOGGER.info("%s/%s %s", index, len(cases), case.case_id)

    if suite.dataset == "pubmedqa":
        scores = score_pubmedqa(cases, predictions, mode=mode.value)
    else:
        scores = score_bioasq_ideal(cases, predictions)
    (out_dir / "scores.json").write_text(scores.model_dump_json(indent=2))
    LOGGER.info("%s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
