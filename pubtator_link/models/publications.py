"""Publication models for PubTator-Link."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from .entities import EntityRelation, TextAnnotation


class Author(BaseModel):
    """Author information."""

    name: str = Field(..., description="Author name")
    affiliation: Optional[str] = Field(default=None, description="Author affiliation")
    orcid: Optional[str] = Field(default=None, description="ORCID identifier")


class Journal(BaseModel):
    """Journal information."""

    title: str = Field(..., description="Journal title")
    issn: Optional[str] = Field(default=None, description="ISSN")
    volume: Optional[str] = Field(default=None, description="Volume")
    issue: Optional[str] = Field(default=None, description="Issue")
    pages: Optional[str] = Field(default=None, description="Page range")
    impact_factor: Optional[float] = Field(default=None, description="Impact factor")


class PublicationMetadata(BaseModel):
    """Publication metadata."""

    pmid: str = Field(..., description="PubMed ID")
    pmcid: Optional[str] = Field(default=None, description="PMC ID")
    doi: Optional[str] = Field(default=None, description="DOI")
    title: str = Field(..., description="Article title")
    abstract: Optional[str] = Field(default=None, description="Abstract text")
    authors: list[Author] = Field(default_factory=list, description="Authors")
    journal: Optional[Journal] = Field(default=None, description="Journal information")
    publication_date: Optional[datetime] = Field(default=None, description="Publication date")
    publication_year: Optional[int] = Field(default=None, description="Publication year")
    mesh_terms: list[str] = Field(default_factory=list, description="MeSH terms")
    keywords: list[str] = Field(default_factory=list, description="Keywords")
    publication_types: list[str] = Field(default_factory=list, description="Publication types")

    @field_validator("pmid")
    @classmethod
    def validate_pmid(cls, v: str) -> str:
        """Validate PMID format."""
        if not v.isdigit():
            raise ValueError("PMID must be numeric")
        return v

    @field_validator("pmcid")
    @classmethod
    def validate_pmcid(cls, v: Optional[str]) -> Optional[str]:
        """Validate PMC ID format."""
        if v is None:
            return v
        if not v.upper().startswith("PMC"):
            v = f"PMC{v}"
        return v.upper()


class TextPassage(BaseModel):
    """Text passage from a publication."""

    section: str = Field(..., description="Section name (title, abstract, body)")
    text: str = Field(..., description="Text content")
    offset: int = Field(default=0, description="Character offset in document")
    annotations: list[TextAnnotation] = Field(default_factory=list, description="Text annotations")


class AnnotatedPublication(BaseModel):
    """Publication with annotations."""

    metadata: PublicationMetadata = Field(..., description="Publication metadata")
    passages: list[TextPassage] = Field(default_factory=list, description="Text passages")
    relations: list[EntityRelation] = Field(default_factory=list, description="Entity relations")
    annotation_metadata: dict[str, Any] = Field(
        default_factory=dict, description="Annotation processing metadata"
    )


class BioCDocument(BaseModel):
    """BioC format document structure."""

    id: str = Field(..., description="Document ID")
    infons: dict[str, Any] = Field(default_factory=dict, description="Document infons")
    passages: list[dict[str, Any]] = Field(default_factory=list, description="Document passages")
    annotations: list[dict[str, Any]] = Field(
        default_factory=list, description="Document annotations"
    )
    relations: list[dict[str, Any]] = Field(default_factory=list, description="Document relations")


class PubTatorDocument(BaseModel):
    """PubTator format document structure."""

    pmid: str = Field(..., description="PubMed ID")
    title_text: str = Field(..., description="Title text")
    abstract_text: Optional[str] = Field(default=None, description="Abstract text")
    annotations: list[str] = Field(default_factory=list, description="Annotation lines")
    relations: list[str] = Field(default_factory=list, description="Relation lines")


class ExportFormat(BaseModel):
    """Export format specification."""

    format_type: str = Field(..., description="Format type")
    mime_type: str = Field(..., description="MIME type")
    file_extension: str = Field(..., description="File extension")
    supports_full_text: bool = Field(default=False, description="Supports full text export")


class PublicationSearchResult(BaseModel):
    """Search result for publications."""

    pmid: str = Field(..., description="PubMed ID")
    title: str = Field(..., description="Article title")
    abstract: Optional[str] = Field(default=None, description="Abstract")
    authors: list[str] = Field(default_factory=list, description="Author names")
    journal: Optional[str] = Field(default=None, description="Journal name")
    publication_date: Optional[str] = Field(default=None, description="Publication date")
    relevance_score: Optional[float] = Field(default=None, description="Search relevance score")
    matched_entities: list[str] = Field(
        default_factory=list, description="Matched entity identifiers"
    )
    annotation_count: int = Field(default=0, description="Number of annotations")


class PublicationBatch(BaseModel):
    """Batch of publications for processing."""

    publications: list[AnnotatedPublication] = Field(
        default_factory=list, description="Publications in batch"
    )
    batch_id: str = Field(..., description="Batch identifier")
    processing_status: str = Field(default="pending", description="Processing status")
    created_at: datetime = Field(default_factory=datetime.now, description="Batch creation time")
    completed_at: Optional[datetime] = Field(default=None, description="Batch completion time")
    error_count: int = Field(default=0, description="Number of errors")
    success_count: int = Field(default=0, description="Number of successes")


# Format specifications
EXPORT_FORMATS = {
    "pubtator": ExportFormat(
        format_type="pubtator",
        mime_type="text/plain",
        file_extension=".txt",
        supports_full_text=False,
    ),
    "biocxml": ExportFormat(
        format_type="biocxml",
        mime_type="application/xml",
        file_extension=".xml",
        supports_full_text=True,
    ),
    "biocjson": ExportFormat(
        format_type="biocjson",
        mime_type="application/json",
        file_extension=".json",
        supports_full_text=True,
    ),
}
