"""Response models for PubTator-Link API."""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class BaseResponse(BaseModel):
    """Base response model with common fields."""

    success: bool = Field(default=True, description="Request success status")
    message: Optional[str] = Field(default=None, description="Response message")


class ErrorResponse(BaseResponse):
    """Error response model."""

    success: bool = Field(default=False)
    error_code: str = Field(..., description="Error code")
    error_details: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional error details"
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy", description="Service status")
    version: str = Field(default="1.0.0", description="Service version")
    uptime: Optional[float] = Field(default=None, description="Uptime in seconds")


class PublicationAnnotation(BaseModel):
    """Publication annotation model."""

    id: str = Field(..., description="Annotation ID")
    infons: Dict[str, Any] = Field(
        default_factory=dict, description="Annotation metadata"
    )
    text: Optional[str] = Field(default=None, description="Annotation text")
    annotations: List[Dict[str, Any]] = Field(
        default_factory=list, description="List of annotations"
    )
    relations: List[Dict[str, Any]] = Field(
        default_factory=list, description="List of relations"
    )


class PublicationExportResponse(BaseResponse):
    """Response model for publication export."""

    format: str = Field(..., description="Export format used")
    pmids: Optional[List[str]] = Field(default=None, description="Requested PMIDs")
    pmcids: Optional[List[str]] = Field(default=None, description="Requested PMC IDs")
    full_text: bool = Field(default=False, description="Whether full text was included")
    export_data: Dict[str, Any] = Field(..., description="Exported data")
    count: int = Field(..., description="Number of exported items")


class PMCExportResponse(BaseResponse):
    """Response model for PMC export."""

    documents: List[PublicationAnnotation] = Field(
        default_factory=list, description="Exported PMC documents"
    )
    format: str = Field(..., description="Export format used")
    pmcids: List[str] = Field(..., description="Requested PMC IDs")
    total_documents: int = Field(..., description="Total number of documents")


class EntityMatch(BaseModel):
    """Entity autocomplete match."""

    identifier: str = Field(..., description="Entity identifier")  # _id from API
    name: str = Field(..., description="Entity name")
    type: str = Field(..., description="Entity type")  # biotype from API
    score: Optional[float] = Field(default=None, description="Match score")
    synonyms: List[str] = Field(default_factory=list, description="Entity synonyms")

    # Additional fields from actual API response
    db_id: Optional[str] = Field(default=None, description="Database ID")
    db: Optional[str] = Field(default=None, description="Database name")
    match: Optional[str] = Field(default=None, description="Match description")

    @field_validator("identifier", mode="before")
    @classmethod
    def map_id_field(cls, v, info):
        """Map _id field to identifier if present."""
        if isinstance(info.data, dict) and "_id" in info.data:
            return info.data["_id"]
        return v

    @field_validator("type", mode="before")
    @classmethod
    def map_biotype_field(cls, v, info):
        """Map biotype field to type if present."""
        if isinstance(info.data, dict) and "biotype" in info.data:
            return info.data["biotype"]
        return v


class EntityAutocompleteResponse(BaseResponse):
    """Response model for entity autocomplete."""

    query: str = Field(..., description="Original query")
    matches: List[EntityMatch] = Field(
        default_factory=list, description="Entity matches"
    )
    total_matches: int = Field(..., description="Total number of matches")
    concept_filter: Optional[str] = Field(
        default=None, description="Applied concept filter"
    )


class SearchResult(BaseModel):
    """Individual search result."""

    pmid: str = Field(..., description="PubMed ID")
    title: str = Field(..., description="Article title")

    @field_validator("pmid", mode="before")
    @classmethod
    def convert_pmid_to_string(cls, v: Union[str, int]) -> str:
        """Convert PMID to string if it's an integer."""
        return str(v)

    abstract: Optional[str] = Field(default=None, description="Article abstract")
    authors: List[str] = Field(default_factory=list, description="Authors")
    journal: Optional[str] = Field(default=None, description="Journal name")
    pub_date: Optional[str] = Field(default=None, description="Publication date")
    annotations: List[Dict[str, Any]] = Field(
        default_factory=list, description="Annotations found"
    )
    score: Optional[float] = Field(default=None, description="Relevance score")

    # Additional fields from actual API response
    pmcid: Optional[str] = Field(default=None, description="PMC ID if available")
    doi: Optional[str] = Field(default=None, description="DOI")
    date: Optional[str] = Field(default=None, description="Publication date ISO format")
    text_hl: Optional[str] = Field(default=None, description="Highlighted text snippet")
    citations: Optional[Dict[str, str]] = Field(
        default=None, description="Citation formats"
    )

    @field_validator("pub_date", mode="before")
    @classmethod
    def map_date_fields(cls, v, info):
        """Map date field to pub_date if present."""
        if v is None and isinstance(info.data, dict) and "date" in info.data:
            return info.data["date"]
        return v


