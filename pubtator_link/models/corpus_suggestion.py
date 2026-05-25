from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pubtator_link.models.publication_metadata import PublicationMetadata
from pubtator_link.models.review_rerag import SourceCoverageHint

CorpusCandidateRole = Literal[
    "guideline",
    "systematic_review",
    "cohort",
    "mechanism",
    "treatment",
    "background",
    "other",
]


class CorpusSuggestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    max_pmids: int = Field(default=8, ge=1, le=20)
    entity_ids: list[str] = Field(default_factory=list)
    must_include_pmids: list[str] = Field(default_factory=list)
    prefer_guidelines: bool = True
    include_metadata: bool = True

    @field_validator("max_pmids", mode="before")
    @classmethod
    def clamp_max_pmids(cls, value: int) -> int:
        return min(int(value), 20)


class CorpusSearchTrace(BaseModel):
    query: str
    result_pmids: list[str]
    result_titles: dict[str, str] = Field(default_factory=dict)


class CorpusCandidate(BaseModel):
    pmid: str
    role: CorpusCandidateRole
    title: str | None = None
    score: float = 0.0
    rationale: str
    matched_terms: list[str] = Field(default_factory=list)
    matched_intents: list[str] = Field(default_factory=list)
    metadata: PublicationMetadata | None = None
    coverage_hint: SourceCoverageHint | None = None


class CorpusSuggestionResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    success: bool = True
    candidate_pmids: list[str]
    candidates: list[CorpusCandidate]
    searches: list[CorpusSearchTrace]
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")
