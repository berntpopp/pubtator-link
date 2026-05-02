"""Response models for PubTator-Link API."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from pubtator_link.models.publication_metadata import PublicationAuthor


class BaseResponse(BaseModel):
    """Base response model with common fields."""

    success: bool = Field(default=True, description="Request success status")
    message: str | None = Field(default=None, description="Response message")


class ErrorResponse(BaseResponse):
    """Error response model."""

    success: bool = Field(default=False)
    error_code: str = Field(..., description="Error code")
    error_details: dict[str, Any] | None = Field(
        default=None, description="Additional error details"
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy", description="Service status")
    version: str = Field(default="1.0.0", description="Service version")
    uptime: float | None = Field(default=None, description="Uptime in seconds")


class DiagnosticsResponse(BaseResponse):
    """Subsystem diagnostics for MCP and readiness recovery."""

    status: str = Field(..., description="ready, degraded, or not_ready")
    subsystems: dict[str, dict[str, Any]] = Field(default_factory=dict)
    recovery: list[str] = Field(default_factory=list)


class PublicationAnnotation(BaseModel):
    """Publication annotation model."""

    id: str = Field(..., description="Annotation ID")
    infons: dict[str, Any] = Field(default_factory=dict, description="Annotation metadata")
    text: str | None = Field(default=None, description="Annotation text")
    annotations: list[dict[str, Any]] = Field(
        default_factory=list, description="List of annotations"
    )
    relations: list[dict[str, Any]] = Field(default_factory=list, description="List of relations")


class PublicationExportResponse(BaseResponse):
    """Response model for publication export."""

    format: str = Field(..., description="Export format used")
    pmids: list[str] | None = Field(default=None, description="Requested PMIDs")
    pmcids: list[str] | None = Field(default=None, description="Requested PMC IDs")
    full_text: bool = Field(default=False, description="Whether full text was included")
    export_data: dict[str, Any] = Field(..., description="Exported data")
    count: int = Field(..., description="Number of exported items")


class PMCExportResponse(BaseResponse):
    """Response model for PMC export."""

    documents: list[PublicationAnnotation] = Field(
        default_factory=list, description="Exported PMC documents"
    )
    format: str = Field(..., description="Export format used")
    pmcids: list[str] = Field(..., description="Requested PMC IDs")
    total_documents: int = Field(..., description="Total number of documents")


class EntityMatch(BaseModel):
    """Entity autocomplete match."""

    identifier: str = Field(..., description="Entity identifier")  # _id from API
    name: str = Field(..., description="Entity name")
    type: str = Field(..., description="Entity type")  # biotype from API
    score: float | None = Field(default=None, description="Match score")
    synonyms: list[str] = Field(default_factory=list, description="Entity synonyms")
    matched_terms: list[str] = Field(
        default_factory=list,
        description="Terms derived from upstream match metadata",
    )

    # Additional fields from actual API response
    db_id: str | None = Field(default=None, description="Database ID")
    db: str | None = Field(default=None, description="Database name")
    match: str | None = Field(default=None, description="Match description")

    @field_validator("identifier", mode="before")
    @classmethod
    def map_id_field(cls, v: Any, info: Any) -> Any:
        """Map _id field to identifier if present."""
        if isinstance(info.data, dict) and "_id" in info.data:
            return info.data["_id"]
        return v

    @field_validator("type", mode="before")
    @classmethod
    def map_biotype_field(cls, v: Any, info: Any) -> Any:
        """Map biotype field to type if present."""
        if isinstance(info.data, dict) and "biotype" in info.data:
            return info.data["biotype"]
        return v


class EntityAutocompleteResponse(BaseResponse):
    """Response model for entity autocomplete."""

    query: str = Field(..., description="Original query")
    matches: list[EntityMatch] = Field(default_factory=list, description="Entity matches")
    total_matches: int = Field(..., description="Total number of matches")
    concept_filter: str | None = Field(default=None, description="Applied concept filter")


class SearchResult(BaseModel):
    """Individual search result."""

    @model_validator(mode="before")
    @classmethod
    def map_pubtator_metadata(cls, data: Any) -> Any:
        """Map PubTator3 metadata aliases into public response fields."""
        if not isinstance(data, dict):
            return data
        mapped = dict(data)
        if mapped.get("pub_date") is None:
            mapped["pub_date"] = mapped.get("meta_date_publication") or mapped.get("date")
        if mapped.get("volume") is None and mapped.get("meta_volume") is not None:
            mapped["volume"] = mapped["meta_volume"]
        if mapped.get("issue") is None and mapped.get("meta_issue") is not None:
            mapped["issue"] = mapped["meta_issue"]
        if mapped.get("pages") is None and mapped.get("meta_pages") is not None:
            mapped["pages"] = mapped["meta_pages"]
        if _coverage_hint_has_no_signal(mapped.get("coverage_hint")):
            mapped["coverage_hint"] = None
        return mapped

    pmid: str = Field(..., description="PubMed ID")
    title: str = Field(..., description="Article title")

    @field_validator("pmid", mode="before")
    @classmethod
    def convert_pmid_to_string(cls, v: str | int) -> str:
        """Convert PMID to string if it's an integer."""
        return str(v)

    abstract: str | None = Field(default=None, description="Article abstract")
    authors: list[PublicationAuthor] = Field(default_factory=list, description="Authors")
    pub_year: int | None = Field(default=None, description="Publication year")
    journal: str | None = Field(default=None, description="Journal name")
    pub_date: str | None = Field(default=None, description="Publication date")
    annotations: list[dict[str, Any]] = Field(default_factory=list, description="Annotations found")
    score: float | None = Field(default=None, description="Relevance score")

    # Additional fields from actual API response
    pmcid: str | None = Field(default=None, description="PMC ID if available")
    doi: str | None = Field(default=None, description="DOI")
    date: str | None = Field(default=None, description="Publication date ISO format")
    text_hl: str | None = Field(default=None, description="Highlighted text snippet")
    citations: dict[str, str] | None = Field(default=None, description="Citation formats")
    volume: str | None = Field(default=None, description="Journal volume")
    issue: str | None = Field(default=None, description="Journal issue")
    pages: str | None = Field(default=None, description="Article pages")
    publication_types: list[str] = Field(
        default_factory=list, description="Publication type metadata"
    )
    mesh_headings: list[str] = Field(default_factory=list, description="MeSH headings")
    nlm_citation: str | None = Field(default=None, description="NLM citation")
    bibtex: str | None = Field(default=None, description="BibTeX citation")
    coverage_hint: dict[str, Any] | None = Field(default=None, description="Coverage hint")
    preflight_coverage_guess: str | None = Field(
        default=None, description="Compact preflight coverage guess"
    )
    preflight_coverage_reason: str | None = Field(
        default=None, description="Compact preflight coverage reason"
    )
    preflight_confidence: Literal["high", "medium", "low"] | None = Field(
        default=None, description="Confidence of the preflight coverage guess"
    )
    rank_features: dict[str, Any] | None = Field(default=None, description="Ranking features")
    matched_terms: list[str] = Field(default_factory=list, description="Matched query terms")

    @field_validator("pub_date", mode="before")
    @classmethod
    def map_date_fields(cls, v: Any, info: Any) -> Any:
        """Map date field to pub_date if present."""
        if v is None and isinstance(info.data, dict) and "date" in info.data:
            return info.data["date"]
        return v


