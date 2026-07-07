"""Text annotation API routes for PubTator3 text processing."""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...config import text_processing_config
from ...models.responses import (
    AnnotationEntity,
    TextAnnotationResultResponse,
    TextAnnotationSubmitResponse,
)
from .dependencies import (
    ClientDep,
    handle_api_errors,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/annotations", tags=["Text Processing"])


class TextAnnotationSubmitRequestBody(BaseModel):
    """Request body for text annotation submission."""

    text: str
    bioconcept: str = "Gene"


@router.post(
    "/submit",
    response_model=TextAnnotationSubmitResponse,
    summary="Submit text for NER processing",
    description="Submit text to PubTator3 for named entity recognition and annotation.",
    operation_id="submit_text_annotation",
    responses={
        200: {
            "description": "Text submitted for processing",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "session_id": "ABC123DEF456",
                        "status": "submitted",
                        "estimated_time": 30,
                        "message": "Text submitted for processing. Use session_id to retrieve results.",
                    }
                }
            },
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_bioconcept": {
                            "summary": "Invalid bioconcept type",
                            "value": {
                                "detail": "Invalid bioconcept 'InvalidType'. "
                                "Supported types: Gene, Disease, Chemical, Species, Variant, CellLine"
                            },
                        },
                        "text_too_long": {
                            "summary": "Text too long",
                            "value": {
                                "detail": "Text too long. Maximum length is 10,000 characters."
                            },
                        },
                    }
                }
            },
        },
        413: {
            "description": "Text payload too large",
            "content": {
                "application/json": {
                    "example": {"detail": "Text payload exceeds maximum allowed size"}
                }
            },
        },
        422: {
            "description": "Validation error",
            "content": {
                "application/json": {"example": {"detail": "Text is required and cannot be empty"}}
            },
        },
    },
)
@handle_api_errors
async def submit_text_annotation(
    client: ClientDep,
    text: str = Query(
        ...,
        description="Text to annotate with biomedical entities",
        examples=[
            {
                "summary": "BRCA1 gene mutation text (PubTator3 example)",
                "description": "Text about BRCA1 gene mutations for gene entity extraction",
                "value": "The ESR1 Mutations: From Bedside to Bench to Bedside.",
            },
            {
                "summary": "COVID-19 clinical text",
                "description": "Clinical text about COVID-19 for disease entity extraction",
                "value": (
                    "Patients with COVID-19 and diabetes mellitus require careful "
                    "monitoring of blood glucose levels."
                ),
            },
            {
                "summary": "Drug interaction text",
                "description": "Pharmacological text for chemical entity extraction",
                "value": "Aspirin and warfarin interaction increases bleeding risk in elderly patients.",
            },
            {
                "summary": "Cancer research abstract",
                "description": "Research abstract with multiple entity types",
                "value": (
                    "TP53 mutations in breast cancer patients treated with doxorubicin "
                    "showed resistance to chemotherapy."
                ),
            },
            {
                "summary": "Alzheimer's disease research",
                "description": "Neuroscience research text with disease and gene entities",
                "value": (
                    "APOE4 genotype is associated with increased risk of Alzheimer's "
                    "disease and accelerated cognitive decline."
                ),
            },
            {
                "summary": "Pharmacogenomics study",
                "description": "Personalized medicine text with genes, drugs, and diseases",
                "value": "CYP2D6 polymorphisms affect metabolism of codeine and tramadol in chronic pain management.",
            },
        ],
    ),
    bioconcepts: str = Query(
        default="Gene",
        description="Bioconcept type to extract from text",
        examples=[
            {
                "summary": "Gene entities",
                "description": "Extract gene names and symbols",
                "value": "Gene",
            },
            {
                "summary": "Disease entities",
                "description": "Extract disease and condition names",
                "value": "Disease",
            },
            {
                "summary": "Chemical entities",
                "description": "Extract drug and chemical compound names",
                "value": "Chemical",
            },
            {
                "summary": "All entity types",
                "description": "Extract all supported biomedical entities",
                "value": "all",
            },
        ],
    ),
) -> TextAnnotationSubmitResponse:
    """Submit text for biomedical named entity recognition.

    This endpoint submits text to PubTator3's text processing service for
    named entity recognition (NER). The service can identify and annotate
    various types of biomedical entities within the provided text.

    **Supported Bioconcept Types:**
    - **Gene**: Gene names, symbols, and identifiers
    - **Disease**: Disease names, conditions, and disorders
    - **Chemical**: Drugs, compounds, and chemical substances
    - **Species**: Organism names and taxonomic identifiers
    - **Variant**: Genetic variants and mutations
    - **CellLine**: Cell line names and identifiers

    **Processing Flow:**
    1. Submit text with chosen bioconcept type
    2. Receive session_id for tracking
    3. Use session_id with GET /annotations/{session_id} to retrieve results
    4. Results include entity positions, identifiers, and confidence scores

    **Text Requirements:**
    - Minimum length: 1 character
    - Maximum length: 10,000 characters
    - Plain text format (HTML/XML tags will be treated as text)
    - Unicode text is supported

    **Processing Time:**
    - Small texts (< 1000 chars): Usually 5-15 seconds
    - Medium texts (1000-5000 chars): Usually 15-45 seconds
    - Large texts (5000-10000 chars): Usually 30-90 seconds

    **Usage Examples:**
    ```json
    {
        "text": "BRCA1 mutations increase breast cancer risk",
        "bioconcept": "Gene"
    }
    ```

    ```json
    {
        "text": "Aspirin treatment reduces cardiovascular disease",
        "bioconcept": "Chemical"
    }
    ```

    Args:
        request_body: Text and bioconcept type for processing
        client: Injected PubTator3 API client

    Returns:
        TextAnnotationSubmitResponse with session_id for result retrieval

    Raises:
        HTTPException(400): Invalid bioconcept type or text format
        HTTPException(413): Text payload too large
        HTTPException(422): Validation errors
        HTTPException(500): Internal server error
    """
    # Parse bioconcepts parameter
    if bioconcepts.lower() == "all":
        bioconcept_list = list(text_processing_config.supported_bioconcepts)
    else:
        bioconcept_list = [bc.strip() for bc in bioconcepts.split(",") if bc.strip()]

    # Validate bioconcept types
    invalid_bioconcepts = [
        bc for bc in bioconcept_list if bc not in text_processing_config.supported_bioconcepts
    ]
    if invalid_bioconcepts:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bioconcept(s): {', '.join(invalid_bioconcepts)}. "
            f"Supported types: {', '.join(text_processing_config.supported_bioconcepts)}",
        )

    # Validate text length
    if len(text) > 10000:
        raise HTTPException(
            status_code=413,
            detail="Text payload exceeds maximum allowed size (10,000 characters)",
        )

    if not text.strip():
        raise HTTPException(status_code=422, detail="Text is required and cannot be empty")

    # Submit to PubTator3 text processing service
    # Note: PubTator3 API processes one bioconcept at a time, so we use the first one
    # The response will indicate all requested bioconcepts for client tracking
    primary_bioconcept = bioconcept_list[0]

    try:
        session_id = await client.submit_text_annotation(
            text=text.strip(), bioconcept=primary_bioconcept
        )

        # Estimate processing time based on text length
        text_length = len(text)
        if text_length < 1000:
            estimated_time = 15
        elif text_length < 5000:
            estimated_time = 45
        else:
            estimated_time = 90

        return TextAnnotationSubmitResponse(
            success=True,
            session_id=session_id,
            status="submitted",
            bioconcepts=bioconcept_list,
            estimated_time=estimated_time,
            message="Text submitted for processing. Use session_id to retrieve results.",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ConnectionError as e:
        raise HTTPException(
            status_code=503, detail="Text processing service temporarily unavailable"
        ) from e
    except TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail="Request timeout while submitting text for processing",
        ) from e


