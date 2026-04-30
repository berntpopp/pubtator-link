from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pubtator_link.models.review_rerag import PrepareMode


class FetchPublicationAnnotationsRequest(BaseModel):
    pmids: list[str] = Field(min_length=1, max_length=50)
    format: Literal["pubtator", "biocxml", "biocjson"] = "biocjson"
    full: bool = False


class EstimatePublicationContextMcpRequest(BaseModel):
    """Estimate compact publication context size. Research use only."""

    pmids: list[str] = Field(min_length=1, max_length=25)
    sections: list[str] = Field(default_factory=list)
    mode: Literal["abstracts", "compact_passages", "section_text"] = "compact_passages"
    full: bool = False
    max_passages_per_pmid: int = Field(default=6, ge=1, le=30)
    include_tables: bool = True
    include_references: bool = False


class FetchPmcAnnotationsRequest(BaseModel):
    pmcids: list[str] = Field(min_length=1, max_length=50)
    format: Literal["biocxml", "biocjson"] = "biocjson"


class FindEntityRelationsRequest(BaseModel):
    entity_id: str = Field(
        min_length=1, description="PubTator entity ID such as @CHEMICAL_remdesivir."
    )
    relation_type: str | None = None
    target_entity_type: str | None = None


class SubmitTextAnnotationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    bioconcepts: str = Field(
        default="Gene", description="Comma-separated PubTator bioconcepts or 'all'."
    )


class GetTextAnnotationResultsRequest(BaseModel):
    session_id: str = Field(min_length=8)


class IndexReviewEvidenceMcpRequest(BaseModel):
    """Queue review-scoped evidence preparation. Research use only."""

    review_id: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    curated_urls: list[str] = Field(default_factory=list)
    prepare_mode: PrepareMode = "selected"
