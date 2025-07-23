"""Publication export API routes for PubTator3 data."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ...config import api_config
from ...models.requests import PublicationExportRequest, PMCExportRequest
from ...models.responses import PublicationExportResponse
from .dependencies import (
    PublicationServiceDep,
    handle_api_errors,
    validate_pmids,
    validate_pmcids,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/publications", tags=["Publications"])


@router.get(
    "/export/{format}",
    response_model=PublicationExportResponse,
    summary="Export publication annotations",
    description="Export PubTator3 annotations for specified publications in the requested format.",
    operation_id="export_publication_annotations",
    responses={
        200: {
            "description": "Publication annotations exported successfully",
            "content": {
                "application/json": {
                    "example": {
                        "format": "biocjson",
                        "pmids": ["29355051", "32511357"],
                        "full_text": False,
                        "export_data": {
                            "documents": [
                                {
                                    "id": "29355051",
                                    "passages": [
                                        {
                                            "text": "BRCA1 mutations and breast cancer risk",
                                            "annotations": [
                                                {
                                                    "id": "@GENE_BRCA1",
                                                    "text": "BRCA1",
                                                    "locations": [
                                                        {"offset": 0, "length": 5}
                                                    ],
                                                    "infons": {
                                                        "type": "Gene",
                                                        "identifier": "672",
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ]
                        },
                        "count": 2,
                    }
                }
            },
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid format 'invalid'. Supported formats: pubtator, biocxml, biocjson"
                    }
                }
            },
        },
        404: {
            "description": "Publications not found",
            "content": {
                "application/json": {
                    "example": {"detail": "No publications found for PMIDs: 99999999"}
                }
            },
        },
        422: {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid PMID format: abc123. PMIDs must be numeric."
                    }
                }
            },
        },
    },
)
@handle_api_errors
async def export_publication_annotations(
    format: str,
    service: PublicationServiceDep,
    pmids: str = Query(
        description="Comma-separated list of PubMed IDs",
        examples={
            "single_pmid": {
                "summary": "Single PMID",
                "description": "Export annotations for one publication",
                "value": "29355051",
            },
            "multiple_pmids": {
                "summary": "Multiple PMIDs",
                "description": "Export annotations for multiple publications",
                "value": "29355051,32511357,34170578",
            },
        },
    ),
    full: bool = Query(
        default=False,
        description="Include full text content (only supported for biocxml and biocjson formats)",
    ),
) -> PublicationExportResponse:
    """Export publication annotations in the specified format.

    This endpoint exports PubTator3 annotations for the specified publications.
    It supports three output formats:

    - **pubtator**: Tab-delimited text format (title/abstract only)
    - **biocxml**: BioC XML format with rich annotations
    - **biocjson**: BioC JSON format with rich annotations

    When `full=true` is specified, full text content is included (only available
    for biocxml and biocjson formats). Note that full text is only available
    for publications that have been processed by PubTator3.

    Args:
        format: Output format (pubtator, biocxml, or biocjson)
        pmids: Comma-separated list of PubMed IDs
        full: Whether to include full text (biocxml/biocjson only)
        service: Injected publication service

    Returns:
        PublicationExportResponse with exported data

    Raises:
        HTTPException(400): Invalid format or parameters
        HTTPException(404): Publications not found
        HTTPException(422): Validation errors
        HTTPException(500): Internal server error
    """
    # Validate format
    if format not in api_config.export_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format '{format}'. Supported formats: {', '.join(api_config.export_formats)}",
        )

    # Validate full text parameter
    if full and format == "pubtator":
        raise HTTPException(
            status_code=400,
            detail="Full text is not supported for pubtator format. Use biocxml or biocjson instead.",
        )

    # Parse and validate PMIDs
    pmid_list = validate_pmids(pmids)

    # Create request object
    request = PublicationExportRequest(pmids=pmid_list, format=format, full=full)

    # Call service
    try:
        result = await service.export_publications_list(
            pmids=request.pmids, format=request.format, full=request.full
        )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No publications found for PMIDs: {', '.join(pmid_list)}",
        )


@router.get(
    "/pmc_export/{format}",
    response_model=PublicationExportResponse,
    summary="Export PMC publication annotations",
    description="Export PubTator3 annotations for PMC publications in the requested format.",
    operation_id="export_pmc_publications",
    responses={
        200: {
            "description": "PMC publication annotations exported successfully",
            "content": {
                "application/json": {
                    "example": {
                        "format": "biocjson",
                        "pmcids": ["PMC7696669", "PMC8869656"],
                        "full_text": True,
                        "export_data": {
                            "documents": [
                                {
                                    "id": "PMC7696669",
                                    "passages": [
                                        {
                                            "text": "COVID-19 treatment with remdesivir shows promise",
                                            "annotations": [
                                                {
                                                    "id": "@DISEASE_COVID-19",
                                                    "text": "COVID-19",
                                                    "locations": [
                                                        {"offset": 0, "length": 8}
                                                    ],
                                                    "infons": {
                                                        "type": "Disease",
                                                        "identifier": "COVID-19",
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ]
                        },
                        "count": 2,
                    }
                }
            },
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid format 'pubtator'. PMC export only supports biocxml and biocjson formats."
                    }
                }
            },
        },
        404: {
            "description": "PMC publications not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "No PMC publications found for PMCIDs: PMC99999999"
                    }
                }
            },
        },
        422: {
            "description": "Validation error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid PMCID format: 123456. PMCIDs must start with 'PMC' followed by digits."
                    }
                }
            },
        },
    },
)
@handle_api_errors
async def export_pmc_publications(
    format: str,
    service: PublicationServiceDep,
    pmcids: str = Query(
        description="Comma-separated list of PMC IDs",
        examples={
            "single_pmcid": {
                "summary": "Single PMCID",
                "description": "Export annotations for one PMC publication",
                "value": "PMC7696669",
            },
            "multiple_pmcids": {
                "summary": "Multiple PMCIDs",
                "description": "Export annotations for multiple PMC publications",
                "value": "PMC7696669,PMC8869656,PMC9123456",
            },
        },
    ),
) -> PublicationExportResponse:
    """Export PMC publication annotations in the specified format.

    This endpoint exports PubTator3 annotations for PMC (PubMed Central) publications.
    PMC publications typically contain full text content and richer annotations.

    **Supported formats for PMC export:**
    - **biocxml**: BioC XML format with full text and annotations
    - **biocjson**: BioC JSON format with full text and annotations

    Note: The pubtator format is not supported for PMC exports as it doesn't
    accommodate the rich structure of full-text PMC articles.

    Args:
        format: Output format (biocxml or biocjson only)
        pmcids: Comma-separated list of PMC IDs (format: PMC1234567)
        service: Injected publication service

    Returns:
        PublicationExportResponse with exported PMC data

    Raises:
        HTTPException(400): Invalid format or parameters
        HTTPException(404): PMC publications not found
        HTTPException(422): Validation errors
        HTTPException(500): Internal server error
    """
    # Validate format (PMC export only supports biocxml and biocjson)
    supported_pmc_formats = ["biocxml", "biocjson"]
    if format not in supported_pmc_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format '{format}'. PMC export only supports: {', '.join(supported_pmc_formats)}",
        )

    # Parse and validate PMCIDs
    pmcid_list = validate_pmcids(pmcids)

    # Create request object
    request = PMCExportRequest(pmcids=pmcid_list, format=format)

    # Call service
    try:
        result = await service.export_pmc_publications_list(
            pmcids=request.pmcids, format=request.format
        )

        # Convert PMCExportResponse to PublicationExportResponse
        return PublicationExportResponse(
            format=result.format,
            pmcids=pmcid_list,
            full_text=True,  # PMC publications always include full text
            export_data={"documents": [doc.model_dump() for doc in result.documents]},
            count=len(pmcid_list),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No PMC publications found for PMCIDs: {', '.join(pmcid_list)}",
        )
