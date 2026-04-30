from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pubtator_link.models.review_rerag import PrepareMode, ReviewBatchResponseMode, ReviewTableMode


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


class GetPublicationPassagesMcpRequest(BaseModel):
    """Return compact publication passages. Research use only."""

    pmids: list[str] = Field(min_length=1, max_length=25)
    sections: list[str] = Field(default_factory=list)
    mode: Literal["abstracts", "compact_passages", "section_text"] = "compact_passages"
    full: bool = False
    max_passages_per_pmid: int = Field(default=6, ge=1, le=30)
    max_chars: int = Field(default=12000, ge=1000, le=50000)
    include_tables: bool = True
    include_references: bool = False


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


class IndexReviewEvidenceMcpRequest(BaseModel):
    """Queue review-scoped evidence preparation. Research use only."""

    review_id: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    curated_urls: list[str] = Field(default_factory=list)
    prepare_mode: PrepareMode = "selected"


class InspectReviewIndexMcpRequest(BaseModel):
    """Inspect review-scoped evidence index contents. Research use only."""

    review_id: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    include_passage_samples: bool = False
    sample_per_pmid: int = Field(default=2, ge=1, le=5)


class RetrieveReviewContextMcpRequest(BaseModel):
    """Retrieve a compact review-scoped context pack. Research use only."""

    review_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages: int = Field(default=8, ge=1, le=30)
    max_chars: int = Field(default=6000, ge=500, le=30000)
    include_diagnostics: bool = False
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)


class RetrieveReviewContextBatchMcpRequest(BaseModel):
    """Retrieve multiple compact review-scoped context packs. Research use only."""

    review_id: str = Field(..., min_length=1)
    queries: list[str] = Field(min_length=1, max_length=10)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages_per_query: int = Field(default=8, ge=1, le=30)
    max_total_passages: int = Field(default=20, ge=1, le=60)
    max_chars: int = Field(default=12000, ge=500, le=50000)
    max_response_chars: int = Field(default=24000, ge=2000, le=100000)
    deduplicate_passages: bool = True
    include_diagnostics: bool = True
    response_mode: ReviewBatchResponseMode = "compact"
    include_tables: bool = False
    include_references: bool = False
    table_mode: ReviewTableMode = "preview"
    allow_truncated_passages: bool = True
    max_chars_per_passage: int = Field(default=2200, ge=300, le=10000)
