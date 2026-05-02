"""Variant evidence lookup models."""

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from pubtator_link.models.publication_metadata import PublicationMetadata

VariantEvidenceSource = Literal["clinvar", "pubtator"]


class VariantEvidenceRequest(BaseModel):
    """Request source-attributed evidence for a gene and variant expression."""

    gene: str = Field(min_length=1)
    variant: str | None = Field(default=None, min_length=1)
    protein: str | None = Field(default=None, min_length=1)
    condition: str | None = Field(default=None, min_length=1)
    sources: list[VariantEvidenceSource] = Field(
        default_factory=lambda: ["clinvar", "pubtator"]
    )
    max_literature_pmids: int = Field(default=20, ge=0, le=100)
    include_citations: bool = True

    @model_validator(mode="after")
    def require_variant_expression(self) -> Self:
        if not self.variant and not self.protein:
            raise ValueError("variant or protein is required")
        return self


class NormalizedVariant(BaseModel):
    """Source-provided normalized variant identity."""

    source: VariantEvidenceSource
    name: str
    variation_id: str | None = None
    allele_id: str | None = None
    hgvs: list[str] = Field(default_factory=list)
    url: str | None = None


class SourceClassification(BaseModel):
    """Source-attributed clinical significance label."""

    source: VariantEvidenceSource
    classification: str
    review_status: str | None = None
    condition: str | None = None
    last_evaluated: str | None = None
    variation_id: str | None = None
    allele_id: str | None = None
    url: str | None = None


class VariantLiteratureEvidence(BaseModel):
    """PubTator literature evidence for a variant query."""

    pmid: str
    title: str | None = None
    snippet: str | None = None
    citation_metadata: PublicationMetadata | None = None
    source: Literal["pubtator"] = "pubtator"


class VariantConflict(BaseModel):
    """Conflict summary across source-attributed records."""

    description: str
    sources: list[str] = Field(default_factory=list)


class VariantEvidenceResponse(BaseModel):
    """Combined source-attributed variant evidence."""

    success: bool = True
    query: dict[str, Any]
    normalized_variants: list[NormalizedVariant] = Field(default_factory=list)
    source_classifications: list[SourceClassification] = Field(default_factory=list)
    literature: list[VariantLiteratureEvidence] = Field(default_factory=list)
    conflicts: list[VariantConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
