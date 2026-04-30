"""Models for review-scoped evidence preparation and re-RAG retrieval."""

import hashlib
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

PrepareMode = Literal["selected", "candidate_fast"]
JobStatus = Literal["queued", "running", "complete", "partial", "failed"]
AttemptStatus = Literal["success", "not_available", "blocked", "failed"]
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


class ContextPassage(BaseModel):
    """One citable passage returned in a context pack."""

    citation_key: str
    passage_id: str
    pmid: str | None = None
    pmcid: str | None = None
    section: str
    text: str
    source_kind: str | None = None


class ContextPack(BaseModel):
    """Fresh per-request retrieval result."""

    question: str
    passages: list[ContextPassage]
    citation_map: dict[str, str]


class RetrieveReviewContextResponse(BaseModel):
    """Response for context retrieval."""

    success: bool = True
    review_id: str
    context_pack: ContextPack
    preparation_status: PreparationStatus


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
