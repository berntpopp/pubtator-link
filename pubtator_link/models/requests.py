"""Request models for PubTator-Link API."""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SearchSortOrder(str, Enum):
    """Supported sort orders for publication search."""

    DATE_DESC = "date desc"
    DATE_ASC = "date asc"
    SCORE_DESC = "score desc"
    SCORE_ASC = "score asc"


class PublicationExportRequest(BaseModel):
    """Request model for publication export."""

    pmids: list[str] = Field(..., description="List of PubMed IDs", min_length=1, max_length=100)
    format: Literal["pubtator", "biocxml", "biocjson"] = Field(
        default="biocjson", description="Export format"
    )
    full: bool = Field(default=False, description="Include full text (only for biocxml/biocjson)")

    @field_validator("pmids")
    @classmethod
    def validate_pmids(cls, v: list[str]) -> list[str]:
        """Validate PMID format."""
        validated = []
        for pmid in v:
            # Remove any non-digit characters and validate
            clean_pmid = "".join(c for c in pmid if c.isdigit())
            if not clean_pmid:
                raise ValueError(f"Invalid PMID format: {pmid}")
            validated.append(clean_pmid)
        return validated


class PMCExportRequest(BaseModel):
    """Request model for PMC export."""

    pmcids: list[str] = Field(..., description="List of PMC IDs", min_length=1, max_length=100)
    format: Literal["biocxml", "biocjson"] = Field(
        default="biocjson",
        description="Export format (PMC only supports biocxml/biocjson)",
    )

    @field_validator("pmcids")
    @classmethod
    def validate_pmcids(cls, v: list[str]) -> list[str]:
        """Validate PMC ID format."""
        validated = []
        for pmcid in v:
            # Ensure PMC prefix and clean up
            clean_pmcid = pmcid.upper().replace("PMC", "")
            clean_pmcid = "".join(c for c in clean_pmcid if c.isdigit())
            if not clean_pmcid:
                raise ValueError(f"Invalid PMCID format: {pmcid}")
            validated.append(f"PMC{clean_pmcid}")
        return validated


class EntityAutocompleteRequest(BaseModel):
    """Request model for entity autocomplete."""

    query: str = Field(..., description="Search query for entity", min_length=1, max_length=500)
    concept: Optional[Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"]] = (
        Field(default=None, description="Filter by bioconcept type")
    )
    limit: int = Field(default=10, description="Maximum number of results", ge=1, le=100)


class SearchRequest(BaseModel):
    """Request model for search."""

    text: str = Field(
        ...,
        description="Search query (free text, entity ID, or relation)",
        min_length=1,
        max_length=1000,
    )
    page: int = Field(default=1, description="Page number for results", ge=1)
    sort: Optional[SearchSortOrder] = Field(
        default=None,
        description="Sort order for results (default: score desc)",
    )


class RelationsRequest(BaseModel):
    """Request model for finding related entities."""

    e1: str = Field(..., description="Primary entity ID (e.g., @CHEMICAL_remdesivir)", min_length=1)
    type: Optional[
        Literal[
            "treat",
            "cause",
            "cotreat",
            "convert",
            "compare",
            "interact",
            "associate",
            "positive_correlate",
            "negative_correlate",
            "prevent",
            "inhibit",
            "stimulate",
            "drug_interact",
        ]
    ] = Field(default=None, description="Relation type filter")
    e2: Optional[Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"]] = Field(
        default=None, description="Target entity type filter"
    )

    @field_validator("e1")
    @classmethod
    def validate_entity_id(cls, v: str) -> str:
        """Validate entity ID format."""
        if not v.startswith("@"):
            raise ValueError("Entity ID must start with '@' (e.g., @CHEMICAL_remdesivir)")
        return v


class TextAnnotationRequest(BaseModel):
    """Request model for text annotation."""

    text: str = Field(..., description="Text to annotate", min_length=1, max_length=10000)
    bioconcept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] = Field(
        default="Gene", description="Type of bioconcept to extract"
    )


class CacheStatsRequest(BaseModel):
    """Request model for cache statistics."""

    detailed: bool = Field(default=False, description="Include detailed cache information")


class CacheClearRequest(BaseModel):
    """Request model for cache clearing."""

    pattern: Optional[str] = Field(
        default=None, description="Cache key pattern to clear (clears all if None)"
    )
