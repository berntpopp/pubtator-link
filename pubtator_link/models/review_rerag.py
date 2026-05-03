"""Models for review-scoped evidence preparation and re-RAG retrieval."""

import hashlib
import math
import re
from enum import StrEnum
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

PrepareMode = Literal["selected"]
JobStatus = Literal["queued", "running", "complete", "partial", "failed"]
PreparationEnqueueResult = Literal[
    "newly_queued",
    "already_queued",
    "already_running",
    "already_indexed",
    "previously_failed_requeued",
]
AttemptStatus = Literal["success", "not_available", "blocked", "failed"]
ReviewBatchResponseMode = Literal["compact", "merged_only", "full", "diagnostics", "quotes"]
InspectReviewIndexResponseMode = Literal["compact", "full"]
ReviewTableMode = Literal["off", "preview", "full"]
SourceCoverage = Literal["title_only", "abstract_only", "full_text", "curated_url", "unknown"]
CoverageTier = SourceCoverage
NextContextKind = Literal["passage", "neighboring_passages", "audit", "llm_context"]
GroundingConfidenceLevel = Literal["high", "moderate", "low", "unknown"]
CoverageExpectationConfidence = Literal["high", "moderate", "low", "unknown"]
CoverageResolutionStage = Literal[
    "preflight_resolver_chain",
    "indexer_resolver_chain",
    "not_resolved",
]
SampleSectionPolicy = Literal["evidence_first", "original_order"]
CoverageReason = Literal[
    "full_text_available",
    "pmc_oa_bioc",
    "abstract_fallback_used",
    "title_only_metadata",
    "no_pmcid",
    "pre_resolution_best_guess",
    "pmc_not_open_access",
    "license_reuse_unavailable",
    "upstream_timeout",
    "upstream_404",
    "retry_exhausted",
    "parser_unsupported",
    "blocked_source",
    "unknown",
]
BudgetStrategy = Literal["query_fair", "source_fair", "scarcity_first"]
BudgetSource = Literal["caller", "auto_fit", "default"]
ReviewResponseVerbosity = Literal["lean", "standard", "full"]
MaxResponseChars = int | Literal["auto"]
EvidenceCertaintyLabel = Literal["high", "moderate", "low", "very_low", "not_rated"]
ZeroResultReason = Literal[
    "review_not_indexed",
    "no_pmids_indexed",
    "no_candidate_matches",
    "filters_excluded_all_candidates",
    "all_candidates_over_budget",
    "coverage_abstract_only",
    "preparation_failed",
]
SourceKind = Literal[
    "pubtator_full_bioc",
    "pmc_bioc",
    "europe_pmc_jats",
    "curated_pdf",
    "curated_html",
    "docling_pdf",
    "pubtator_abstract",
]
ResearchSessionStatus = Literal["active", "complete", "partial", "failed"]
ResearchSessionCandidateStatus = Literal[
    "candidate",
    "preflighted",
    "queued",
    "abstract_ready",
    "full_text_ready",
    "abstract_only",
    "metadata_only",
    "failed",
    "skipped",
]
ResearchSessionDecisionReason = Literal[
    "selected_by_rank",
    "explicit_pmid",
    "duplicate",
    "over_candidate_limit",
    "coverage_unknown",
    "metadata_only",
    "preflight_failed",
    "already_indexed",
    "queue_rejected",
]
ReviewLlmContextKind = Literal["retrieval_context"]
ReviewLlmContextEventType = Literal[
    "context_created",
    "session_selected",
    "pmids_selected",
    "pmids_rejected",
    "query_succeeded",
    "query_failed",
    "passage_selected",
    "audit_passage_selected",
    "question_opened",
    "decision_recorded",
    "next_commands_recorded",
    "context_summarized",
]


class McpToolKind(StrEnum):
    """MCP-facing tool names for the POC."""

    index_review_evidence = "pubtator.index_review_evidence"
    retrieve_review_context = "pubtator.retrieve_review_context"


class EvidenceTier(StrEnum):
    """Scientific evidence tier for returned or inspected source material."""

    PASSAGE_FULL_TEXT = "PASSAGE_FULL_TEXT"
    PASSAGE_ABSTRACT = "PASSAGE_ABSTRACT"
    METADATA_TITLE = "METADATA_TITLE"
    CURATED_FULL_TEXT = "CURATED_FULL_TEXT"
    UNVERIFIED_EXTERNAL = "UNVERIFIED_EXTERNAL"


class ResolverAttemptSummary(BaseModel):
    """Structured audit summary for one upstream/source resolver attempt."""

    source_kind: str
    status: AttemptStatus
    attempt_count: int = Field(default=1, ge=1)
    last_status_code: int | None = None
    retry_after_ms: int | None = None
    backoff_ms: int | None = None
    terminal_reason: CoverageReason | str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    source_id: str | None = None
    url: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    content_type: str | None = None
    content_length: int | None = Field(default=None, ge=0)


