"""Entity autocomplete API routes for PubTator3 data."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ...config import api_config
from ...models.requests import EntityAutocompleteRequest
from ...models.responses import EntityAutocompleteResponse, EntityMatch
from .dependencies import (
    ClientDep,
    handle_api_errors,
    validate_limit,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/entities", tags=["Entities"])


@router.get(
    "/autocomplete",
    response_model=EntityAutocompleteResponse,
    summary="Find entity IDs through autocomplete",
    description="Search for biomedical entity identifiers using free text queries with optional concept filtering.",
    operation_id="search_entity_ids",
    responses={
        200: {
            "description": "Entity autocomplete results",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "query": "breast cancer",
                        "matches": [
                            {
                                "identifier": "@DISEASE_MESH:D001943",
                                "name": "Breast Neoplasms",
                                "type": "Disease",
                                "score": 0.95,
                                "synonyms": [
                                    "breast cancer",
                                    "mammary cancer",
                                    "breast carcinoma",
                                ],
                            },
                            {
                                "identifier": "@DISEASE_OMIM:114480",
                                "name": "Breast Cancer",
                                "type": "Disease",
                                "score": 0.92,
                                "synonyms": [
                                    "hereditary breast cancer",
                                    "familial breast cancer",
                                ],
                            },
                        ],
                        "total_matches": 2,
                        "concept_filter": "Disease",
                    }
                }
            },
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid bioconcept 'InvalidType'. "
                        "Supported types: Gene, Disease, Chemical, Species, Variant, CellLine"
                    }
                }
            },
        },
        422: {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Query string is required and must be at least 1 character long"
                    }
                }
            },
        },
    },
)
@handle_api_errors
async def search_entity_ids(
    client: ClientDep,
    query: str = Query(
        description="Free text search query for biomedical entities",
        min_length=1,
        max_length=500,
        examples={
            "disease_query": {
                "summary": "Disease search",
                "description": "Search for disease entities",
                "value": "breast cancer",
            },
            "gene_query": {
                "summary": "Gene search",
                "description": "Search for gene entities",
                "value": "BRCA1",
            },
            "chemical_query": {
                "summary": "Chemical search",
                "description": "Search for chemical entities",
                "value": "aspirin",
            },
            "complex_query": {
                "summary": "Complex term",
                "description": "Search for complex biomedical terms",
                "value": "tumor suppressor protein p53",
            },
        },
    ),
    concept: Optional[str] = Query(
        default=None,
        description="Filter results by bioconcept type",
        examples={
            "gene": {
                "summary": "Gene filter",
                "description": "Only return gene entities",
                "value": "Gene",
            },
            "disease": {
                "summary": "Disease filter",
                "description": "Only return disease entities",
                "value": "Disease",
            },
            "chemical": {
                "summary": "Chemical filter",
                "description": "Only return chemical entities",
                "value": "Chemical",
            },
        },
    ),
    limit: int = Query(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=100,
        examples={
            "default": {
                "summary": "Default limit",
                "description": "Return up to 10 results",
                "value": 10,
            },
            "more_results": {
                "summary": "More results",
                "description": "Return up to 25 results",
                "value": 25,
            },
        },
    ),
) -> EntityAutocompleteResponse:
    """Find biomedical entity identifiers through autocomplete search.

    This endpoint searches PubTator3's entity database to find standard identifiers
    for biomedical concepts using free text queries. It supports fuzzy matching
    and synonym recognition to help find the correct entity identifiers.

    **Supported bioconcept types:**
    - **Gene**: Human genes and gene products (NCBI Gene, UniProt)
    - **Disease**: Diseases and medical conditions (MeSH, OMIM, Disease Ontology)
    - **Chemical**: Drugs, compounds, and chemicals (MeSH, ChEBI, PubChem)
    - **Species**: Organisms and taxonomic groups (NCBI Taxonomy)
    - **Variant**: Genetic variants and mutations (dbSNP, ClinVar)
    - **CellLine**: Cell lines used in research (Cellosaurus)

    **Usage examples:**
    - Find gene identifiers: query="BRCA1", concept="Gene"
    - Find disease identifiers: query="breast cancer", concept="Disease"
    - Find chemical identifiers: query="aspirin", concept="Chemical"
    - Broad search: query="p53" (returns genes, diseases, chemicals, etc.)

    Args:
        query: Free text search query for biomedical entities
        concept: Optional bioconcept type filter
        limit: Maximum number of results (1-100, default 10)
        client: Injected PubTator3 API client

    Returns:
        EntityAutocompleteResponse with matching entities

    Raises:
        HTTPException(400): Invalid bioconcept type
        HTTPException(422): Validation errors
        HTTPException(500): Internal server error
    """
    # Validate concept type if provided
    if concept and concept not in api_config.bioconcept_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bioconcept '{concept}'. Supported types: {', '.join(api_config.bioconcept_types)}",
        )

    # Validate limit
    validated_limit = validate_limit(limit, max_limit=100)

    # Create request object
    request = EntityAutocompleteRequest(query=query.strip(), concept=concept, limit=validated_limit)

    # Call PubTator3 API
    try:
        result = await client.autocomplete_entity(
            query=request.query, concept=request.concept, limit=request.limit
        )

        # Parse API response and create EntityMatch objects
        matches = []
        # API returns a list directly, not a dict with "results" key
        api_results = result if isinstance(result, list) else []

        for item in api_results:
            # Extract entity information from PubTator3 response
            entity_match = EntityMatch(
                identifier=item.get("_id", ""),
                name=item.get("name", ""),
                type=item.get("biotype", concept or "Unknown"),
                score=item.get("score"),
                synonyms=item.get("synonyms", []),
                db_id=item.get("db_id"),
                db=item.get("db"),
                match=item.get("match"),
            )
            matches.append(entity_match)

        return EntityAutocompleteResponse(
            success=True,
            query=request.query,
            matches=matches,
            total_matches=len(matches),
            concept_filter=concept,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ConnectionError as e:
        raise HTTPException(
            status_code=503, detail="PubTator3 service temporarily unavailable"
        ) from e
    except TimeoutError as e:
        raise HTTPException(
            status_code=504, detail="Request timeout while searching entities"
        ) from e
