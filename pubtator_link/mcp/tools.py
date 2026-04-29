from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SearchLiteratureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    page: int = Field(default=1, ge=1, le=1000)
    sort: str | None = Field(default=None, description="Examples: 'score desc', 'date desc'.")
    filters: str | None = Field(
        default=None, description="Optional PubTator search filters as JSON."
    )
    sections: str | None = Field(default=None, description="Comma-separated document sections.")


class FetchPublicationAnnotationsRequest(BaseModel):
    pmids: list[str] = Field(min_length=1, max_length=50)
    format: Literal["pubtator", "biocxml", "biocjson"] = "biocjson"
    full: bool = False


class FetchPmcAnnotationsRequest(BaseModel):
    pmcids: list[str] = Field(min_length=1, max_length=50)
    format: Literal["biocxml", "biocjson"] = "biocjson"


class SearchBiomedicalEntitiesRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] | None = None
    limit: int = Field(default=10, ge=1, le=100)


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