class SourceCoverageHint(BaseModel):
    """Preflight source coverage estimate for a PMID."""

    pmid: str
    expected_coverage: SourceCoverage = "unknown"
    coverage_reason: CoverageReason = "unknown"
    pmcid: str | None = None
    doi: str | None = None
    license_or_access_hint: str | None = None
    pmc_fallback_available: bool = False
    notes: list[str] = Field(default_factory=list)
    resolver_attempts: list[ResolverAttemptSummary] = Field(default_factory=list)
    expected_coverage_after_index: SourceCoverage = "unknown"
    expected_coverage_confidence: CoverageExpectationConfidence = "unknown"
    coverage_resolution_stage: CoverageResolutionStage = "not_resolved"


def coverage_to_evidence_tier(coverage: SourceCoverage, source_kind: str) -> EvidenceTier:
    """Map actual source coverage into a review-facing evidence tier."""
    if coverage == "full_text":
        return EvidenceTier.PASSAGE_FULL_TEXT
    if coverage == "abstract_only":
        return EvidenceTier.PASSAGE_ABSTRACT
    if coverage == "title_only":
        return EvidenceTier.METADATA_TITLE
    if coverage == "curated_url":
        return EvidenceTier.CURATED_FULL_TEXT
    if source_kind in {"curated_pdf", "curated_html", "docling_pdf"}:
        return EvidenceTier.CURATED_FULL_TEXT
    return EvidenceTier.UNVERIFIED_EXTERNAL


class PreparationStatus(BaseModel):
    """Aggregated preparation status counts for one review."""

    queued: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    complete: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        """Total preparation jobs across statuses."""
        return self.queued + self.running + self.complete + self.partial + self.failed


class IndexReviewEvidenceRequest(BaseModel):
    """Request to enqueue review-scoped evidence preparation."""

    pmids: list[str] = Field(default_factory=list)
    curated_urls: list[str] = Field(default_factory=list)
    prepare_mode: PrepareMode = "selected"
    session_id: str | None = Field(default=None, min_length=1)
    wait_for_completion: bool = False
    wait_for_status: Literal["complete", "complete_or_partial", "terminal"] | None = None
    timeout_ms: int = Field(default=0, ge=0, le=120_000)
    dry_run: bool = False


class IndexReviewEvidenceResponse(BaseModel):
    """Response after queueing or deduplicating preparation jobs."""

    success: bool = True
    review_id: str
    queued: int
    already_prepared: int
    preparation_status: PreparationStatus
    retry_after_ms: int | None = None
    index_snapshot_date: str | None = None
    lifecycle_note: str | None = None
    dry_run: bool = False
    waited_ms: int = 0
    timed_out: bool = False
    estimated_queue_position: int | None = None
    estimated_source_count: int = 0
    already_indexed: int = 0
    already_queued: int = 0
    already_running: int = 0
    newly_queued: int = 0
    previously_failed_requeued: int = 0
    source_preflight_summary: dict[str, int] = Field(default_factory=dict)
    source_preflight_message: str | None = None
    source_preflight_warnings: list[str] = Field(default_factory=list)


class PreflightReviewSourcesRequest(BaseModel):
    """Request to estimate source coverage before review indexing."""

    pmids: list[str] = Field(min_length=1)


class PreflightReviewSourcesResponse(BaseModel):
    """Response containing source coverage hints for requested PMIDs."""

    success: bool = True
    coverage_hints: list[SourceCoverageHint]


class StageResearchSessionRequest(BaseModel):
    """Request to stage a transparent research session."""

    session_id: str | None = Field(default=None, min_length=1)
    query: str | None = Field(default=None, min_length=1)
    pmids: list[str] = Field(default_factory=list)
    page: int = Field(default=1, ge=1, le=1000)
    sort: str | None = None
    filters: str | None = None
    publication_types: list[str] = Field(default_factory=list)
    year_min: int | None = Field(default=None, ge=1800, le=2030)
    year_max: int | None = Field(default=None, ge=1800, le=2030)
    sections: list[str] = Field(default_factory=list)
    max_candidates: int = Field(default=20, ge=1, le=100)
    stage_full_text: bool = True

    @model_validator(mode="after")
    def require_query_or_pmids(self) -> Self:
        if not self.query and not self.pmids:
            raise ValueError("query or pmids is required")
        return self


class ResearchSessionCandidate(BaseModel):
    """One PMID candidate in a staged research session."""

    pmid: str
    rank: int | None = Field(default=None, ge=1)
    title: str | None = None
    status: ResearchSessionCandidateStatus = "candidate"
    decision_reason: ResearchSessionDecisionReason = "selected_by_rank"
    coverage_hint: SourceCoverageHint | None = None
    source_id: str | None = None
    error: str | None = None


