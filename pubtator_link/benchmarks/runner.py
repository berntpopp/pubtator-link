from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from pubtator_link.benchmarks.adapters import AdapterRequest, adapter_registry, parse_answer_stack
from pubtator_link.benchmarks.artifacts import ArtifactBundleWriter
from pubtator_link.benchmarks.cases import load_cases, load_suite, sample_cases
from pubtator_link.benchmarks.log_parser import EventAnalysis, analyze_events
from pubtator_link.benchmarks.models import (
    BenchmarkCase,
    BenchmarkMode,
    BenchmarkScore,
    ModelSettings,
    PredictionRecord,
    RunManifest,
    RunMetadata,
)
from pubtator_link.benchmarks.prompts import render_prompt
from pubtator_link.benchmarks.scoring import score_bioasq_ideal, score_pubmedqa
from pubtator_link.benchmarks.storage import BenchmarkStorage
from pubtator_link.benchmarks.summaries import render_summary


def run_suite(
    *,
    suite_path: Path,
    answer_stack: str,
    artifact_dir: Path = Path("benchmarks/results"),
    mode: BenchmarkMode | None = None,
    case_count: int | None = None,
    no_db: bool = False,
    dry_run: bool = False,
    database_url: str | None = None,
) -> Path:
    del dry_run
    suite = load_suite(suite_path)
    selected_mode = mode or suite.modes[0]
    cases = sample_cases(
        load_cases(suite.case_file),
        seed=suite.sample_seed,
        count=case_count or suite.case_count,
    )
    contexts = [case.to_prompt_context(selected_mode) for case in cases]
    prompt_path = Path(suite.prompt_versions["answer"])
    rendered_prompt = render_prompt(prompt_path, contexts)
    stack = parse_answer_stack(answer_stack)
    adapter = adapter_registry()[stack.adapter]
    run_id = uuid4()
    writer = ArtifactBundleWriter(root=artifact_dir, run_id=run_id, suite=suite.name)
    result = adapter.run(
        AdapterRequest(
            prompt=rendered_prompt,
            cases=cases,
            mode=selected_mode,
            model=stack.model,
            output_dir=writer.path,
            timeout_s=suite.defaults.timeout_s,
        )
    )
    benchmark_events: list[dict[str, object]] = [
        {
            "event_type": "benchmark_adapter_completed",
            "adapter": stack.adapter,
            "requested_model": stack.model,
            "resolved_model": result.resolved_model,
            "exit_status": result.exit_status,
            "prediction_count": len(result.predictions),
        },
        *result.events,
    ]
    manifest = RunManifest(
        run_id=str(run_id),
        suite=suite.name,
        dataset=suite.dataset,
        dataset_version=suite.dataset_version,
        mode=selected_mode,
        sample_seed=suite.sample_seed,
        case_ids=[case.case_id for case in cases],
        prompt_template_hash=rendered_prompt.template_hash,
        prompt_resolved_hash=rendered_prompt.resolved_hash,
        answer_stack=answer_stack,
        model_settings=ModelSettings(adapter=stack.adapter, requested_model=stack.model),
    )
    if suite.dataset == "pubmedqa":
        scores = score_pubmedqa(cases, result.predictions, mode=selected_mode.value)
    else:
        scores = score_bioasq_ideal(cases, result.predictions)
    analysis = analyze_events(result.events)
    run_metadata = RunMetadata(
        run_id=str(run_id),
        suite=suite.name,
        dataset=suite.dataset,
        dataset_version=suite.dataset_version,
        mode=selected_mode.value,
        sample_seed=suite.sample_seed,
        answer_stack=answer_stack,
        adapter=stack.adapter,
        requested_model=stack.model,
        resolved_model=result.resolved_model,
        prompt_template_hash=rendered_prompt.template_hash,
        prompt_resolved_hash=rendered_prompt.resolved_hash,
    )
    writer.write_json("manifest.json", manifest.model_dump(mode="json", by_alias=True))
    writer.write_cases(cases)
    writer.write_predictions(result.predictions)
    writer.write_json("scores.json", scores.model_dump(mode="json"))
    writer.write_json("answer_output.json", result.raw_output)
    writer.write_text(
        "answer_events.jsonl",
        "".join(f"{json.dumps(event, sort_keys=True)}\n" for event in result.events),
    )
    writer.write_text("answer_debug.log", "")
    writer.write_text("prompt_answer.md", rendered_prompt.text)
    writer.write_text("summary.md", render_summary(run_metadata, scores, analysis))
    writer.write_json(
        "artifacts.json",
        [record.model_dump(mode="json") for record in writer.finalize_artifact_records()],
    )
    if not no_db and database_url:
        storage = BenchmarkStorage(database_url)
        asyncio.run(
            _persist_run(
                storage,
                manifest,
                cases,
                selected_mode,
                result.predictions,
                scores,
                benchmark_events,
                analysis,
            )
        )
    return writer.path


async def _persist_run(
    storage: BenchmarkStorage,
    manifest: RunManifest,
    cases: list[BenchmarkCase],
    mode: BenchmarkMode,
    predictions: list[PredictionRecord],
    scores: BenchmarkScore,
    events: list[dict[str, object]],
    analysis: EventAnalysis,
) -> None:
    await storage.insert_run(manifest)
    await storage.insert_cases(manifest.run_id, cases, mode)
    await storage.insert_predictions(manifest.run_id, predictions)
    await storage.insert_scores(manifest.run_id, scores)
    await storage.insert_log_events(manifest.run_id, events)
    await storage.insert_tool_calls(manifest.run_id, analysis.tool_calls)
