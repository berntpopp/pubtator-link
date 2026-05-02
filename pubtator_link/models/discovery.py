"""Typed models for review-feeding discovery tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ArticleIdKind = Literal["pmid", "pmcid", "doi", "auto"]
ArticleIdTarget = Literal["pmid", "pmcid", "doi"]
ArticleIdStatus = Literal["resolved", "not_found", "ambiguous", "invalid", "error"]
CitationLookupStatus = Literal["matched", "not_found", "ambiguous", "error"]
RelatedArticleMode = Literal["similar", "cited_by", "references"]
RelatedArticleStatus = Literal["found", "not_found", "error"]


class DiscoveryMeta(BaseModel):
    """Response metadata for transparent research-use discovery results."""

    research_use_only: bool = True
    source_urls: list[str] = Field(default_factory=list)
    next_commands: list[str] = Field(default_factory=list)


class ArticleIdConversionRequest(BaseModel):
    """Request to convert biomedical article identifiers."""

    ids: list[str] = Field(min_length=1, max_length=200)
    source: ArticleIdKind = "auto"
    target: list[ArticleIdTarget] | None = None


class ArticleIdConversionRecord(BaseModel):
    """One identifier conversion result."""

    input_id: str
    status: ArticleIdStatus
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    error: str | None = None


class ArticleIdConversionResponse(BaseModel):
    """Response for article identifier conversion."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    success: bool = True
    records: list[ArticleIdConversionRecord]
    candidate_pmids: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")


class MeshLookupRequest(BaseModel):
    """Request to look up MeSH descriptors relevant to a query."""

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class MeshDescriptor(BaseModel):
    """One MeSH descriptor match."""

    descriptor_ui: str
    name: str
    tree_numbers: list[str] = Field(default_factory=list)
    entry_terms: list[str] = Field(default_factory=list)
    scope_note: str | None = None


class MeshLookupResponse(BaseModel):
    """Response for MeSH descriptor lookup."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    success: bool = True
    query: str
    descriptors: list[MeshDescriptor] = Field(default_factory=list)
    candidate_pmids: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")


class CitationLookupRequest(BaseModel):
    """Request to resolve free-text citations to candidate PMIDs."""

    citations: list[str] = Field(min_length=1, max_length=100)


class CitationLookupRecord(BaseModel):
    """One citation lookup result."""

    citation: str
    status: CitationLookupStatus
    pmid: str | None = None
    title: str | None = None
    error: str | None = None


class CitationLookupResponse(BaseModel):
    """Response for citation lookup."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    success: bool = True
    records: list[CitationLookupRecord]
    candidate_pmids: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")


class RelatedArticlesRequest(BaseModel):
    """Request to find articles related to one or more PMIDs."""

    pmids: list[str] = Field(min_length=1, max_length=100)
    mode: RelatedArticleMode = "similar"
    limit: int = Field(default=20, ge=1, le=100)


class RelatedArticleRecord(BaseModel):
    """One related article lookup result."""

    source_pmid: str
    status: RelatedArticleStatus
    related_pmid: str | None = None
    title: str | None = None
    score: float | None = None
    error: str | None = None


class RelatedArticlesResponse(BaseModel):
    """Response for related article lookup."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    success: bool = True
    records: list[RelatedArticleRecord]
    candidate_pmids: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")

    @field_validator("candidate_pmids")
    @classmethod
    def deduplicate_candidate_pmids(cls, pmids: list[str]) -> list[str]:
        return list(dict.fromkeys(pmids))