class ResearchSessionManifest(BaseModel):
    """Transparent manifest for one research session."""

    session_id: str
    review_id: str
    query: str | None = None
    status: ResearchSessionStatus = "active"
    candidates: list[ResearchSessionCandidate] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
    queued_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    preparation_status: PreparationStatus | None = None
    created_at: str | None = None
    updated_at: str | None = None


class StageResearchSessionResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    success: bool = True
    manifest: ResearchSessionManifest
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")


class ReviewQuickstartResponse(BaseModel):
    """One-shot search, stage/index, inspect handoff for casual review sessions."""

    success: bool = True
    review_id: str
    session_id: str
    topic: str
    selected_pmids: list[str] = Field(default_factory=list)
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    preparation_status: PreparationStatus
    indexed_totals: "ReviewIndexTotals"
    ready_to_retrieve: bool = False
    next_commands: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GroundQuestionResponse(BaseModel):
    """Composite one-call grounded question workflow response."""

    success: bool = True
    question: str
    review_id: str
    selected_pmids: list[str] = Field(default_factory=list)
    search_total_results: int = 0
    preparation_status: PreparationStatus | None = None
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    ready_to_retrieve: bool = False
    context: "RetrieveReviewContextBatchResponse | None" = None
    next_tools: list[str] = Field(default_factory=list)
    recovery: list[str] = Field(default_factory=list)


class ResearchSessionStatusResponse(BaseModel):
    success: bool = True
    manifest: ResearchSessionManifest


class ListResearchSessionsResponse(BaseModel):
    success: bool = True
    sessions: list[ResearchSessionManifest] = Field(default_factory=list)


class RetrieveReviewContextRequest(BaseModel):
    """Request for a fresh review-scoped context pack."""

    question: str = Field(..., min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages: int = Field(default=8, ge=1, le=30)
    max_chars: int = Field(default=6000, ge=500, le=50000)
    max_passages_per_pmid: int = Field(default=2, ge=1, le=10)
    include_diagnostics: bool = False
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    section_policy: SampleSectionPolicy = "evidence_first"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)


def estimate_tokens_from_chars(char_count: int) -> int:
    """Return a conservative tokenizer-free estimate for LLM context planning."""
    return max(1, math.ceil(char_count / 3.6))


def stable_citation_key_for_passage(passage_id: str) -> str:
    """Return a deterministic compact citation key for a stable passage ID."""
    return f"c_{hashlib.sha256(passage_id.encode('utf-8')).hexdigest()[:10]}"


class ContextBudget(BaseModel):
    """Approximate context budget accounting for an MCP/REST response."""

    max_chars: int
    budget_source: BudgetSource = "default"
    text_chars: int
    estimated_json_chars: int
    estimated_total_chars: int
    estimated_tokens: int
    truncated: bool = False
    dropped_count: int = 0


class ContextDropReason(BaseModel):
    """Reason a candidate passage was not included in a compact response."""

    reason: str
    passage_id: str | None = None
    pmid: str | None = None
    section: str | None = None
    char_count: int | None = None


class RecoverySuggestedFilters(BaseModel):
    """Bounded filters an LLM can apply on a follow-up retrieval call."""

    sections: list[str] = Field(default_factory=list)
    pmids: list[str] = Field(default_factory=list)


class RecoveryBudgetAdvice(BaseModel):
    """Bounded context-budget adjustments for recovery."""

    increase_max_chars_to: int | None = Field(default=None, ge=500)
    increase_max_response_chars_to: int | None = Field(default=None, ge=2000)
    lower_max_passages_per_query_to: int | None = Field(default=None, ge=1)
    estimated_tokens_to_unlock: int | None = Field(default=None, ge=0)
    dropped_pmid_count: int = Field(default=0, ge=0)
    dropped_priority_pmids: list[str] = Field(default_factory=list)
    retry_arguments: dict[str, Any] = Field(default_factory=dict)


class RecoveryHint(BaseModel):
    """Top-level deterministic recovery guidance for LLM drivers."""

    reason: str
    message: str
    next_steps: list[str] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list)
    suggested_filters: RecoverySuggestedFilters | None = None
    budget_advice: RecoveryBudgetAdvice | None = None


class SourceDroppedSummary(BaseModel):
    """Structured accounting for passages dropped from a compact response."""

    total_dropped: int = Field(default=0, ge=0)
    visible_dropped: int = Field(default=0, ge=0)
    truncated_count: int = Field(default=0, ge=0)
    by_reason: dict[str, int] = Field(default_factory=dict)
    suggested_filters: RecoverySuggestedFilters | None = None
    budget_advice: RecoveryBudgetAdvice | None = None


class PassageQuote(BaseModel):
    """Citation-ready quote with returned-text and original-passage offsets."""

    text: str
    truncated: bool = False
    tail_preview: str | None = None
    returned_start_offset: int = Field(ge=0)
    returned_end_offset: int = Field(ge=0)
    passage_start_char: int = Field(ge=0)
    passage_end_char: int = Field(ge=0)
    offset_basis: Literal["returned_text_and_original_passage"] = (
        "returned_text_and_original_passage"
    )


