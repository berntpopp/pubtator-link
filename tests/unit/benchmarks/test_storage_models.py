from __future__ import annotations

import pytest
from pydantic import ValidationError

from pubtator_link.benchmarks.models import (
    BenchmarkScore,
    CliInvocation,
    PredictionJsonPayload,
    PredictionRecord,
    SelfJudgmentPayload,
    SourceAccess,
)
from pubtator_link.benchmarks.storage import jsonb_payload, validate_jsonb


def test_jsonb_models_include_schema_version() -> None:
    payload = CliInvocation(command=["claude", "--print"], env_hash="abc")

    assert payload.model_dump(by_alias=True)["_schema_version"] == 1


def test_cli_invocation_rejects_string_command() -> None:
    with pytest.raises(ValidationError):
        CliInvocation(command="claude --print", env_hash="abc")  # type: ignore[arg-type]


def test_source_access_values_are_closed_enum() -> None:
    assert SourceAccess("abstract_only") == SourceAccess.ABSTRACT_ONLY
    with pytest.raises(ValueError):
        SourceAccess("pdf_only")


def test_validate_jsonb_rejects_missing_schema_version() -> None:
    with pytest.raises(ValidationError):
        validate_jsonb(CliInvocation, {"command": ["claude"], "env_hash": "abc"})


def test_prediction_payload_jsonb_is_versioned() -> None:
    payload = PredictionJsonPayload(prediction=PredictionRecord(case_id="case_1"))

    stored = jsonb_payload(PredictionJsonPayload, payload)

    assert stored["_schema_version"] == 1
    assert stored["prediction"]["case_id"] == "case_1"


def test_score_payload_jsonb_is_versioned() -> None:
    payload = jsonb_payload(BenchmarkScore, BenchmarkScore(dataset="pubmedqa"))

    assert payload["_schema_version"] == 1


def test_self_judgment_requires_trace_bound_dimensions() -> None:
    payload = SelfJudgmentPayload.model_validate(
        {
            "_schema_version": 1,
            "dimensions": {
                "argument_clarity": {
                    "score": 8,
                    "rationale": "The trace explains evidence use.",
                }
            },
            "overall_score": 7,
            "recommendations": ["Tighten prompts."],
        }
    )

    assert payload.dimensions["argument_clarity"].score == 8
    assert payload.overall_score == 7


def test_self_judgment_rejects_unknown_dimension() -> None:
    raw_payload = {
        "_schema_version": 1,
        "dimensions": {"clinical_accuracy": {"score": 10}},
        "overall_score": 7,
    }

    with pytest.raises(ValidationError):
        SelfJudgmentPayload.model_validate(raw_payload)
