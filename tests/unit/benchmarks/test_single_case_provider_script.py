from __future__ import annotations

import json

from pubtator_link.benchmarks.models import BenchmarkCase, BenchmarkMode
from scripts.run_single_case_provider_benchmark import _prediction_from_raw, _prompt_payload


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


def test_prompt_payload_includes_pubmedqa_context_without_gold_answer() -> None:
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

    assert payload["abstract_context"] == "Non-gold abstract context."
    assert "gold_answer" not in payload
    assert "gold_label" not in payload