class GroundingConfidence(BaseModel):
    """Deterministic source-grounding confidence, not clinical certainty."""

    level: GroundingConfidenceLevel = "unknown"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    factors: dict[str, float] = Field(default_factory=dict)
    match_mode: Literal["strict", "relaxed", "strict_and_relaxed"] = "strict_and_relaxed"
    explanation: str


class PassageScore(BaseModel):
    """Transparent score features for a selected review passage."""

    lexical_rank: float = 0.0
    section_boost: float = 0.0
    entity_overlap: int = 0
    pmid_filter_boost: float = 0.0
    final_rank: float = 0.0


class ContextPassage(BaseModel):
    """One citable passage returned in a context pack."""

    citation_key: str
    stable_citation_key: str | None = None
    passage_id: str
    source_id: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    section: str
    text: str
    source_kind: str | None = None
    char_count: int | None = None
    truncated: bool = False
    tail_preview: str | None = None
    next_window_token: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    boundary: str | None = None
    score: PassageScore | None = None
    quote: PassageQuote | None = None
    confidence_for_grounding: GroundingConfidence | None = None
    matched_queries: list[str] = Field(default_factory=list)
    matched_query_indices: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_stable_citation_key(self) -> Self:
        """Populate the stable citation key from the immutable passage ID."""
        if self.stable_citation_key is None:
            self.stable_citation_key = stable_citation_key_for_passage(self.passage_id)
        return self

    @model_serializer(mode="wrap")
    def serialize_compact(self, handler: Any) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        for key in list(data):
            if data[key] in (None, [], {}):
                data.pop(key)
        confidence = self.confidence_for_grounding
        if confidence is not None:
            data["confidence_for_grounding"] = {
                "level": confidence.level,
                "explanation": confidence.explanation,
            }
        return data


class ContextPack(BaseModel):
    """Fresh per-request retrieval result."""

    question: str
    passages: list[ContextPassage]
    citation_map: dict[str, str]
    stable_citation_map: dict[str, str] = Field(default_factory=dict)
    total_chars: int = 0
    estimated_tokens: int = 0
    budget: ContextBudget | None = None
    dropped: list[ContextDropReason] = Field(default_factory=list)
    dropped_summary: SourceDroppedSummary | dict[str, int] = Field(default_factory=dict)
    recovery: RecoveryHint | None = None

    @model_validator(mode="after")
    def fill_stable_citation_map(self) -> Self:
        """Populate stable citation key mappings when callers omit them."""
        if not self.stable_citation_map:
            self.stable_citation_map = {
                passage.stable_citation_key: passage.passage_id
                for passage in self.passages
                if passage.stable_citation_key is not None
            }
        return self


class RetrieveReviewContextResponse(BaseModel):
    """Response for context retrieval."""

    success: bool = True
    review_id: str
    context_pack: ContextPack
    preparation_status: PreparationStatus
    index_snapshot_date: str | None = None
    diagnostics: "RetrieveReviewDiagnostics | None" = None
    prepared_pmids: list[str] = Field(default_factory=list)
    still_preparing_pmids: list[str] = Field(default_factory=list)
    failed_pmids: list[str] = Field(default_factory=list)
    recovery: RecoveryHint | None = None


class EmbeddingRerankDiagnostics(BaseModel):
    """Diagnostics for optional embedding-based review context reranking."""

    enabled: bool = False
    active: bool = False
    model_name: str | None = None
    embedding_dim: int | None = None
    candidate_count: int = Field(default=0, ge=0)
    embedded_candidate_count: int = Field(default=0, ge=0)
    missing_embedding_count: int = Field(default=0, ge=0)
    strategy: str | None = None
    fallback_reason: str | None = None


class RetrieveReviewDiagnostics(BaseModel):
    """Actionable diagnostics for review context retrieval."""

    query: str
    query_tokens: list[str]
    query_mode: Literal["strict", "relaxed", "strict_and_relaxed"] = "strict_and_relaxed"
    candidate_count: int = Field(default=0, ge=0)
    selected_count: int = Field(default=0, ge=0)
    available_sections: list[str] = Field(default_factory=list)
    indexed_pmids: list[str] = Field(default_factory=list)
    failed_sources: list["FailedSourceSummary"] = Field(default_factory=list)
    filter_summary: dict[str, list[str]] = Field(default_factory=dict)
    suggested_queries: list[str] = Field(default_factory=list)
    embedding_rerank: EmbeddingRerankDiagnostics | None = None
    message: str


