"""Publication export API routes for PubTator3 data."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ...config import api_config
from ...models.publication_passages import (
    PublicationContextEstimateRequest,
    PublicationContextEstimateResponse,
    PublicationPassageRequest,
    PublicationPassageResponse,
)
from ...models.requests import PMCExportRequest, PublicationExportRequest
from ...models.responses import PublicationExportResponse
from .dependencies import (
    PublicationPassageServiceDep,
    PublicationServiceDep,
    handle_api_errors,
    validate_pmcids,
    validate_pmids,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/publications", tags=["Publications"])


@router.post(
    "/passages",
    response_model=PublicationPassageResponse,
    operation_id="get_publication_passages",
    summary="Get compact publication passages",
)
@handle_api_errors
async def get_publication_passages(
    request: PublicationPassageRequest,
    service: PublicationPassageServiceDep,
) -> PublicationPassageResponse:
    """Return compact sectioned publication passages without raw BioC."""
    return await service.get_passages(request)


@router.post(
    "/context-estimate",
    response_model=PublicationContextEstimateResponse,
    operation_id="estimate_publication_context",
    summary="Estimate compact publication context size",
)
@handle_api_errors
async def estimate_publication_context(
    request: PublicationContextEstimateRequest,
    service: PublicationPassageServiceDep,
) -> PublicationContextEstimateResponse:
    """Estimate compact passage count and character size before retrieval."""
    return await service.estimate_context(request)


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
                                                    "locations": [{"offset": 0, "length": 5}],
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
                    "example": {"detail": "Invalid PMID format: abc123. PMIDs must be numeric."}
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
        openapi_examples={
            "covid_research": {
                "summary": "COVID-19 research paper",
                "description": "Export annotations for remdesivir COVID-19 study (PubTator3 example)",
                "value": "32511357",
            },
            "brca1_genetics": {
                "summary": "BRCA1 genetics study",
                "description": "Export annotations for breast cancer genetics research (PubTator3 example)",
                "value": "29355051",
            },
            "multiple_cancer_studies": {
                "summary": "Multiple cancer studies",
                "description": "Export annotations for multiple cancer research papers",
                "value": "29355051,32511357,34170578",
            },
            "alzheimers_collection": {
                "summary": "Alzheimer's research collection",
                "description": "Export annotations for neurodegenerative disease studies",
                "value": "33858462,34567891,35123456",
            },
            "drug_discovery": {
                "summary": "Drug discovery pipeline",
                "description": "Export annotations for pharmaceutical research papers",
                "value": "31234567,32345678,33456789,34567890",
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
    request = PublicationExportRequest(
        pmids=pmid_list,
        format=format,  # type: ignore[arg-type]
        full=full,
    )

    # Call service
    try:
        result = await service.export_publications_list(
            pmids=request.pmids, format=request.format, full=request.full
        )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"No publications found for PMIDs: {', '.join(pmid_list)}",
        ) from e


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
                                                    "locations": [{"offset": 0, "length": 8}],
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
                    "example": {"detail": "No PMC publications found for PMCIDs: PMC99999999"}
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
        openapi_examples={
            "covid_treatment": {
                "summary": "COVID-19 treatment study",
                "description": "Export full-text annotations for COVID-19 research (PubTator3 example)",
                "value": "PMC7696669",
            },
            "biomedical_collection": {
                "summary": "Biomedical research collection",
                "description": "Export annotations for multiple PMC articles (PubTator3 example)",
                "value": "PMC7696669,PMC8869656",
            },
            "cancer_immunotherapy": {
                "summary": "Cancer immunotherapy studies",
                "description": "Export full-text annotations for cancer treatment research",
                "value": "PMC8123456,PMC8234567,PMC8345678",
            },
            "genomics_precision": {
                "summary": "Genomics and precision medicine",
                "description": "Export annotations for genomics research with full methodologies",
                "value": "PMC9001234,PMC9112345,PMC9223456",
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
    request = PMCExportRequest(
        pmcids=pmcid_list,
        format=format,  # type: ignore[arg-type]
    )

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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"No PMC publications found for PMCIDs: {', '.join(pmcid_list)}",
        ) from e
