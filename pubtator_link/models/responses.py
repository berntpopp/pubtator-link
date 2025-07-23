"""Response models for PubTator-Link API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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

    documents: List[PublicationAnnotation] = Field(
        default_factory=list, description="Exported publication documents"
    )
    format: str = Field(..., description="Export format used")
    pmids: List[str] = Field(..., description="Requested PMIDs")
    total_documents: int = Field(..., description="Total number of documents")


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

    identifier: str = Field(..., description="Entity identifier")
    name: str = Field(..., description="Entity name")
    type: str = Field(..., description="Entity type")
    score: Optional[float] = Field(default=None, description="Match score")
    synonyms: List[str] = Field(default_factory=list, description="Entity synonyms")


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
    abstract: Optional[str] = Field(default=None, description="Article abstract")
    authors: List[str] = Field(default_factory=list, description="Authors")
    journal: Optional[str] = Field(default=None, description="Journal name")
    pub_date: Optional[str] = Field(default=None, description="Publication date")
    annotations: List[Dict[str, Any]] = Field(
        default_factory=list, description="Annotations found"
    )
    score: Optional[float] = Field(default=None, description="Relevance score")


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

    entity_id: str = Field(..., description="Entity identifier")
    entity_name: str = Field(..., description="Entity name")
    entity_type: str = Field(..., description="Entity type")
    relation_type: str = Field(..., description="Relation type")
    confidence: Optional[float] = Field(default=None, description="Relation confidence")
    pmids: List[str] = Field(default_factory=list, description="Supporting PMIDs")


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