class QueryDiagnosticsSummary(BaseModel):
    """Compact per-query diagnostics for batch retrieval."""

    query: str
    query_tokens: list[str]
    candidate_count: int = Field(default=0, ge=0)
    selected_count: int = Field(default=0, ge=0)
    returned_count: int = Field(default=0, ge=0)
    dropped_count: int = Field(default=0, ge=0)
    top_sections: list[str] = Field(default_factory=list)
    top_pmids: list[str] = Field(default_factory=list)
    zero_result_reason: ZeroResultReason | None = None
    suggested_queries: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class SourceBudgetSummary(BaseModel):
    """Per-source accounting for source-aware batch budgeting."""

    source_id: str | None = None
    pmid: str | None = None
    coverage: SourceCoverage = "unknown"
    candidate_count: int = Field(default=0, ge=0)
    returned_count: int = Field(default=0, ge=0)
    dropped_count: int = Field(default=0, ge=0)
    first_pass_eligible: bool = False


class PmidStatusSummary(BaseModel):
    """Per-PMID accounting for batch retrieval."""

    pmid: str
    candidate_count: int = Field(default=0, ge=0)
    passages_returned: int = Field(default=0, ge=0)
    passages_dropped: int = Field(default=0, ge=0)
    prioritized: bool = False


class RetrieveReviewBatchDiagnostics(BaseModel):
    """Collapsed diagnostics for batch review context retrieval."""

    query_summaries: list[QueryDiagnosticsSummary] = Field(default_factory=list)
    source_budget_summaries: list[SourceBudgetSummary] = Field(default_factory=list)
    pmid_status_summary: list[PmidStatusSummary] = Field(default_factory=list)
    dropped_summary: SourceDroppedSummary | dict[str, int] = Field(default_factory=dict)


class ReviewQuote(BaseModel):
    """Short citable quote returned by batch quotes mode."""

    stable_citation_key: str
    pmid: str | None = None
    passage_id: str
    section: str
    quote: str = Field(max_length=350)
    truncated: bool = False
    tail_preview: str | None = None
    matched_queries: list[str] = Field(default_factory=list)
    coverage_status: SourceCoverage = "unknown"


class NextContextOption(BaseModel):
    """Resource link for loading additional context after retrieval."""

    kind: NextContextKind
    resource: str
    reason: str


class RetrieveReviewContextBatchRequest(BaseModel):
    """Request for multiple review-scoped context retrieval queries."""

    queries: list[str] = Field(min_length=1, max_length=10)
    session_id: str | None = Field(default=None, min_length=1)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages_per_query: int = Field(default=8, ge=1, le=30)
    max_total_passages: int = Field(default=20, ge=1, le=60)
    max_chars: int = Field(default=24000, ge=500, le=50000)
    max_response_chars: MaxResponseChars = 48000
    verbosity: ReviewResponseVerbosity = "standard"
    budget_source: BudgetSource = "default"
    deduplicate_passages: bool = True
    budget_strategy: BudgetStrategy = "query_fair"
    min_passages_per_source: int = Field(default=1, ge=1, le=10)
    min_passages_per_pmid: int = Field(default=0, ge=0, le=10)
    prioritize_pmids: list[str] = Field(default_factory=list)
    include_diagnostics: bool = False
    response_mode: ReviewBatchResponseMode = "compact"
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    section_policy: SampleSectionPolicy = "evidence_first"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)
    dry_run: bool = False


class RetrieveReviewContextBatchResponse(BaseModel):
    """Response for batch review context retrieval."""

    success: bool = True
    review_id: str
    results: list[RetrieveReviewContextResponse] = Field(default_factory=list)
    merged_context_pack: ContextPack
    preparation_status: PreparationStatus
    response_mode: ReviewBatchResponseMode = "compact"
    include_diagnostics: bool = False
    diagnostics: RetrieveReviewBatchDiagnostics | None = None
    query_summaries: list[QueryDiagnosticsSummary] = Field(default_factory=list)
    source_budget_summaries: list[SourceBudgetSummary] = Field(default_factory=list)
    pmid_status_summary: list[PmidStatusSummary] = Field(default_factory=list)
    budget: ContextBudget | None = None
    budget_source: BudgetSource = "default"
    cache_key: str | None = None
    corpus_snapshot_date: str | None = None
    index_snapshot_date: str | None = None
    source_versions: dict[str, str] = Field(default_factory=dict)
    prepared_pmids: list[str] = Field(default_factory=list)
    still_preparing_pmids: list[str] = Field(default_factory=list)
    failed_pmids: list[str] = Field(default_factory=list)
    recovery: RecoveryHint | None = None
    quotes: list[ReviewQuote] = Field(default_factory=list)
    next_context_options: list[NextContextOption] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def omit_empty_results_for_compact(self, handler: Any) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        if (
            self.response_mode in {"compact", "merged_only", "diagnostics", "quotes"}
            and not self.results
        ):
            data.pop("results", None)
        if self.response_mode in {"compact", "merged_only"} or (
            not self.include_diagnostics and self.response_mode != "diagnostics"
        ):
            data.pop("query_summaries", None)
            data.pop("source_budget_summaries", None)
            data.pop("pmid_status_summary", None)
        if not self.include_diagnostics and self.response_mode != "diagnostics":
            data.pop("diagnostics", None)
        return data


