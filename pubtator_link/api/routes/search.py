"""Publication search API routes for PubTator3 data."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ...models.requests import SearchRequest
from ...models.responses import SearchResponse, SearchResult
from .dependencies import (
    ClientDep,
    handle_api_errors,
    validate_page_number,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["Search"])


@router.get(
    "/",
    response_model=SearchResponse,
    summary="Search publications",
    description="Search biomedical literature using free text, entity IDs, or relation queries.",
    operation_id="search_publications",
    responses={
        200: {
            "description": "Search results",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "query": "breast cancer",
                        "results": [
                            {
                                "pmid": "29355051",
                                "title": "BRCA1 mutations in breast cancer susceptibility",
                                "abstract": "BRCA1 gene mutations significantly increase "
                                "the risk of developing breast and ovarian cancers...",
                                "authors": ["Smith J", "Johnson M", "Brown K"],
                                "journal": "Nature Medicine",
                                "pub_date": "2018-01-15",
                                "annotations": [
                                    {
                                        "type": "Gene",
                                        "text": "BRCA1",
                                        "identifier": "@GENE_672",
                                    }
                                ],
                                "score": 0.95,
                            }
                        ],
                        "total_results": 15847,
                        "page": 1,
                        "per_page": 20,
                        "total_pages": 793,
                    }
                }
            },
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid page number: 0. Page must be positive (starting from 1)"
                    }
                }
            },
        },
        422: {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Search query is required and must be at least 1 character long"
                    }
                }
            },
        },
    },
)
@handle_api_errors
async def search_publications(
    client: ClientDep,
    text: str = Query(
        description="Search query (free text, entity ID, or relation query)",
        min_length=1,
        max_length=1000,
        examples={
            "free_text": {
                "summary": "Free text search",
                "description": "Search using natural language",
                "value": "breast cancer treatment",
            },
            "entity_search": {
                "summary": "Entity ID search",
                "description": "Search using specific entity identifier",
                "value": "@CHEMICAL_remdesivir",
            },
            "boolean_search": {
                "summary": "Boolean search",
                "description": "Search using boolean operators",
                "value": "@CHEMICAL_Doxorubicin AND @DISEASE_Neoplasms",
            },
            "relation_search": {
                "summary": "Relation search",
                "description": "Search for entity relationships",
                "value": "relations:ANY|@CHEMICAL_Doxorubicin|@DISEASE_Neoplasms",
            },
            "relation_type_search": {
                "summary": "Specific relation search",
                "description": "Search for specific relationship types",
                "value": "relations:treat|@CHEMICAL_remdesivir|Disease",
            },
        },
    ),
    page: int = Query(
        default=1,
        description="Page number for pagination",
        ge=1,
        le=1000,
        examples={
            "first_page": {
                "summary": "First page",
                "description": "Get the first page of results",
                "value": 1,
            },
            "specific_page": {
                "summary": "Specific page",
                "description": "Get a specific page of results",
                "value": 5,
            },
        },
    ),
) -> SearchResponse:
    """Search biomedical literature using flexible query types.

    This endpoint provides comprehensive search capabilities across PubTator3's
    annotated literature database. It supports multiple query types for different
    use cases and research needs.

    **Query Types Supported:**

    1. **Free Text Search**: Natural language queries
       - Example: "breast cancer treatment"
       - Example: "COVID-19 vaccine efficacy"

    2. **Entity ID Search**: Search using specific biomedical entity identifiers
       - Example: "@CHEMICAL_remdesivir" (find papers about remdesivir)
       - Example: "@GENE_BRCA1" (find papers about BRCA1 gene)

    3. **Boolean Search**: Combine entities with AND/OR operators
       - Example: "@CHEMICAL_Doxorubicin AND @DISEASE_Neoplasms"
       - Example: "@GENE_BRCA1 OR @GENE_BRCA2"

    4. **Relation Search**: Find papers with specific entity relationships
       - Format: "relations:TYPE|ENTITY1|ENTITY2"
       - Example: "relations:treat|@CHEMICAL_Doxorubicin|@DISEASE_Neoplasms"
       - Example: "relations:ANY|@CHEMICAL_remdesivir|Disease"

    **Supported Relation Types:**
    - treat, cause, cotreat, convert, compare, interact, associate
    - positive_correlate, negative_correlate, prevent, inhibit, stimulate, drug_interact
    - Use "ANY" to find any relationship type

    **Pagination:**
    - Results are paginated with 20 results per page by default
    - Use the `page` parameter to navigate through results
    - Maximum page number is 1000 to ensure reasonable response times

    Args:
        text: Search query in any supported format
        page: Page number for pagination (1-based)
        client: Injected PubTator3 API client

    Returns:
        SearchResponse with matching publications

    Raises:
        HTTPException(400): Invalid page number or query format
        HTTPException(422): Validation errors
        HTTPException(500): Internal server error
    """
    # Validate page number
    validated_page = validate_page_number(page)

    # Create request object
    request = SearchRequest(text=text.strip(), page=validated_page)

    # Call PubTator3 API
    try:
        result = await client.search_publications(text=request.text, page=request.page)

        # Parse API response and create SearchResult objects
        search_results = []
        api_results = result.get("results", [])

        for item in api_results:
            # Extract publication information from PubTator3 response
            search_result = SearchResult(
                pmid=item.get("pmid", ""),
                title=item.get("title", ""),
                abstract=item.get("abstract"),
                authors=item.get("authors", []),
                journal=item.get("journal"),
                pub_date=item.get("pub_date"),
                annotations=item.get("annotations", []),
                score=item.get("score"),
            )
            search_results.append(search_result)

        # Extract pagination information
        total_results = result.get("total", 0)
        per_page = result.get("per_page", 20)
        total_pages = (total_results + per_page - 1) // per_page  # Ceiling division

        return SearchResponse(
            success=True,
            query=request.text,
            results=search_results,
            total_results=total_results,
            page=validated_page,
            per_page=per_page,
            total_pages=total_pages,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError:
        raise HTTPException(
            status_code=503, detail="PubTator3 service temporarily unavailable"
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504, detail="Request timeout while searching publications"
        )
