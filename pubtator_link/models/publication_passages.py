"""Compact publication passage models."""

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from pubtator_link.services.degradation import DegradedMode

PublicationPassageMode = Literal["abstracts", "full_abstract", "compact_passages", "section_text"]
PublicationCoverage = Literal["full_text", "abstract_only", "title_only", "unknown"]
Verbosity = Literal["lean", "standard", "full"]
PassageDropReasonCode = Literal[
    "char_budget_exceeded",
    "section_filtered",
    "reference_excluded",
    "table_excluded",
    "max_passages_per_pmid_exceeded",
    "upstream_error",
]
PublicationPassageSource = Literal["pubtator_abstract", "pubtator_full_bioc"]
MAX_PUBLICATION_PASSAGE_CHARS = 50_000
RECOMMENDED_CONTEXT_SAFETY_NUMERATOR = 6
RECOMMENDED_CONTEXT_SAFETY_DENOMINATOR = 5


class PublicationPassageRequest(BaseModel):
    """Request for compact passages from PubTator BioC exports."""

    pmids: list[str] = Field(min_length=1, max_length=25)
    sections: list[str] = Field(default_factory=list)
    mode: PublicationPassageMode = "compact_passages"
    full: bool = False
    max_passages_per_pmid: int = Field(default=6, ge=1, le=30)
    max_chars: int = Field(default=12000, ge=1000, le=50000)
    include_tables: bool = True
    include_references: bool = False
    dry_run: bool = False
    verbosity: Verbosity = "standard"


class PublicationContextEstimateRequest(BaseModel):
    """Request for estimating compact publication context size."""

    pmids: list[str] = Field(min_length=1, max_length=25)
    sections: list[str] = Field(default_factory=list)
    mode: PublicationPassageMode = "compact_passages"
    full: bool = False
    max_passages_per_pmid: int = Field(default=6, ge=1, le=30)
    include_tables: bool = True
    include_references: bool = False


class PublicationPassage(BaseModel):
    """One compact, citable publication passage."""

    passage_id: str
    pmid: str
    pmcid: str | None = None
    section: str
    text: str
    char_count: int
    source: PublicationPassageSource


class PassageDropReason(BaseModel):
    """Reason a source passage was omitted from compact output."""

    reason: PassageDropReasonCode
    pmid: str | None = None
    section: str | None = None
    passage_id: str | None = None
    message: str | None = None


class FailedPublicationPmid(BaseModel):
    """PMID that could not produce any PubTator passages."""

    pmid: str
    reason: str


class PublicationContextEstimate(BaseModel):
    """Estimated compact context size without raw BioC content."""

    estimated_passages: int = Field(ge=0)
    estimated_chars: int = Field(ge=0)
    sections_by_pmid: dict[str, list[str]]
    recommended_mode: PublicationPassageMode
    warning: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recommended_max_chars(self) -> int:
        """Recommended get_publication_passages max_chars with safety margin."""
        with_margin = (
            self.estimated_chars * RECOMMENDED_CONTEXT_SAFETY_NUMERATOR
            + RECOMMENDED_CONTEXT_SAFETY_DENOMINATOR
            - 1
        ) // RECOMMENDED_CONTEXT_SAFETY_DENOMINATOR
        return min(MAX_PUBLICATION_PASSAGE_CHARS, max(1000, with_margin))


class PublicationPassageResponse(BaseModel):
    """Compact publication passage response."""

    success: bool = True
    pmids: list[str]
    mode: PublicationPassageMode
    passages: list[PublicationPassage]
    dropped: list[PassageDropReason] = Field(default_factory=list)
    context_estimate: PublicationContextEstimate
    coverage_by_pmid: dict[str, PublicationCoverage] = Field(default_factory=dict)
    coverage_reason_by_pmid: dict[str, str] = Field(default_factory=dict)
    failed_pmids: list[FailedPublicationPmid] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    cache_key: str | None = None
    corpus_snapshot_date: str | None = None
    source_versions: dict[str, str] = Field(default_factory=dict)
    degraded_mode: DegradedMode | None = None
    dry_run: bool = False


class PublicationContextEstimateResponse(PublicationContextEstimate):
    """Context estimate response."""

    success: bool = True
    pmids: list[str]
    mode: PublicationPassageMode