class ReviewPassageSample(BaseModel):
    """Small passage excerpt for index inspection."""

    passage_id: str
    section: str
    text: str
    char_count: int


class ReviewPassageLookupRequest(BaseModel):
    """Request exact review passages by stable passage ID."""

    passage_ids: list[str] = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)


class ReviewNeighboringPassagesRequest(BaseModel):
    """Request neighboring review passages around a stable passage ID."""

    passage_id: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    before: int = Field(default=1, ge=0, le=20)
    after: int = Field(default=1, ge=0, le=20)
    same_section: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)


class ReviewPassageLookupResponse(BaseModel):
    """Response for exact or neighboring review passage lookups."""

    success: bool = True
    review_id: str
    passages: list[ContextPassage]
    not_found: list[str] = Field(default_factory=list)


class ReviewAuditTrailItem(BaseModel):
    """One copy-ready selected passage audit item."""

    pmid: str | None = None
    pmcid: str | None = None
    passage_id: str
    stable_citation_key: str
    section: str
    quote: str
    char_count: int = Field(ge=0)


class ReviewAuditTrailResponse(BaseModel):
    """Thin audit trail for selected passage IDs used in an answer."""

    success: bool = True
    review_id: str
    session_id: str | None = None
    items: list[ReviewAuditTrailItem] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    audit_block: str = ""


class ReviewSearchRun(BaseModel):
    query: str
    filters: dict[str, object] = Field(default_factory=dict)
    source: str = "pubtator"
    returned_count: int = Field(default=0, ge=0)
    created_at: str | None = None


class ReviewRetrievalRun(BaseModel):
    queries: list[str]
    passage_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None


class ReviewLlmContext(BaseModel):
    """Compact durable context snapshot for LLM review resume."""

    context_id: str
    review_id: str
    session_id: str | None = None
    kind: ReviewLlmContextKind = "retrieval_context"
    topic: str | None = Field(default=None, max_length=500)
    research_question: str | None = Field(default=None, max_length=1000)
    question_hash: str | None = Field(default=None, max_length=128)
    request: dict[str, Any] = Field(default_factory=dict, max_length=40)
    response_summary: dict[str, Any] = Field(default_factory=dict, max_length=40)
    selected_pmids: list[str] = Field(default_factory=list, max_length=200)
    rejected_pmids: list[str] = Field(default_factory=list, max_length=200)
    preferred_entity_ids: list[str] = Field(default_factory=list, max_length=200)
    active_queries: list[str] = Field(default_factory=list, max_length=50)
    successful_queries: list[str] = Field(default_factory=list, max_length=100)
    failed_queries: list[str] = Field(default_factory=list, max_length=100)
    selected_passage_ids: list[str] = Field(default_factory=list, max_length=500)
    audit_passage_ids: list[str] = Field(default_factory=list, max_length=500)
    open_questions: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    user_decisions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    last_next_commands: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    stable_citation_keys: dict[str, str] = Field(default_factory=dict, max_length=500)
    cache_key: str | None = Field(default=None, max_length=500)
    token_estimate: int | None = Field(default=None, ge=0)
    created_by: str | None = Field(default=None, max_length=200)
    created_at: str
    updated_at: str


class ReviewLlmContextEvent(BaseModel):
    """Append-only LLM context event with compact evidence references."""

    event_id: str
    context_id: str | None = None
    review_id: str
    session_id: str | None = None
    event_type: ReviewLlmContextEventType
    summary: str | None = Field(default=None, max_length=4000)
    pmids: list[str] = Field(default_factory=list, max_length=200)
    passage_ids: list[str] = Field(default_factory=list, max_length=500)
    queries: list[str] = Field(default_factory=list, max_length=100)
    decision: dict[str, Any] | None = Field(default=None, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict, max_length=40)
    created_by: str | None = Field(default=None, max_length=200)
    created_at: str


class RecordReviewContextRequest(BaseModel):
    """Request to persist compact LLM context without article text."""

    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    kind: ReviewLlmContextKind = "retrieval_context"
    topic: str | None = Field(default=None, max_length=500)
    research_question: str | None = Field(default=None, max_length=1000)
    question_hash: str | None = Field(default=None, max_length=128)
    request: dict[str, Any] = Field(default_factory=dict, max_length=40)
    response_summary: dict[str, Any] = Field(default_factory=dict, max_length=40)
    selected_pmids: list[str] = Field(default_factory=list, max_length=200)
    rejected_pmids: list[str] = Field(default_factory=list, max_length=200)
    preferred_entity_ids: list[str] = Field(default_factory=list, max_length=200)
    active_queries: list[str] = Field(default_factory=list, max_length=50)
    successful_queries: list[str] = Field(default_factory=list, max_length=100)
    failed_queries: list[str] = Field(default_factory=list, max_length=100)
    selected_passage_ids: list[str] = Field(default_factory=list, max_length=500)
    audit_passage_ids: list[str] = Field(default_factory=list, max_length=500)
    open_questions: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    user_decisions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    last_next_commands: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    stable_citation_keys: dict[str, str] = Field(default_factory=dict, max_length=500)
    cache_key: str | None = Field(default=None, max_length=500)
    token_estimate: int | None = Field(default=None, ge=0)
    event_type: ReviewLlmContextEventType
    summary: str | None = Field(default=None, max_length=4000)
    pmids: list[str] = Field(default_factory=list, max_length=200)
    passage_ids: list[str] = Field(default_factory=list, max_length=500)
    queries: list[str] = Field(default_factory=list, max_length=100)
    decision: dict[str, Any] | None = Field(default=None, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict, max_length=40)
    created_by: str | None = Field(default=None, max_length=200)