class SearchResponse(BaseResponse):
    """Response model for search."""

    query: str = Field(..., description="Original search query")
    results: List[SearchResult] = Field(
        default_factory=list, description="Search results"
    )
    total_results: int = Field(..., description="Total number of results")
    page: int = Field(..., description="Current page number")
    per_page: int = Field(default=20, description="Results per page")
    total_pages: int = Field(..., description="Total number of pages")


class RelatedEntity(BaseModel):
    """Related entity information."""

    entity_id: str = Field(..., description="Entity identifier")  # target from API
    entity_name: Optional[str] = Field(default=None, description="Entity name")
    entity_type: Optional[str] = Field(default=None, description="Entity type")
    relation_type: str = Field(..., description="Relation type")  # type from API
    confidence: Optional[float] = Field(default=None, description="Relation confidence")
    pmids: List[str] = Field(default_factory=list, description="Supporting PMIDs")

    # Fields from actual API response
    source: Optional[str] = Field(default=None, description="Source entity")
    target: str = Field(..., description="Target entity")
    publications: Optional[int] = Field(
        default=None, description="Number of publications"
    )

    @field_validator("entity_id", mode="before")
    @classmethod
    def map_target_to_entity_id(cls, v, info):
        """Map target field to entity_id if present."""
        if v is None and isinstance(info.data, dict) and "target" in info.data:
            return info.data["target"]
        return v

    @field_validator("relation_type", mode="before")
    @classmethod
    def map_type_to_relation_type(cls, v, info):
        """Map type field to relation_type if present."""
        if isinstance(info.data, dict) and "type" in info.data:
            return info.data["type"]
        return v


class RelationsResponse(BaseResponse):
    """Response model for relations."""

    primary_entity: str = Field(..., description="Primary entity ID")
    related_entities: List[RelatedEntity] = Field(
        default_factory=list, description="Related entities"
    )
    total_relations: int = Field(..., description="Total number of relations")
    relation_filter: Optional[str] = Field(
        default=None, description="Applied relation type filter"
    )
    entity_filter: Optional[str] = Field(
        default=None, description="Applied entity type filter"
    )


class AnnotationEntity(BaseModel):
    """Annotated entity in text."""

    start: int = Field(..., description="Start position in text")
    end: int = Field(..., description="End position in text")
    text: str = Field(..., description="Entity text")
    entity_id: str = Field(..., description="Entity identifier")
    entity_type: str = Field(..., description="Entity type")
    confidence: Optional[float] = Field(
        default=None, description="Annotation confidence"
    )


class TextAnnotationSubmitResponse(BaseResponse):
    """Response for text annotation submission."""

    session_id: str = Field(..., description="Session ID for retrieval")
    status: str = Field(default="submitted", description="Processing status")
    bioconcepts: List[str] = Field(..., description="Bioconcept types being processed")
    estimated_time: Optional[int] = Field(
        default=None, description="Estimated processing time in seconds"
    )


class TextAnnotationResultResponse(BaseResponse):
    """Response for text annotation results."""

    session_id: str = Field(..., description="Session ID")
    status: str = Field(..., description="Processing status")
    original_text: str = Field(..., description="Original input text")
    bioconcept: str = Field(..., description="Bioconcept type processed")
    annotations: List[AnnotationEntity] = Field(
        default_factory=list, description="Extracted annotations"
    )
    processing_time: Optional[float] = Field(
        default=None, description="Processing time in seconds"
    )


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
    detailed_stats: Optional[Dict[str, Any]] = Field(
        default=None, description="Detailed cache information"
    )


class CacheClearResponse(BaseResponse):
    """Response for cache clearing."""

    cleared_items: int = Field(..., description="Number of items cleared")
    pattern: Optional[str] = Field(
        default=None, description="Pattern used for clearing"
    )
