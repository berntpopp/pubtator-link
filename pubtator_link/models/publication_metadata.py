"""Typed publication metadata models for citation-oriented tools."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from pubtator_link.models.review_rerag import CoverageReason, CoverageTier


def _normalize_pmid(pmid: str) -> str:
    clean_pmid = pmid.strip()
    if clean_pmid.upper().startswith("PMID:"):
        clean_pmid = clean_pmid[5:].strip()
    return clean_pmid


def _normalize_and_validate_pmid(pmid: str) -> str:
    clean_pmid = _normalize_pmid(pmid)
    if not clean_pmid:
        raise ValueError("PMID is required")
    if not clean_pmid.isdigit():
        raise ValueError("PMID must be numeric")
    return clean_pmid


class PublicationAuthor(BaseModel):
    """Structured author metadata from PubMed citation records."""

    last_name: str | None = None
    fore_name: str | None = None
    initials: str | None = None
    collective_name: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_name(self) -> str:
        """Author display name suitable for compact citation strings."""
        if self.collective_name:
            return self.collective_name

        name = " ".join(part for part in (self.last_name, self.initials) if part)
        return name or self.fore_name or ""


class PublicationMetadata(BaseModel):
    """Citation and source coverage metadata for one publication."""

    pmid: str
    title: str | None = None
    journal: str | None = None
    pub_year: int | None = None
    pub_date: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    authors: list[PublicationAuthor] = Field(default_factory=list)
    publication_types: list[str] = Field(default_factory=list)
    mesh_headings: list[str] = Field(default_factory=list)
    nlm_citation: str | None = None
    bibtex: str | None = None
    coverage: CoverageTier = "unknown"
    coverage_reason: CoverageReason | None = None

    @field_validator("pmid")
    @classmethod
    def normalize_pmid(cls, pmid: str) -> str:
        return _normalize_and_validate_pmid(pmid)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def citation_key(self) -> str:
        """Stable PMID-backed citation key."""
        return f"PMID:{self.pmid}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def vancouver_author_string(self) -> str:
        """Compact Vancouver-style author list."""
        author_names = [author.display_name for author in self.authors if author.display_name]
        if len(author_names) > 6:
            author_names = [*author_names[:6], "et al"]
        return ", ".join(author_names)


class PublicationMetadataRequest(BaseModel):
    """Request for publication metadata lookup."""

    pmids: list[str] = Field(min_length=1, max_length=100)
    include_mesh: bool = True
    include_publication_types: bool = True
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "both"
    include_coverage: bool = True

    @field_validator("pmids")
    @classmethod
    def normalize_pmids(cls, pmids: list[str]) -> list[str]:
        normalized_pmids: list[str] = []
        seen_pmids: set[str] = set()
        for pmid in pmids:
            clean_pmid = _normalize_pmid(pmid)
            if not clean_pmid:
                continue
            if not clean_pmid.isdigit():
                raise ValueError("PMID must be numeric")
            if clean_pmid not in seen_pmids:
                normalized_pmids.append(clean_pmid)
                seen_pmids.add(clean_pmid)
        if not normalized_pmids:
            raise ValueError("at least one PMID is required")
        return normalized_pmids


class PublicationMetadataResponse(BaseModel):
    """Response containing publication metadata records and lookup failures."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    success: bool = True
    metadata: list[PublicationMetadata] = Field(default_factory=list)
    failed_pmids: dict[str, str] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")
