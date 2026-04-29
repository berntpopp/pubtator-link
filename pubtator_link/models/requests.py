"""Request models for PubTator-Link API."""

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SearchSortOrder(StrEnum):
    """Supported sort orders for publication search."""

    DATE_DESC = "date desc"
    DATE_ASC = "date asc"
    SCORE_DESC = "score desc"
    SCORE_ASC = "score asc"


class PublicationType(StrEnum):
    """Publication type filter options based on PubTator3 API."""

    # Primary research types
    JOURNAL_ARTICLE = "Journal Article"  # Most common type (58 in example)
    RESEARCH_ARTICLE = "Research Article"
    ORIGINAL_ARTICLE = "Original Article"

    # Review types
    REVIEW = "Review"  # Second most common (10 in example)
    SYSTEMATIC_REVIEW = "Systematic Review"
    META_ANALYSIS = "Meta-Analysis"
    NARRATIVE_REVIEW = "Narrative Review"

    # Clinical study types
    CLINICAL_TRIAL = "Clinical Trial"  # (2 in example)
    RANDOMIZED_CONTROLLED_TRIAL = "Randomized Controlled Trial"  # (2 in example)
    CONTROLLED_CLINICAL_TRIAL = "Controlled Clinical Trial"
    MULTICENTER_STUDY = "Multicenter Study"  # (2 in example)
    CLINICAL_STUDY = "Clinical Study"
    PHASE_I_TRIAL = "Phase I Clinical Trial"
    PHASE_II_TRIAL = "Phase II Clinical Trial"
    PHASE_III_TRIAL = "Phase III Clinical Trial"
    PHASE_IV_TRIAL = "Phase IV Clinical Trial"

    # Case studies
    CASE_REPORT = "Case Report"
    CASE_SERIES = "Case Series"
    CASE_CONTROL_STUDY = "Case-Control Study"

    # Observational studies
    COHORT_STUDY = "Cohort Study"
    CROSS_SECTIONAL_STUDY = "Cross-Sectional Study"
    LONGITUDINAL_STUDY = "Longitudinal Study"
    PROSPECTIVE_STUDY = "Prospective Study"
    RETROSPECTIVE_STUDY = "Retrospective Study"

    # Editorial content
    EDITORIAL = "Editorial"
    LETTER = "Letter"
    COMMENT = "Comment"
    OPINION = "Opinion"
    PERSPECTIVE = "Perspective"

    # News and communications
    NEWS = "News"
    CORRESPONDENCE = "Correspondence"
    BRIEF_COMMUNICATION = "Brief Communication"

    # Conference and academic
    CONFERENCE_PAPER = "Conference Paper"
    CONFERENCE_ABSTRACT = "Conference Abstract"
    THESIS = "Thesis"
    DISSERTATION = "Dissertation"

    # Guidelines and recommendations
    GUIDELINE = "Guideline"
    PRACTICE_GUIDELINE = "Practice Guideline"
    CONSENSUS_STATEMENT = "Consensus Statement"
    POSITION_STATEMENT = "Position Statement"


