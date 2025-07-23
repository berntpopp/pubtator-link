"""Entity relations API routes for PubTator3 data."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ...config import api_config
from ...models.requests import RelationsRequest
from ...models.responses import RelatedEntity, RelationsResponse
from .dependencies import (
    ClientDep,
    handle_api_errors,
    validate_entity_id,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/relations", tags=["Relations"])


@router.get(
    "/",
    response_model=RelationsResponse,
    summary="Find related entities",
    description="Find entities related to a specific biomedical entity through various relationship types.",
    operation_id="find_related_entities",
    responses={
        200: {
            "description": "Related entities found",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "primary_entity": "@CHEMICAL_remdesivir",
                        "related_entities": [
                            {
                                "entity_id": "@DISEASE_COVID-19",
                                "entity_name": "COVID-19",
                                "entity_type": "Disease",
                                "relation_type": "treat",
                                "confidence": 0.92,
                                "pmids": ["32275812", "32707141", "33378609"],
                            },
                            {
                                "entity_id": "@DISEASE_SARS-CoV-2",
                                "entity_name": "SARS-CoV-2 infection",
                                "entity_type": "Disease",
                                "relation_type": "treat",
                                "confidence": 0.89,
                                "pmids": ["32707141", "33378609"],
                            },
                        ],
                        "total_relations": 2,
                        "relation_filter": "treat",
                        "entity_filter": "Disease",
                    }
                }
            },
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_entity_id": {
                            "summary": "Invalid entity ID format",
                            "value": {
                                "detail": "Entity ID must start with '@' (e.g., @CHEMICAL_remdesivir)"
                            },
                        },
                        "invalid_relation_type": {
                            "summary": "Invalid relation type",
                            "value": {
                                "detail": "Invalid relation type 'invalid_type'. "
                                "Supported types: treat, cause, interact, ..."
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "No relations found",
            "content": {
                "application/json": {
                    "example": {"detail": "No related entities found for @CHEMICAL_nonexistent"}
                }
            },
        },
        422: {
            "description": "Validation error",
            "content": {
                "application/json": {"example": {"detail": "Entity ID parameter is required"}}
            },
        },
    },
)
@handle_api_errors
async def find_related_entities(
    client: ClientDep,
    e1: str = Query(
        description="Primary entity ID (must start with @)",
        min_length=1,
        examples=[
            {
                "summary": "Remdesivir relationships",
                "description": "Find entities related to remdesivir antiviral (PubTator3 example)",
                "value": "@CHEMICAL_remdesivir",
            },
            {
                "summary": "Doxorubicin cancer drug",
                "description": "Find entities related to doxorubicin chemotherapy (PubTator3 example)",
                "value": "@CHEMICAL_Doxorubicin",
            },
            {
                "summary": "BRCA1 tumor suppressor",
                "description": "Find diseases and pathways related to BRCA1 gene",
                "value": "@GENE_BRCA1",
            },
            {
                "summary": "COVID-19 pandemic",
                "description": "Find treatments and associated entities for COVID-19",
                "value": "@DISEASE_COVID-19",
            },
            {
                "summary": "TP53 guardian gene",
                "description": "Find cancer-related entities linked to p53 tumor suppressor",
                "value": "@GENE_TP53",
            },
            {
                "summary": "Alzheimer's disease",
                "description": "Find genes, drugs, and pathways related to Alzheimer's",
                "value": "@DISEASE_Alzheimer_Disease",
            },
            {
                "summary": "Metformin diabetes drug",
                "description": "Find conditions treated by metformin and drug interactions",
                "value": "@CHEMICAL_Metformin",
            },
        ],
    ),
    type: Optional[str] = Query(
        default=None,
        description="Filter by specific relation type",
        examples=[
            {
                "summary": "Treatment relations",
                "description": "Find entities that the primary entity treats",
                "value": "treat",
            },
            {
                "summary": "Causation relations",
                "description": "Find entities caused by the primary entity",
                "value": "cause",
            },
            {
                "summary": "Interaction relations",
                "description": "Find entities that interact with the primary entity",
                "value": "interact",
            },
            {
                "summary": "Association relations",
                "description": "Find entities associated with the primary entity",
                "value": "associate",
            },
        ],
    ),
    e2: Optional[str] = Query(
        default=None,
        description="Filter by target entity type",
        examples=[
            {
                "summary": "Disease targets",
                "description": "Only find related diseases",
                "value": "Disease",
            },
            {
                "summary": "Gene targets",
                "description": "Only find related genes",
                "value": "Gene",
            },
            {
                "summary": "Chemical targets",
                "description": "Only find related chemicals",
                "value": "Chemical",
            },
        ],
    ),
) -> RelationsResponse:
    """Find entities related to a specific biomedical entity.

    This endpoint discovers relationships between biomedical entities based on
    literature evidence in PubTator3. It can find various types of relationships
    such as treatment effects, causation, interactions, and associations.

    **Entity ID Format:**
    Entity IDs must start with '@' followed by the concept type and identifier:
    - @CHEMICAL_remdesivir (chemical compound remdesivir)
    - @GENE_BRCA1 (BRCA1 gene)
    - @DISEASE_COVID-19 (COVID-19 disease)
    - @SPECIES_9606 (Homo sapiens)

    **Supported Relation Types:**
    - **treat**: Entity A treats condition B (e.g., drug treats disease)
    - **cause**: Entity A causes condition B (e.g., mutation causes disease)
    - **interact**: Entity A interacts with entity B (e.g., drug-drug interaction)
    - **associate**: Entity A is associated with entity B (e.g., gene-disease association)
    - **cotreat**: Entity A is co-treated with entity B
    - **convert**: Entity A converts to entity B
    - **compare**: Entity A is compared to entity B
    - **positive_correlate**: Entity A positively correlates with entity B
    - **negative_correlate**: Entity A negatively correlates with entity B
    - **prevent**: Entity A prevents entity B
    - **inhibit**: Entity A inhibits entity B
    - **stimulate**: Entity A stimulates entity B
    - **drug_interact**: Drug interaction between entity A and entity B

    **Entity Type Filters:**
    When using the `e2` parameter, you can filter results to specific entity types:
    - Gene, Disease, Chemical, Species, Variant, CellLine

    **Usage Examples:**
    - Find diseases treated by remdesivir: e1="@CHEMICAL_remdesivir", type="treat", e2="Disease"
    - Find all interactions with BRCA1: e1="@GENE_BRCA1", type="interact"
    - Find any relationships with COVID-19: e1="@DISEASE_COVID-19"

    Args:
        e1: Primary entity ID (required, must start with @)
        type: Optional relation type filter
        e2: Optional target entity type filter
        client: Injected PubTator3 API client

    Returns:
        RelationsResponse with related entities and relationship information

    Raises:
        HTTPException(400): Invalid entity ID format or relation type
        HTTPException(404): No relations found
        HTTPException(422): Validation errors
        HTTPException(500): Internal server error
    """
    # Validate entity ID format
    validated_entity_id = validate_entity_id(e1)

    # Validate relation type if provided
    if type and type not in api_config.relation_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid relation type '{type}'. Supported types: {', '.join(api_config.relation_types)}",
        )

    # Validate target entity type if provided
    if e2 and e2 not in api_config.bioconcept_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity type '{e2}'. Supported types: {', '.join(api_config.bioconcept_types)}",
        )

    # Create request object
    request = RelationsRequest(e1=validated_entity_id, type=type, e2=e2)

    # Call PubTator3 API
    try:
        result = await client.find_relations(
            e1=request.e1, relation_type=request.type, e2=request.e2
        )

        # Parse API response and create RelatedEntity objects
        related_entities = []
        # API returns a list directly, not a dict with "results" key
        api_results = result if isinstance(result, list) else []

        for item in api_results:
            # Extract relationship information from PubTator3 response
            related_entity = RelatedEntity(
                entity_id=item.get("target", ""),
                entity_name=item.get("entity_name", ""),
                entity_type=item.get("entity_type", ""),
                relation_type=item.get("type", ""),
                confidence=item.get("confidence"),
                pmids=item.get("pmids", []),
                source=item.get("source", ""),
                target=item.get("target", ""),
                publications=item.get("publications"),
            )
            related_entities.append(related_entity)

        # Check if any relations were found
        if not related_entities:
            raise HTTPException(
                status_code=404,
                detail=f"No related entities found for {validated_entity_id}",
            )

        return RelationsResponse(
            success=True,
            primary_entity=validated_entity_id,
            related_entities=related_entities,
            total_relations=len(related_entities),
            relation_filter=type,
            entity_filter=e2,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ConnectionError as e:
        raise HTTPException(
            status_code=503, detail="PubTator3 service temporarily unavailable"
        ) from e
    except TimeoutError as e:
        raise HTTPException(
            status_code=504, detail="Request timeout while finding related entities"
        ) from e