class RecordReviewContextResponse(BaseModel):
    success: bool = True
    context: ReviewLlmContext
    event: ReviewLlmContextEvent


class ReviewAuditBundle(BaseModel):
    success: bool = True
    review_id: str
    session_id: str | None = None
    generated_at: str
    preparation_status: PreparationStatus
    totals: "ReviewIndexTotals"
    sources: list["ReviewSourceSummary"]
    failed_sources: list["FailedSourceSummary"]
    coverage_distribution: dict[str, int]
    resolver_attempts: list[ResolverAttemptSummary]
    search_runs: list[ReviewSearchRun] = Field(default_factory=list)
    retrieval_runs: list[ReviewRetrievalRun] = Field(default_factory=list)
    evidence_certainty: list["EvidenceCertaintyRecord"] = Field(default_factory=list)
    research_sessions: list[ResearchSessionManifest] = Field(default_factory=list)
    passage_ids: list[str]
    stable_citation_keys: dict[str, str]
    index_snapshot_date: str | None = None


class McpReviewAuditBundleResponse(BaseModel):
    """MCP wrapper preserving the existing audit bundle tool JSON shape."""

    success: bool = True
    audit_bundle: ReviewAuditBundle | None = None
    inline_bundle: dict[str, Any] | None = None
    export_path: str | None = None
    error: dict[str, Any] | None = None


class ReviewIndexInventoryItem(BaseModel):
    """Inventory summary for one persisted review index."""

    review_id: str
    created_at: str
    updated_at: str
    expires_at: str | None = None
    preparation_status: PreparationStatus
    pmid_count: int = Field(default=0, ge=0)
    source_count: int = Field(default=0, ge=0)
    passage_count: int = Field(default=0, ge=0)
    failed_source_count: int = Field(default=0, ge=0)
    approximate_bytes: int = Field(default=0, ge=0)


class ListReviewIndexesResponse(BaseModel):
    success: bool = True
    indexes: list[ReviewIndexInventoryItem] = Field(default_factory=list)


class ReviewIndexSummaryResponse(BaseModel):
    success: bool = True
    index: ReviewIndexInventoryItem | None = None


class DeleteReviewIndexResponse(BaseModel):
    success: bool = True
    review_id: str
    deleted: bool


class CleanupExpiredReviewIndexesResponse(BaseModel):
    success: bool = True
    deleted_review_ids: list[str] = Field(default_factory=list)


class UpsertEvidenceCertaintyRequest(BaseModel):
    """User/client-supplied GRADE-style certainty judgment."""

    outcome: str = Field(min_length=1)
    question: str | None = None
    study_design: str | None = None
    risk_of_bias_notes: str | None = None
    inconsistency_notes: str | None = None
    indirectness_notes: str | None = None
    imprecision_notes: str | None = None
    publication_bias_notes: str | None = None
    overall_certainty: EvidenceCertaintyLabel = "not_rated"
    certainty_rationale: str | None = None
    passage_ids: list[str] = Field(default_factory=list)
    created_by: str | None = None
    validate_passages: bool = False


class EvidenceCertaintyRecord(BaseModel):
    """Stored user/client-supplied certainty judgment."""

    certainty_id: str
    review_id: str
    outcome: str
    question: str | None = None
    study_design: str | None = None
    risk_of_bias_notes: str | None = None
    inconsistency_notes: str | None = None
    indirectness_notes: str | None = None
    imprecision_notes: str | None = None
    publication_bias_notes: str | None = None
    overall_certainty: EvidenceCertaintyLabel = "not_rated"
    certainty_rationale: str | None = None
    passage_ids: list[str] = Field(default_factory=list)
    unresolved_passage_ids: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: str
    updated_at: str


class EvidenceCertaintyResponse(BaseModel):
    success: bool = True
    record: EvidenceCertaintyRecord


class ListEvidenceCertaintyResponse(BaseModel):
    success: bool = True
    records: list[EvidenceCertaintyRecord] = Field(default_factory=list)