class SearchResponse(BaseResponse):
    """Response model for search."""

    @model_validator(mode="after")
    def populate_preflight_error_code(self) -> "SearchResponse":
        if self.preflight_failure_reason and not self.preflight_error_reason:
            self.preflight_error_reason = self.preflight_failure_reason
        if self.preflight_error_reason and not self.preflight_error_code:
            self.preflight_error_code = f"coverage_preflight_{self.preflight_error_reason}"
        return self

    query: str = Field(..., description="Original search query")
    results: list[SearchResult] = Field(default_factory=list, description="Search results")
    total_results: int = Field(..., description="Total number of results")
    page: int = Field(..., description="Current page number")
    per_page: int = Field(default=20, description="Results per page")
    total_pages: int = Field(..., description="Total number of pages")
    sort_order: str | None = Field(default=None, description="Applied sort order")
    cache_key: str | None = Field(default=None, description="Stable search cache key")
    corpus_snapshot_date: str | None = Field(
        default=None, description="Date when the live corpus was queried"
    )
    source_versions: dict[str, str] = Field(default_factory=dict, description="Source versions")
    preflight_failure_reason: str | None = Field(
        default=None, description="Backward-compatible coverage preflight failure reason"
    )
    preflight_error_reason: str | None = Field(
        default=None, description="Stable coverage preflight failure reason"
    )
    preflight_error_code: str | None = Field(
        default=None, description="Stable coverage preflight failure code"
    )