@router.get(
    "/results/{session_id}",
    response_model=TextAnnotationResultResponse,
    summary="Retrieve annotation results",
    description="Retrieve the results of text annotation processing using the session ID.",
    operation_id="get_annotation_results",
    responses={
        200: {
            "description": "Annotation results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "session_id": "ABC123DEF456",
                        "status": "completed",
                        "original_text": "BRCA1 mutations increase breast cancer risk",
                        "bioconcept": "Gene",
                        "annotations": [
                            {
                                "start": 0,
                                "end": 5,
                                "text": "BRCA1",
                                "entity_id": "@GENE_672",
                                "entity_type": "Gene",
                                "confidence": 0.95,
                            }
                        ],
                        "processing_time": 12.5,
                    }
                }
            },
        },
        202: {
            "description": "Processing still in progress",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "session_id": "ABC123DEF456",
                        "status": "processing",
                        "original_text": "BRCA1 mutations increase breast cancer risk",
                        "bioconcept": "Gene",
                        "annotations": [],
                        "message": "Processing in progress. Please try again in a few moments.",
                    }
                }
            },
        },
        404: {
            "description": "Session not found or expired",
            "content": {
                "application/json": {
                    "example": {"detail": "Session ABC123DEF456 not found or has expired"}
                }
            },
        },
        422: {
            "description": "Invalid session ID format",
            "content": {"application/json": {"example": {"detail": "Invalid session ID format"}}},
        },
    },
)
@handle_api_errors
async def get_annotation_results(
    session_id: str,
    client: ClientDep,
) -> TextAnnotationResultResponse:
    """Retrieve biomedical text annotation results.

    This endpoint retrieves the results of text processing submitted via the
    POST /annotations/submit endpoint. The processing is asynchronous, so you
    may need to poll this endpoint until processing is complete.

    **Processing Status Values:**
    - **submitted**: Request received, processing not yet started
    - **processing**: NER processing in progress
    - **completed**: Processing finished, results available
    - **failed**: Processing failed due to an error
    - **expired**: Session has expired (results no longer available)

    **Session Management:**
    - Sessions are valid for 24 hours after submission
    - Results are cached and can be retrieved multiple times
    - Session IDs are unique and cannot be guessed

    **Polling Recommendations:**
    - Check status immediately after submission
    - If status is "processing", wait 5-10 seconds before next check
    - For large texts, wait 15-30 seconds between polls
    - Maximum recommended polling time: 5 minutes

    **Annotation Format:**
    Each annotation includes:
    - **start/end**: Character positions in the original text
    - **text**: The exact text that was annotated
    - **entity_id**: PubTator3 entity identifier (e.g., @GENE_672)
    - **entity_type**: Type of entity (Gene, Disease, Chemical, etc.)
    - **confidence**: Annotation confidence score (0.0-1.0)

    **Error Handling:**
    - 202: Still processing (not an error, continue polling)
    - 404: Session not found or expired
    - 500: Processing failed (check logs for details)

    Args:
        session_id: Session ID from the submit endpoint
        client: Injected PubTator3 API client

    Returns:
        TextAnnotationResultResponse with processing status and results

    Raises:
        HTTPException(202): Processing still in progress
        HTTPException(404): Session not found or expired
        HTTPException(422): Invalid session ID format
        HTTPException(500): Processing failed
    """
    # Validate session ID format (basic validation)
    if not session_id or len(session_id) < 8:
        raise HTTPException(status_code=422, detail="Invalid session ID format")

    # Retrieve results from PubTator3 text processing service
    try:
        result = await client.retrieve_text_annotation(session_id=session_id)

        # Parse the response based on processing status
        status = result.get("status", "unknown")

        if status == "processing" or status == "submitted":
            # Still processing - return 202 with current status
            response = TextAnnotationResultResponse(
                success=True,
                session_id=session_id,
                status=status,
                original_text=result.get("original_text", ""),
                bioconcept=result.get("bioconcept", ""),
                annotations=[],
                processing_time=None,
                message="Processing in progress. Please try again in a few moments.",
            )
            # Set HTTP status code to 202 for "still processing"
            raise HTTPException(status_code=202, detail=response.model_dump())

        elif status == "completed":
            # Processing completed - parse annotations
            annotations = []
            for annotation_data in result.get("annotations", []):
                annotation = AnnotationEntity(
                    start=annotation_data.get("start", 0),
                    end=annotation_data.get("end", 0),
                    text=annotation_data.get("text", ""),
                    entity_id=annotation_data.get("entity_id", ""),
                    entity_type=annotation_data.get("entity_type", ""),
                    confidence=annotation_data.get("confidence"),
                )
                annotations.append(annotation)

            return TextAnnotationResultResponse(
                success=True,
                session_id=session_id,
                status=status,
                original_text=result.get("original_text", ""),
                bioconcept=result.get("bioconcept", ""),
                annotations=annotations,
                processing_time=result.get("processing_time"),
            )

        elif status == "failed":
            # Processing failed
            raise HTTPException(
                status_code=500,
                detail=f"Text processing failed: {result.get('error', 'Unknown error')}",
            )

        elif status == "expired":
            # Session expired
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} has expired. Results are no longer available.",
            )

        else:
            # Unknown status
            raise HTTPException(status_code=500, detail=f"Unknown processing status: {status}")

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ConnectionError as e:
        raise HTTPException(
            status_code=503, detail="Text processing service temporarily unavailable"
        ) from e
    except TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail="Request timeout while retrieving annotation results",
        ) from e
    except Exception as e:
        # Session not found or other error. Log only the sanitized type; the
        # raw exception string can carry free-text or identifiers.
        logger.error("Error retrieving annotation results", extra={"error_type": type(e).__name__})
        raise HTTPException(
            status_code=404, detail=f"Session {session_id} not found or has expired"
        ) from e