class ReviewSourceSummary(BaseModel):
    """Inspection summary for one indexed review source."""

    source_id: str
    pmid: str | None = None
    source_kind: str
    job_status: str
    error: str | None = None
    attempt_statuses: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    passage_count: int = Field(default=0, ge=0)
    char_count: int = Field(default=0, ge=0)
    coverage: SourceCoverage = "unknown"
    coverage_reason: CoverageReason = "unknown"
    pmcid: str | None = None
    doi: str | None = None
    license_or_access_hint: str | None = None
    pmc_fallback_available: bool = False
    resolver_attempts: list[ResolverAttemptSummary] = Field(default_factory=list)
    sample_passages: list[ReviewPassageSample] = Field(default_factory=list)
    sample_warning: str | None = None
    citation_metadata: Any | None = None


class FailedSourceSummary(BaseModel):
    """Inspection summary for a failed or unavailable review source."""

    source_id: str
    pmid: str | None = None
    source_kind: str
    job_status: str
    error: str | None = None
    attempt_statuses: list[str] = Field(default_factory=list)
    coverage_reason: CoverageReason = "unknown"
    pmcid: str | None = None
    doi: str | None = None
    license_or_access_hint: str | None = None
    pmc_fallback_available: bool = False
    resolver_attempts: list[ResolverAttemptSummary] = Field(default_factory=list)


class ReviewIndexTotals(BaseModel):
    """Aggregate counts for a review-scoped index."""

    pmid_count: int = Field(default=0, ge=0)
    source_count: int = Field(default=0, ge=0)
    passage_count: int = Field(default=0, ge=0)
    char_count: int = Field(default=0, ge=0)
    failed_source_count: int = Field(default=0, ge=0)


class InspectReviewIndexRequest(BaseModel):
    """Request to inspect review-scoped index contents."""

    session_id: str | None = Field(default=None, min_length=1)
    pmids: list[str] = Field(default_factory=list)
    response_mode: InspectReviewIndexResponseMode = "full"
    include_passage_samples: bool = False
    sample_per_pmid: int = Field(default=2, ge=0, le=10)
    min_sample_chars: int = Field(default=80, ge=0, le=1000)
    sample_section_policy: SampleSectionPolicy = "evidence_first"
    include_metadata: bool = False
    metadata: Literal["basic", "full"] = "basic"
    limit: int | None = Field(default=None, ge=1, le=100)
    cursor: str | None = None


class InspectReviewIndexResponse(BaseModel):
    """Response describing indexed sources and failures for a review."""

    success: bool = True
    review_id: str
    response_mode: InspectReviewIndexResponseMode = "full"
    preparation_status: PreparationStatus
    sources: list[ReviewSourceSummary]
    totals: ReviewIndexTotals
    failed_sources: list[FailedSourceSummary]
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    index_snapshot_date: str | None = None
    next_cursor: str | None = None
    page_source_count: int = Field(default=0, ge=0)
    page_failed_source_count: int = Field(default=0, ge=0)
    omitted_counts: dict[str, int] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def omit_bulky_fields_for_compact(self, handler: Any) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        if self.response_mode != "compact":
            return data
        for source in data.get("sources", []):
            if not isinstance(source, dict):
                continue
            source.pop("resolver_attempts", None)
            source.pop("sample_passages", None)
            source.pop("citation_metadata", None)
            _drop_none_values(source)
        for failed_source in data.get("failed_sources", []):
            if not isinstance(failed_source, dict):
                continue
            failed_source.pop("resolver_attempts", None)
            _drop_none_values(failed_source)
        return data


def _drop_none_values(data: dict[str, Any]) -> None:
    for key, value in list(data.items()):
        if value is None:
            data.pop(key)


class ReviewPassageRow(BaseModel):
    """Repository row for a review passage candidate."""

    passage_id: str
    review_id: str
    source_id: str
    source_kind: str
    section: str
    text: str
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    url: str | None = None
    heading_path: str | None = None
    page: int | None = None
    entity_ids: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    screening_status: str = "candidate"
    source_metadata: dict[str, object] = Field(default_factory=dict)
    lexical_rank: float = 0.0


def normalize_section(section: str) -> str:
    """Normalize a section name for stable passage IDs."""
    lowered = section.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered)
    return normalized.strip("_") or "body"


def passage_id_for_pmid(pmid: str, section: str, index: int) -> str:
    """Build deterministic PMID passage ID."""
    return f"PMID:{pmid}:{normalize_section(section)}:{index}"


def passage_id_for_pmcid(pmcid: str, section: str, index: int) -> str:
    """Build deterministic PMCID passage ID."""
    return f"PMCID:{pmcid}:{normalize_section(section)}:{index}"


def source_hash_for_url(url: str) -> str:
    """Build stable short URL source hash."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def passage_id_for_url(url: str, section_or_page: str, index: int) -> str:
    """Build deterministic URL passage ID."""
    return f"URL:{source_hash_for_url(url)}:{normalize_section(section_or_page)}:{index}"
