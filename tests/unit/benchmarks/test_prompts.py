from __future__ import annotations

import hashlib
from pathlib import Path

from pubtator_link.benchmarks.cases import load_cases
from pubtator_link.benchmarks.models import BenchmarkMode
from pubtator_link.benchmarks.prompts import load_prompt_template, render_prompt


def test_prompt_hash_is_sha256_of_template_bytes() -> None:
    path = Path("benchmarks/prompts/answer_pubmedqa_article_local_v1.md")

    template = load_prompt_template(path)

    assert template.template_hash == hashlib.sha256(path.read_bytes()).hexdigest()


def test_render_pubmedqa_prompt_hides_gold() -> None:
    template_path = Path("benchmarks/prompts/answer_pubmedqa_article_local_v1.md")
    prompt_context = [
        case.to_prompt_context(BenchmarkMode.NO_TOOLS)
        for case in load_cases(Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl"))[:1]
    ]

    prompt = render_prompt(template_path, prompt_context)

    assert "gold_label" not in prompt.text
    assert "yes" not in prompt.text.lower().split("gold", 1)[-1]
    assert len(prompt.resolved_hash) == 64


def test_pubmedqa_mcp_prompt_mentions_full_abstract_and_maybe_calibration() -> None:
    prompt = Path("benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md").read_text()

    assert "mode='full_abstract'" in prompt
    assert "If preflight fails, call pubtator.get_publication_passages" in prompt
    assert (
        "Do not convert conditional, underpowered, mixed, or method-limited evidence into yes/no"
        in prompt
    )
