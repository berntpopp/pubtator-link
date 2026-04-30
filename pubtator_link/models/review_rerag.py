"""Models for review-scoped evidence preparation and re-RAG retrieval."""

import hashlib
import math
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

PrepareMode = Literal["selected", "candidate_fast"]
JobStatus = Literal["queued", "running", "complete", "partial", "failed"]
AttemptStatus = Literal["success", "not_available", "blocked", "failed"]
ReviewBatchResponseMode = Literal["compact", "merged_only", "full", "diagnostics"]
ReviewTableMode = Literal["off", "preview", "full"]
SourceCoverage = Literal["title_only", "abstract_only", "full_text", "curated_url", "unknown"]
ZeroResultReason = Literal[
    "review_not_indexed",
    "no_candidate_matches",
    "filters_excluded_all_candidates",
    "all_candidates_over_budget",
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


class McpToolKind(StrEnum):
    """MCP-facing tool names for the POC."""

    index_review_evidence = "pubtator.index_review_evidence"
    retrieve_review_context = "pubtator.retrieve_review_context"


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


class IndexReviewEvidenceResponse(BaseModel):
    """Response after queueing or deduplicating preparation jobs."""

    success: bool = True
    review_id: str
    queued: int
    already_prepared: int
    preparation_status: PreparationStatus


class RetrieveReviewContextRequest(BaseModel):
    """Request for a fresh review-scoped context pack."""

    question: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages: int = Field(default=8, ge=1, le=30)
    max_chars: int = Field(default=6000, ge=500, le=30000)
    max_passages_per_pmid: int = Field(default=2, ge=1, le=10)
    include_diagnostics: bool = False
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)


def estimate_tokens_from_chars(char_count: int) -> int:
    """Return a conservative tokenizer-free estimate for LLM context planning."""
    return max(1, math.ceil(char_count / 3.6))


class ContextBudget(BaseModel):
    """Approximate context budget accounting for an MCP/REST response."""

    max_chars: int
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
    passage_id: str
    pmid: str | None = None
    pmcid: str | None = None
    section: str
    text: str
    source_kind: str | None = None
    char_count: int | None = None
    truncated: bool = False
    start_char: int | None = None
    end_char: int | None = None
    boundary: str | None = None
    score: PassageScore | None = None


class ContextPack(BaseModel):
    """Fresh per-request retrieval result."""

    question: str
    passages: list[ContextPassage]
    citation_map: dict[str, str]
    total_chars: int = 0
    estimated_tokens: int = 0
    budget: ContextBudget | None = None
    dropped: list[ContextDropReason] = Field(default_factory=list)


class RetrieveReviewContextResponse(BaseModel):
    """Response for context retrieval."""

    success: bool = True
    review_id: str
    context_pack: ContextPack
    preparation_status: PreparationStatus
    diagnostics: "RetrieveReviewDiagnostics | None" = None


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


class RetrieveReviewContextBatchRequest(BaseModel):
    """Request for multiple review-scoped context retrieval queries."""

    queries: list[str] = Field(min_length=1, max_length=10)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages_per_query: int = Field(default=8, ge=1, le=30)
    max_total_passages: int = Field(default=20, ge=1, le=60)
    max_chars: int = Field(default=12000, ge=500, le=50000)
    max_response_chars: int = Field(default=24000, ge=2000, le=100000)
    deduplicate_passages: bool = True
    include_diagnostics: bool = True
    response_mode: ReviewBatchResponseMode = "compact"
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)


class RetrieveReviewContextBatchResponse(BaseModel):
    """Response for batch review context retrieval."""

    success: bool = True
    review_id: str
    results: list[RetrieveReviewContextResponse]
    merged_context_pack: ContextPack
    preparation_status: PreparationStatus
    response_mode: ReviewBatchResponseMode = "compact"
    query_summaries: list[QueryDiagnosticsSummary] = Field(default_factory=list)
    budget: ContextBudget | None = None


class ReviewPassageSample(BaseModel):
    """Small passage excerpt for index inspection."""

    passage_id: str
    section: str
    text: str
    char_count: int


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
    sample_passages: list[ReviewPassageSample] = Field(default_factory=list)


class FailedSourceSummary(BaseModel):
    """Inspection summary for a failed or unavailable review source."""

    source_id: str
    pmid: str | None = None
    source_kind: str
    job_status: str
    error: str | None = None
    attempt_statuses: list[str] = Field(default_factory=list)


class ReviewIndexTotals(BaseModel):
    """Aggregate counts for a review-scoped index."""

    pmid_count: int = Field(default=0, ge=0)
    source_count: int = Field(default=0, ge=0)
    passage_count: int = Field(default=0, ge=0)
    char_count: int = Field(default=0, ge=0)
    failed_source_count: int = Field(default=0, ge=0)


class InspectReviewIndexRequest(BaseModel):
    """Request to inspect review-scoped index contents."""

    pmids: list[str] = Field(default_factory=list)
    include_passage_samples: bool = False
    sample_per_pmid: int = Field(default=2, ge=1, le=5)


class InspectReviewIndexResponse(BaseModel):
    """Response describing indexed sources and failures for a review."""

    success: bool = True
    review_id: str
    preparation_status: PreparationStatus
    sources: list[ReviewSourceSummary]
    totals: ReviewIndexTotals
    failed_sources: list[FailedSourceSummary]


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
