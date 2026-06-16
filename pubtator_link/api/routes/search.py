"""Publication search API routes for PubTator3 data."""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ...models.requests import SearchRequest, SearchSection, SearchSortOrder
from ...models.responses import SearchResponse
from ...services.publication_metadata import lookup_metadata_batched
from ...services.search_coverage import SearchCoverageMode, attach_preflight_coverage
from ...services.search_shaping import (
    IncludeCitations,
    SearchMetadataMode,
    SearchResponseMode,
    TextHighlightFormat,
    combined_search_text,
    selected_search_items,
    shaped_search_response,
)
from ..search_filters import apply_year_window, build_search_filter_plan
from .dependencies import (
    ClientDep,
    PublicationMetadataServiceDep,
    SourcePreflightServiceDep,
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
    source_preflight_service: SourcePreflightServiceDep,
    publication_metadata_service: PublicationMetadataServiceDep,
    text: str = Query(
        description="Search query (free text, entity ID, or relation query)",
        min_length=1,
        max_length=1000,
        openapi_examples={
            "covid_research": {
                "summary": "COVID-19 research",
                "description": "Free text search for coronavirus research",
                "value": "COVID-19 vaccine efficacy",
            },
            "remdesivir_studies": {
                "summary": "Remdesivir studies",
                "description": "Search for remdesivir antiviral research (PubTator3 example)",
                "value": "@CHEMICAL_remdesivir",
            },
            "cancer_drug_combination": {
                "summary": "Cancer drug combination",
                "description": "Boolean search for doxorubicin in cancer treatment",
                "value": "@CHEMICAL_Doxorubicin AND @DISEASE_Neoplasms",
            },
            "brca_genetics": {
                "summary": "BRCA1/BRCA2 genetics",
                "description": "Hereditary breast cancer gene research",
                "value": "(@GENE_BRCA1 OR @GENE_BRCA2) AND breast cancer",
            },
            "drug_disease_relations": {
                "summary": "Drug-disease relationships",
                "description": "Find any relationship between doxorubicin and neoplasms",
                "value": "relations:ANY|@CHEMICAL_Doxorubicin|@DISEASE_Neoplasms",
            },
            "treatment_relations": {
                "summary": "Treatment relationships",
                "description": "Find drugs that treat diseases (specific relation type)",
                "value": "relations:treat|@CHEMICAL_remdesivir|Disease",
            },
            "alzheimers_research": {
                "summary": "Alzheimer's disease research",
                "description": "Neurodegenerative disease and amyloid research",
                "value": "@DISEASE_Alzheimer_Disease AND amyloid plaques",
            },
            "diabetes_mechanisms": {
                "summary": "Diabetes drug mechanisms",
                "description": "Metformin mechanism of action research",
                "value": "@CHEMICAL_Metformin AND glucose metabolism",
            },
        },
    ),
    page: int = Query(
        default=1,
        description="Page number for pagination",
        ge=1,
        le=1000,
        openapi_examples={
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
    sort: Annotated[
        SearchSortOrder | None,
        Query(
            description="Sort order for search results (default: score desc)",
            openapi_examples={
                "by_relevance": {
                    "summary": "By relevance",
                    "description": "Sort by relevance score (highest first)",
                    "value": "score desc",
                },
                "by_date_newest": {
                    "summary": "By date (newest)",
                    "description": "Sort by publication date (newest first)",
                    "value": "date desc",
                },
                "by_date_oldest": {
                    "summary": "By date (oldest)",
                    "description": "Sort by publication date (oldest first)",
                    "value": "date asc",
                },
                "by_relevance_lowest": {
                    "summary": "By relevance (lowest)",
                    "description": "Sort by relevance score (lowest first)",
                    "value": "score asc",
                },
            },
        ),
    ] = None,
    filters: Annotated[
        str | None,
        Query(
            description="Advanced search filters as JSON string (type, journal, author, year)",
            openapi_examples={
                "recent_reviews": {
                    "summary": "Recent reviews only",
                    "description": "Filter for review articles published recently",
                    "value": '{"type":["Review"],"year":{"min":2020}}',
                },
                "high_impact_journals": {
                    "summary": "High-impact journals",
                    "description": "Research from top-tier biomedical journals",
                    "value": '{"journal":["Nature","Science","Cell","NEJM"]}',
                },
                "clinical_trials": {
                    "summary": "Clinical trials filter",
                    "description": "Randomized controlled trials and clinical studies",
                    "value": '{"type":["Randomized Controlled Trial","Clinical Trial"]}',
                },
                "seizure_reviews": {
                    "summary": "Seizure journal reviews",
                    "description": "Review articles in Seizure journal (PubTator3 example)",
                    "value": '{"type":["Review"],"journal":["Seizure"]}',
                },
                "covid_era_research": {
                    "summary": "COVID-19 era research",
                    "description": "Publications from the pandemic period with specific authors",
                    "value": '{"year":{"min":2020,"max":2023},"author":["Fauci A","Collins F"]}',
                },
                "cancer_research": {
                    "summary": "Cancer research focus",
                    "description": "Recent cancer research in oncology journals",
                    "value": (
                        '{"type":["Journal Article","Research Article"],'
                        '"journal":["Cancer Research","Oncogene"],"year":{"min":2021}}'
                    ),
                },
            },
        ),
    ] = None,
    publication_types: Annotated[
        list[str] | None,
        Query(description="Publication type filters merged into filters.type"),
    ] = None,
    year_min: Annotated[
        int | None,
        Query(
            description="Minimum publication year merged into filters.year.min",
            ge=1800,
            le=2030,
        ),
    ] = None,
    year_max: Annotated[
        int | None,
        Query(
            description="Maximum publication year merged into filters.year.max",
            ge=1800,
            le=2030,
        ),
    ] = None,
    sections: Annotated[
        str | None,
        Query(
            description="Comma-separated list of document sections to search within",
            openapi_examples={
                "title_abstract": {
                    "summary": "Title and abstract focus",
                    "description": "Search only in titles and abstracts (PubTator3 example)",
                    "value": "title,abstract",
                },
                "methods_only": {
                    "summary": "Methods section targeting",
                    "description": "Find methodology mentions (PubTator3 example)",
                    "value": "methods",
                },
                "results_discussion": {
                    "summary": "Results and discussion",
                    "description": "Focus on research findings and interpretation",
                    "value": "results,discussion",
                },
                "comprehensive_search": {
                    "summary": "Comprehensive search",
                    "description": "Search across core paper sections",
                    "value": "title,abstract,introduction,methods,results,discussion,conclusion",
                },
                "intro_background": {
                    "summary": "Introduction and background",
                    "description": "Focus on literature review and rationale sections",
                    "value": "introduction,background",
                },
                "figures_tables": {
                    "summary": "Figure and table content",
                    "description": "Search within figure captions and table descriptions",
                    "value": "figure_captions,table_captions",
                },
            },
        ),
    ] = None,
    response_mode: Annotated[
        SearchResponseMode,
        Query(description="Response verbosity: compact, standard, or full"),
    ] = "standard",
    include_citations: Annotated[
        IncludeCitations,
        Query(description="Citation formats to include"),
    ] = "both",
    text_hl_format: Annotated[
        TextHighlightFormat,
        Query(description="Highlight format: none, plain, or annotated"),
    ] = "annotated",
    limit: Annotated[
        int | None,
        Query(ge=1, le=50, description="Trim results returned from the current page"),
    ] = None,
    entity_ids: Annotated[
        list[str] | None,
        Query(description="Canonical PubTator entity IDs combined with the text query"),
    ] = None,
    guideline_boost: Annotated[
        bool,
        Query(description="Rerank current page to prioritize guideline/consensus records"),
    ] = False,
    coverage: Annotated[
        SearchCoverageMode,
        Query(description="Coverage hints to attach to search hits: none or preflight"),
    ] = "none",
    metadata: Annotated[
        SearchMetadataMode,
        Query(description=("Publication metadata enrichment: none, basic, with_abstract, or full")),
    ] = "none",
) -> SearchResponse:
    """Search biomedical literature with advanced filtering and section targeting.

    This endpoint provides comprehensive search capabilities across PubTator3's
    annotated literature database with advanced filtering options and section-specific
    searching for precise research targeting.

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

    **Advanced Filtering:**

    The `filters` parameter accepts a JSON string with the following options:
    - `type`: Filter by publication types (e.g., ["Review", "Research Article"])
    - `journal`: Filter by specific journal names (e.g., ["Nature", "Science"])
    - `author`: Filter by author names (e.g., ["Smith J", "Johnson M"])
    - `year`: Filter by publication year range (e.g., {"min": 2020, "max": 2023})

    **Section Targeting:**

    The `sections` parameter allows limiting search to specific document sections:
    - Available sections: title, abstract, methods, results, discussion, conclusion,
      introduction, background, fulltext
    - Multiple sections can be specified as comma-separated values
    - Example: "title,abstract" focuses search on titles and abstracts only

    **Example Advanced Search:**
    ```
    GET /api/search/?text=epilepsy&filters={"type":["Review"],"journal":["Seizure"]}&sections=title,methods
    ```
    This searches for "epilepsy" in review articles from the Seizure journal,
    limiting the search to title and methods sections only.

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

    try:
        filter_plan = build_search_filter_plan(
            filters=filters,
            publication_types=publication_types,
            year_min=year_min,
            year_max=year_max,
            ignore_malformed_filters=False,
        )
        merged_filters = filter_plan.server_filters
    except ValueError as e:
        detail = str(e)
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if detail.startswith("Invalid filters JSON")
            or detail == "filters must be a JSON object"
            else 422
        )
        raise HTTPException(status_code=status_code, detail=detail) from e

    # Parse sections if provided
    parsed_sections = None
    if sections:
        section_list = [s.strip() for s in sections.split(",") if s.strip()]
        try:
            parsed_sections = [SearchSection(s) for s in section_list]
        except ValueError as e:
            valid_sections = [s.value for s in SearchSection]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid section: {e!s}. Valid sections: {', '.join(valid_sections)}",
            ) from e

    # Create request object
    request = SearchRequest(
        text=combined_search_text(text, entity_ids),
        page=validated_page,
        sort=sort,
        filters=None,
        sections=parsed_sections,
    )

    # Call PubTator3 API
    try:
        result = await client.search_publications(
            text=request.text,
            page=request.page,
            sort=request.sort.value if request.sort else None,
            filters=merged_filters,
            sections=(",".join([s.value for s in request.sections]) if request.sections else None),
        )

        if filter_plan.has_local_year_window:
            # PubTator3 only filters by an exact year server-side; apply the
            # requested year range locally over this page (best-effort).
            trimmed = apply_year_window(
                list(result.get("results", [])),
                filter_plan.local_year_min,
                filter_plan.local_year_max,
            )
            result = {**result, "results": trimmed, "count": len(trimmed), "total_pages": 1}

        raw_items = selected_search_items(
            list(result.get("results", [])),
            guideline_boost=guideline_boost,
            limit=limit,
        )

        metadata_by_pmid = {}
        if metadata != "none":
            pmids = [str(item.get("pmid", "")) for item in raw_items]
            pmids = [pmid for pmid in dict.fromkeys(pmids) if pmid]
            if pmids:
                include_metadata_citations: IncludeCitations = (
                    "both"
                    if metadata == "full" and include_citations == "none"
                    else include_citations
                )
                metadata_response = await lookup_metadata_batched(
                    publication_metadata_service,
                    pmids,
                    include_mesh=metadata == "full",
                    include_publication_types=True,
                    include_citations=include_metadata_citations if metadata == "full" else "none",
                    include_coverage=False,
                )
                metadata_by_pmid = {
                    item.pmid: item.model_dump() for item in metadata_response.metadata
                }

        response = shaped_search_response(
            raw=result,
            query=request.text,
            page=validated_page,
            sort=request.sort.value if request.sort else None,
            filters=merged_filters,
            sections=[section.value for section in request.sections] if request.sections else None,
            response_mode=response_mode,
            include_citations=include_citations,
            text_hl_format=text_hl_format,
            limit=limit,
            guideline_boost=guideline_boost,
            metadata=metadata,
            metadata_by_pmid=metadata_by_pmid,
        )
        if coverage == "preflight":
            await attach_preflight_coverage(response, source_preflight_service)
        return response

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ConnectionError as e:
        raise HTTPException(
            status_code=503, detail="PubTator3 service temporarily unavailable"
        ) from e
    except TimeoutError as e:
        raise HTTPException(
            status_code=504, detail="Request timeout while searching publications"
        ) from e