def _coverage_hint_has_no_signal(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    signal_keys = {
        "pmcid",
        "doi",
        "license_or_access_hint",
        "notes",
        "resolver_attempts",
    }
    if any(value.get(key) for key in signal_keys):
        return False
    if value.get("pmc_fallback_available"):
        return False
    return (
        value.get("expected_coverage", "unknown") == "unknown"
        and value.get("coverage_reason", "unknown") == "unknown"
    )


class RelatedEntity(BaseModel):
    """Related entity information."""

    entity_id: str = Field(..., description="Entity identifier")  # target from API
    entity_name: str | None = Field(default=None, description="Entity name")
    entity_type: str | None = Field(default=None, description="Entity type")
    relation_type: str = Field(..., description="Relation type")  # type from API
    confidence: float | None = Field(default=None, description="Relation confidence")
    pmids: list[str] = Field(default_factory=list, description="Supporting PMIDs")

    # Fields from actual API response
    source: str | None = Field(default=None, description="Source entity")
    target: str = Field(..., description="Target entity")
    publications: int | None = Field(default=None, description="Number of publications")

    @field_validator("entity_id", mode="before")
    @classmethod
    def map_target_to_entity_id(cls, v: Any, info: Any) -> Any:
        """Map target field to entity_id if present."""
        if v is None and isinstance(info.data, dict) and "target" in info.data:
            return info.data["target"]
        return v

    @field_validator("relation_type", mode="before")
    @classmethod
    def map_type_to_relation_type(cls, v: Any, info: Any) -> Any:
        """Map type field to relation_type if present."""
        if isinstance(info.data, dict) and "type" in info.data:
            return info.data["type"]
        return v


class RelationsResponse(BaseResponse):
    """Response model for relations."""

    primary_entity: str = Field(..., description="Primary entity ID")
    related_entities: list[RelatedEntity] = Field(
        default_factory=list, description="Related entities"
    )
    total_relations: int = Field(..., description="Total number of relations")
    relation_filter: str | None = Field(default=None, description="Applied relation type filter")
    entity_filter: str | None = Field(default=None, description="Applied entity type filter")


class AnnotationEntity(BaseModel):
    """Annotated entity in text."""

    start: int = Field(..., description="Start position in text")
    end: int = Field(..., description="End position in text")
    text: str = Field(..., description="Entity text")
    entity_id: str = Field(..., description="Entity identifier")
    entity_type: str = Field(..., description="Entity type")
    confidence: float | None = Field(default=None, description="Annotation confidence")


class TextAnnotationSubmitResponse(BaseResponse):
    """Response for text annotation submission."""

    session_id: str = Field(..., description="Session ID for retrieval")
    status: str = Field(default="submitted", description="Processing status")
    bioconcepts: list[str] = Field(..., description="Bioconcept types being processed")
    estimated_time: int | None = Field(
        default=None, description="Estimated processing time in seconds"
    )


class TextAnnotationResultResponse(BaseResponse):
    """Response for text annotation results."""

    session_id: str = Field(..., description="Session ID")
    status: str = Field(..., description="Processing status")
    original_text: str = Field(..., description="Original input text")
    bioconcept: str = Field(..., description="Bioconcept type processed")
    annotations: list[AnnotationEntity] = Field(
        default_factory=list, description="Extracted annotations"
    )
    processing_time: float | None = Field(default=None, description="Processing time in seconds")


class CacheStats(BaseModel):
    """Cache statistics."""

    total_size: int = Field(..., description="Total cache size")
    current_size: int = Field(..., description="Current number of items")
    hit_rate: float = Field(..., description="Cache hit rate")
    miss_rate: float = Field(..., description="Cache miss rate")
    total_hits: int = Field(default=0, description="Total cache hits")
    total_misses: int = Field(default=0, description="Total cache misses")


class CacheStatsResponse(BaseResponse):
    """Response for cache statistics."""

    stats: CacheStats = Field(..., description="Cache statistics")
    detailed_stats: dict[str, Any] | None = Field(
        default=None, description="Detailed cache information"
    )


class CacheClearResponse(BaseResponse):
    """Response for cache clearing."""

    cleared_items: int = Field(..., description="Number of items cleared")
    pattern: str | None = Field(default=None, description="Pattern used for clearing")
