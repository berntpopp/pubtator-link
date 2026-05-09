from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceAccess(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    METADATA_ONLY = "metadata_only"
    MISSING = "missing"


class BenchmarkMode(StrEnum):
    NO_TOOLS = "no_tools"
    ORACLE_CONTEXT = "oracle_context"
    MCP_ORACLE_PMID = "mcp_oracle_pmid"
    MCP_OPEN_RETRIEVAL = "mcp_open_retrieval"


class VersionedJsonModel(BaseModel):
    schema_version: int = Field(default=1, alias="_schema_version")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SuiteDefaults(BaseModel):
    timeout_s: int | None = None
    max_cases_per_run: int | None = None
    mcp_endpoint: str | None = None


class SuiteConfig(BaseModel):
    name: str
    dataset: str
    dataset_version: str
    case_file: Path
    modes: list[BenchmarkMode]
    sample_seed: int
    case_count: int
    sampling_mode: Literal["balanced", "natural"]
    prompt_versions: dict[str, str]
    defaults: SuiteDefaults = Field(default_factory=SuiteDefaults)


class PromptContext(BaseModel):
    dataset: str
    dataset_version: str
    case_id: str
    question: str
    target_pmids: list[str] = Field(default_factory=list)
    evidence_pmids: list[str] = Field(default_factory=list)
    case_metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkCase(BaseModel):
    dataset: str
    dataset_version: str
    case_id: str
    question: str
    target_pmids: list[str] = Field(default_factory=list)
    gold_label: Literal["yes", "no", "maybe"] | None = None
    gold_answer: dict[str, Any] = Field(default_factory=dict)
    gold_evidence_pmids: list[str] = Field(default_factory=list)
    source_access: dict[str, SourceAccess] = Field(default_factory=dict)
    dataset_license: str
    dataset_use_restriction: str
    case_metadata: dict[str, Any] = Field(default_factory=dict)

    def to_prompt_context(self, mode: BenchmarkMode) -> PromptContext:
        expose_pmids = mode != BenchmarkMode.NO_TOOLS
        return PromptContext(
            dataset=self.dataset,
            dataset_version=self.dataset_version,
            case_id=self.case_id,
            question=self.question,
            target_pmids=self.target_pmids if expose_pmids else [],
            evidence_pmids=self.gold_evidence_pmids if expose_pmids else [],
            case_metadata=self.case_metadata,
        )


class GoldCase(BaseModel):
    case_id: str
    gold_label: str | None = None
    gold_answer: dict[str, Any] = Field(default_factory=dict)
    gold_evidence_pmids: list[str] = Field(default_factory=list)


class PredictionRecord(BaseModel):
    case_id: str
    predicted_label: str | None = None
    predicted_answer: str | None = None
    cited_pmids: list[str] = Field(default_factory=list)
    retrieved_pmids: list[str] = Field(default_factory=list)
    source_access: dict[str, SourceAccess] = Field(default_factory=dict)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    reason_short: str | None = None
    score_details: dict[str, Any] = Field(default_factory=dict)


class PredictionJsonPayload(VersionedJsonModel):
    prediction: PredictionRecord


class ScoreDetails(VersionedJsonModel):
    metrics: dict[str, Any] = Field(default_factory=dict)


class BenchmarkScore(VersionedJsonModel):
    dataset: str
    accuracy: Decimal | None = None
    wilson_ci_low: Decimal | None = None
    wilson_ci_high: Decimal | None = None
    macro_f1: Decimal | None = None
    f1_by_class: dict[str, Decimal] = Field(default_factory=dict)
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    label_distribution: dict[str, int] = Field(default_factory=dict)
    predicted_label_distribution: dict[str, int] = Field(default_factory=dict)
    gold_source_access_rate: dict[str, float] = Field(default_factory=dict)
    score_details: dict[str, Any] = Field(default_factory=dict)
    empty_output_count: int = 0
    unsupported_claim_count: int = 0
    contradicted_claim_count: int = 0
    wrong_direction_count: int = 0
    wrong_endpoint_count: int = 0
    wrong_comparator_count: int = 0
    wrong_population_count: int = 0
    wrong_significance_count: int = 0
    wrong_measure_count: int = 0
    scope_inflation_count: int = 0
    pubmedqa_memorization_risk: str | None = None


class CliInvocation(VersionedJsonModel):
    command: list[str]
    cwd: str | None = None
    env_hash: str
    timeout_s: int | None = None

    @field_validator("command", mode="before")
    @classmethod
    def command_must_be_list(cls, value: object) -> object:
        if isinstance(value, str):
            raise ValueError("command must be a list of argv strings")
        return value


class ModelSettings(VersionedJsonModel):
    adapter: str
    requested_model: str
    resolved_model: str | None = None
    temperature: float | None = None


class TokenUsage(VersionedJsonModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class CliConfigSnapshot(VersionedJsonModel):
    adapter: str
    invocation: CliInvocation | None = None
    config_hash: str | None = None


class PubTatorApiHealth(VersionedJsonModel):
    checked: bool = False
    status: str | None = None


class RunMetadata(VersionedJsonModel):
    run_id: str
    suite: str
    dataset: str
    mode: str
    sample_seed: int
    dataset_version: str | None = None
    answer_stack: str | None = None
    adapter: str | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    prompt_template_hash: str | None = None
    prompt_resolved_hash: str | None = None
    dataset_drift_detected: bool = False


class RunManifest(VersionedJsonModel):
    run_id: str
    suite: str
    dataset: str
    dataset_version: str
    mode: BenchmarkMode
    sample_seed: int
    case_ids: list[str]
    prompt_template_hash: str
    prompt_resolved_hash: str
    answer_stack: str
    model_settings: ModelSettings


class ArtifactRecord(BaseModel):
    artifact_type: str
    relative_path: str
    sha256: str
    size_bytes: int


class PairwiseComparison(VersionedJsonModel):
    left_run_id: str | None = None
    right_run_id: str | None = None
    metric: str = "accuracy"
    accuracy_diff: Decimal = Decimal("0.000000")
    mcnemar_b: int = 0
    mcnemar_c: int = 0
    mcnemar_p_value: float | None = None
    descriptive_only: bool = True


class SelfJudgmentDimension(BaseModel):
    score: int = Field(ge=1, le=10)
    rationale: str | None = None


TRACE_BOUND_DIMENSIONS = {
    "speed_latency",
    "context_management",
    "tool_discoverability",
    "argument_clarity",
    "schema_output_clarity",
    "retrieval_quality",
    "citation_provenance_support",
    "diagnostics_recovery",
    "workflow_fit_biomedical_review",
    "safety_research_guardrails",
    "token_cost_efficiency",
    "confidence_in_final_answers",
}


class SelfJudgmentPayload(VersionedJsonModel):
    dimensions: dict[str, SelfJudgmentDimension]
    overall_score: int = Field(ge=1, le=10)
    recommendations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def dimensions_are_trace_bound(self) -> SelfJudgmentPayload:
        unknown = set(self.dimensions) - TRACE_BOUND_DIMENSIONS
        if unknown:
            raise ValueError(f"unknown self-judgment dimensions: {sorted(unknown)}")
        return self
