"""Entity models for PubTator-Link."""

from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


class BioConcept(BaseModel):
    """Base bioconcept model."""

    identifier: str = Field(..., description="Entity identifier")
    name: str = Field(..., description="Primary name")
    type: str = Field(..., description="Bioconcept type")
    synonyms: list[str] = Field(default_factory=list, description="Alternative names")
    description: Optional[str] = Field(default=None, description="Entity description")
    external_ids: dict[str, str] = Field(
        default_factory=dict, description="External database identifiers"
    )


class Gene(BioConcept):
    """Gene entity model."""

    type: str = Field(default="Gene", description="Entity type")
    symbol: Optional[str] = Field(default=None, description="Gene symbol")
    full_name: Optional[str] = Field(default=None, description="Full gene name")
    organism: Optional[str] = Field(default=None, description="Organism")
    chromosome: Optional[str] = Field(default=None, description="Chromosome location")
    map_location: Optional[str] = Field(default=None, description="Map location")


class Disease(BioConcept):
    """Disease entity model."""

    type: str = Field(default="Disease", description="Entity type")
    mesh_id: Optional[str] = Field(default=None, description="MeSH identifier")
    omim_id: Optional[str] = Field(default=None, description="OMIM identifier")
    disease_class: Optional[str] = Field(default=None, description="Disease classification")


class Chemical(BioConcept):
    """Chemical entity model."""

    type: str = Field(default="Chemical", description="Entity type")
    mesh_id: Optional[str] = Field(default=None, description="MeSH identifier")
    cas_number: Optional[str] = Field(default=None, description="CAS registry number")
    pubchem_cid: Optional[str] = Field(default=None, description="PubChem CID")
    molecular_formula: Optional[str] = Field(default=None, description="Molecular formula")


class Species(BioConcept):
    """Species entity model."""

    type: str = Field(default="Species", description="Entity type")
    ncbi_taxon_id: Optional[str] = Field(default=None, description="NCBI Taxonomy ID")
    scientific_name: Optional[str] = Field(default=None, description="Scientific name")
    common_name: Optional[str] = Field(default=None, description="Common name")


class Variant(BioConcept):
    """Genetic variant entity model."""

    type: str = Field(default="Variant", description="Entity type")
    hgvs_notation: Optional[str] = Field(default=None, description="HGVS notation")
    dbsnp_id: Optional[str] = Field(default=None, description="dbSNP identifier")
    variant_type: Optional[str] = Field(default=None, description="Variant type")
    chromosome: Optional[str] = Field(default=None, description="Chromosome")
    position: Optional[int] = Field(default=None, description="Genomic position")


class CellLine(BioConcept):
    """Cell line entity model."""

    type: str = Field(default="CellLine", description="Entity type")
    cellosaurus_id: Optional[str] = Field(default=None, description="Cellosaurus identifier")
    source_organism: Optional[str] = Field(default=None, description="Source organism")
    tissue_origin: Optional[str] = Field(default=None, description="Tissue of origin")


class EntityRelation(BaseModel):
    """Relationship between entities."""

    relation_id: str = Field(..., description="Relation identifier")
    relation_type: str = Field(..., description="Type of relation")
    entity1: str = Field(..., description="First entity identifier")
    entity2: str = Field(..., description="Second entity identifier")
    confidence: Optional[float] = Field(
        default=None, description="Confidence score", ge=0.0, le=1.0
    )
    evidence_pmids: list[str] = Field(default_factory=list, description="Supporting PubMed IDs")
    evidence_count: int = Field(default=0, description="Number of supporting articles")

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        """Validate relation type."""
        valid_types = {
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
        }
        if v not in valid_types:
            raise ValueError(f"Invalid relation type: {v}")
        return v


class AnnotationLocation(BaseModel):
    """Location of an annotation in text."""

    start: int = Field(..., description="Start character position", ge=0)
    end: int = Field(..., description="End character position", ge=0)
    text: str = Field(..., description="Annotated text span")

    @field_validator("end")
    @classmethod
    def validate_end_position(cls, v: int, values: Any) -> int:
        """Validate end position is after start."""
        if "start" in values and v <= values["start"]:
            raise ValueError("End position must be greater than start position")
        return v


class TextAnnotation(BaseModel):
    """Text annotation with entity information."""

    annotation_id: str = Field(..., description="Annotation identifier")
    location: AnnotationLocation = Field(..., description="Text location")
    entity: BioConcept = Field(..., description="Annotated entity")
    confidence: Optional[float] = Field(
        default=None, description="Annotation confidence", ge=0.0, le=1.0
    )
    method: Optional[str] = Field(default=None, description="Annotation method")


# Type aliases for entity unions
AnyEntity = Union[Gene, Disease, Chemical, Species, Variant, CellLine]
EntityType = Union[
    type[Gene],
    type[Disease],
    type[Chemical],
    type[Species],
    type[Variant],
    type[CellLine],
]


def create_entity_from_type(entity_type: str, **kwargs: Any) -> AnyEntity:
    """Create entity from type string."""
    entity_classes = {
        "Gene": Gene,
        "Disease": Disease,
        "Chemical": Chemical,
        "Species": Species,
        "Variant": Variant,
        "CellLine": CellLine,
    }

    entity_class = entity_classes.get(entity_type)
    if not entity_class:
        raise ValueError(f"Unknown entity type: {entity_type}")

    return entity_class(**kwargs)  # type: ignore[no-any-return]
