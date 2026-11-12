"""Compact publication passage models."""

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from pubtator_link.mcp.untrusted_content import UntrustedText, fence_untrusted_text
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dropped_summary(self) -> dict[str, dict[str, int]]:
        """Drop counts as ``{reason: {section: count}}`` (#244)."""
        summary: dict[str, dict[str, int]] = {}
        for drop in self.dropped:
            by_section = summary.setdefault(drop.reason, {})
            section = drop.section or "unknown"
            by_section[section] = by_section.get(section, 0) + 1
        return summary

    @computed_field  # type: ignore[prop-decorator]
    @property
    def truncated_sections(self) -> list[str]:
        """Sections the per-PMID cap or the char budget cut short (#244)."""
        cut = {"max_passages_per_pmid_exceeded", "char_budget_exceeded"}
        return sorted(
            {drop.section for drop in self.dropped if drop.reason in cut and drop.section}
        )

    def model_dump_mcp(self, verbosity: Verbosity = "standard") -> dict[str, object]:
        """Serialize with external passage prose fenced for the MCP boundary.

        Individual ``dropped`` rows are listed only at ``verbosity='full'``;
        ``dropped_summary`` carries the counts otherwise (#244).
        """
        fenced_passages: list[MCPPublicationPassage] = []
        for passage in self.passages:
            fenced = fence_untrusted_text(
                passage.text,
                source=passage.source,
                record_id=f"PMID:{passage.pmid}#{passage.passage_id}",
            )
            fenced_passages.append(
                MCPPublicationPassage(
                    **passage.model_dump(exclude={"text", "char_count"}),
                    text=fenced,
                    char_count=len(fenced.text),
                )
            )
        dropped = (
            self.dropped
            if verbosity == "full"
            else [drop for drop in self.dropped if drop.reason == "upstream_error"]
        )
        return MCPPublicationPassageResponse(
            **self.model_dump(exclude={"passages", "dropped"}),
            passages=fenced_passages,
            dropped=dropped,
        ).model_dump()


class MCPPublicationPassage(BaseModel):
    """One publication passage fenced for the public MCP response."""

    passage_id: str
    pmid: str
    pmcid: str | None = None
    section: str
    text: UntrustedText
    char_count: int
    source: PublicationPassageSource


class MCPPublicationPassageResponse(BaseModel):
    """MCP-only response whose external passage prose is structurally fenced."""

    success: bool = True
    pmids: list[str]
    mode: PublicationPassageMode
    passages: list[MCPPublicationPassage]
    dropped: list[PassageDropReason] = Field(default_factory=list)
    dropped_summary: dict[str, dict[str, int]] = Field(default_factory=dict)
    truncated_sections: list[str] = Field(default_factory=list)
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