class SearchSection(StrEnum):
    """Document sections available for targeted searching in PubTator3."""

    # Core sections (most commonly used)
    TITLE = "title"  # Article title
    ABSTRACT = "abstract"  # Abstract/summary section

    # Introduction sections
    INTRODUCTION = "introduction"  # Introduction section
    BACKGROUND = "background"  # Background/rationale section

    # Methodology sections
    METHODS = "methods"  # Methods/methodology section
    MATERIALS_AND_METHODS = "materials_and_methods"  # Materials and methods
    EXPERIMENTAL_PROCEDURES = "experimental_procedures"  # Experimental procedures

    # Results sections
    RESULTS = "results"  # Results section
    FINDINGS = "findings"  # Findings section

    # Analysis sections
    DISCUSSION = "discussion"  # Discussion section
    ANALYSIS = "analysis"  # Analysis section
    INTERPRETATION = "interpretation"  # Interpretation section

    # Conclusion sections
    CONCLUSION = "conclusion"  # Conclusion section
    CONCLUSIONS = "conclusions"  # Conclusions (plural)
    SUMMARY = "summary"  # Summary section

    # Reference sections
    REFERENCES = "references"  # Reference list
    BIBLIOGRAPHY = "bibliography"  # Bibliography

    # Supplementary content
    SUPPLEMENTARY = "supplementary"  # Supplementary material
    APPENDIX = "appendix"  # Appendix sections

    # Full document
    FULL_TEXT = "fulltext"  # Entire document text
    BODY = "body"  # Main body text (excluding title/abstract)

    # Figure and table content
    FIGURE_CAPTIONS = "figure_captions"  # Figure captions
    TABLE_CAPTIONS = "table_captions"  # Table captions
    CAPTIONS = "captions"  # All captions

    # Author information
    AUTHOR_INFORMATION = "author_information"  # Author affiliations and info
    ACKNOWLEDGMENTS = "acknowledgments"  # Acknowledgments section


class SearchFilters(BaseModel):
    """Advanced search filters for PubTator3 API."""

    type: list[PublicationType] | None = Field(
        default=None,
        description="Filter by publication types (e.g., Review, Research Article)",
    )
    journal: list[str] | None = Field(default=None, description="Filter by specific journal names")
    author: list[str] | None = Field(default=None, description="Filter by author names")
    year_min: int | None = Field(
        default=None, ge=1800, le=2030, description="Minimum publication year"
    )
    year_max: int | None = Field(
        default=None, ge=1800, le=2030, description="Maximum publication year"
    )

    @field_validator("year_max")
    @classmethod
    def validate_year_range(cls, v: int | None, info: Any) -> int | None:
        """Validate year range consistency."""
        if v is not None and info.data.get("year_min") is not None and v < info.data["year_min"]:
            raise ValueError("year_max must be greater than or equal to year_min")
        return v

    def to_json_string(self) -> str:
        """Convert filters to JSON string for API."""
        filter_dict: dict[str, Any] = {}

        if self.type:
            filter_dict["type"] = [t.value for t in self.type]
        if self.journal:
            filter_dict["journal"] = self.journal
        if self.author:
            filter_dict["author"] = self.author
        if self.year_min is not None or self.year_max is not None:
            year_range: dict[str, int] = {}
            if self.year_min is not None:
                year_range["min"] = self.year_min
            if self.year_max is not None:
                year_range["max"] = self.year_max
            filter_dict["year"] = year_range

        return json.dumps(filter_dict) if filter_dict else ""


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
    concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] | None = (
        Field(default=None, description="Filter by bioconcept type")
    )
    limit: int = Field(default=10, description="Maximum number of results", ge=1, le=100)


class SearchRequest(BaseModel):
    """Request model for advanced search with filters and sections."""

    text: str = Field(
        ...,
        description="Search query (free text, entity ID, or relation)",
        min_length=1,
        max_length=1000,
    )
    page: int = Field(default=1, description="Page number for results", ge=1)
    sort: SearchSortOrder | None = Field(
        default=None,
        description="Sort order for results (default: score desc)",
    )
    filters: SearchFilters | None = Field(
        default=None,
        description="Advanced search filters (type, journal, author, year)",
    )
    sections: list[SearchSection] | None = Field(
        default=None, description="Limit search to specific document sections"
    )


class RelationsRequest(BaseModel):
    """Request model for finding related entities."""

    e1: str = Field(..., description="Primary entity ID (e.g., @CHEMICAL_remdesivir)", min_length=1)
    type: (
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
        | None
    ) = Field(default=None, description="Relation type filter")
    e2: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] | None = Field(
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

    pattern: str | None = Field(
        default=None, description="Cache key pattern to clear (clears all if None)"
    )
