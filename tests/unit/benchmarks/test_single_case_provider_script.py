from __future__ import annotations

import json

from pubtator_link.benchmarks.models import BenchmarkCase, BenchmarkMode
from scripts.run_single_case_provider_benchmark import (
    _prediction_from_raw,
    _prompt_payload,
    _provider_command,
)


def test_prediction_from_raw_preserves_prompt_diagnostics() -> None:
    case = BenchmarkCase(
        dataset="pubmedqa",
        dataset_version="pqa_l_balanced_30_v1",
        case_id="case-1",
        question="Does the evidence support the claim?",
        gold_label="maybe",
        dataset_license="test",
        dataset_use_restriction="research_use",
    )
    provider_payload = {
        "case_id": "case-1",
        "predicted_label": "maybe",
        "evidence_status": "insufficient",
        "confidence": "low",
        "abstention_reason": "No direct evidence resolves the question.",
        "reason_short": "The supplied evidence is insufficient.",
    }
    raw = {
        "exit_status": 0,
        "stdout": json.dumps({"result": json.dumps(provider_payload)}),
        "stderr": "",
    }

    prediction = _prediction_from_raw(case, raw)

    assert prediction.predicted_label == "maybe"
    assert prediction.score_details == {
        "evidence_status": "insufficient",
        "confidence": "low",
        "abstention_reason": "No direct evidence resolves the question.",
    }


def test_no_tools_prompt_payload_excludes_abstract_context_and_gold_fields() -> None:
    case = BenchmarkCase(
        dataset="pubmedqa",
        dataset_version="pqa_l_balanced_30_v1",
        case_id="case-1",
        question="Does the evidence support the claim?",
        gold_label="yes",
        gold_answer={"long_answer": "Gold conclusion must not be rendered."},
        case_metadata={"abstract_context": "Non-gold abstract context."},
        dataset_license="test",
        dataset_use_restriction="research_use",
    )

    payload = _prompt_payload(case, BenchmarkMode.NO_TOOLS)

    assert payload == {
        "case_id": "case-1",
        "question": "Does the evidence support the claim?",
    }
    assert "gold_answer" not in payload
    assert "gold_label" not in payload


def test_mcp_prompt_payload_excludes_abstract_context_but_includes_pmids() -> None:
    case = BenchmarkCase(
        dataset="pubmedqa",
        dataset_version="pqa_l_balanced_30_v1",
        case_id="case-1",
        question="Does the evidence support the claim?",
        target_pmids=["123"],
        gold_evidence_pmids=["456"],
        gold_label="yes",
        gold_answer={"long_answer": "Gold conclusion must not be rendered."},
        case_metadata={"abstract_context": "Non-gold abstract context."},
        dataset_license="test",
        dataset_use_restriction="research_use",
    )

    payload = _prompt_payload(case, BenchmarkMode.MCP_ORACLE_PMID)

    assert payload == {
        "case_id": "case-1",
        "question": "Does the evidence support the claim?",
        "target_pmids": ["123"],
        "evidence_pmids": ["456"],
    }
    assert "abstract_context" not in payload
    assert "gold_answer" not in payload
    assert "gold_label" not in payload


def test_claude_no_mcp_command_allows_native_web_tools_without_pubtator_mcp() -> None:
    command = _provider_command(
        provider="claude",
        model="sonnet",
        prompt="Answer from your own capabilities. Do not use PubTator-Link MCP.",
    )

    assert "--tools" in command
    assert "WebSearch,WebFetch" in command
    assert "--allowedTools" not in command
    assert "mcp__pubtator-link" not in command


def test_claude_mcp_command_allows_pubtator_mcp() -> None:
    command = _provider_command(
        provider="claude",
        model="sonnet",
        prompt="Call pubtator.get_publication_passages.",
    )

    assert "--allowedTools" in command
    assert "mcp__pubtator-link" in command
