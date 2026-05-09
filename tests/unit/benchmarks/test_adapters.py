from __future__ import annotations

from pathlib import Path

from pubtator_link.benchmarks.adapters import (
    AdapterRequest,
    DryRunAdapter,
    adapter_registry,
    parse_answer_stack,
)
from pubtator_link.benchmarks.cases import load_cases
from pubtator_link.benchmarks.models import BenchmarkMode
from pubtator_link.benchmarks.prompts import RenderedPrompt


def test_parse_answer_stack() -> None:
    stack = parse_answer_stack("codex_cli:gpt-5.4")

    assert stack.adapter == "codex_cli"
    assert stack.model == "gpt-5.4"


def test_dry_run_adapter_returns_one_prediction_per_case() -> None:
    cases = load_cases(Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl"))[:2]
    prompt = RenderedPrompt(text="{}", template_hash="a" * 64, resolved_hash="b" * 64)

    result = DryRunAdapter().run(
        AdapterRequest(prompt=prompt, cases=cases, mode=BenchmarkMode.NO_TOOLS)
    )

    assert result.exit_status == 0
    assert [p.case_id for p in result.predictions] == [c.case_id for c in cases]


def test_adapter_registry_exposes_required_adapters() -> None:
    assert set(adapter_registry()) >= {"claude_code", "codex_cli", "gemini_cli", "dry_run"}
