"""Review-scoped evidence preparation and context retrieval routes."""

from fastapi import APIRouter

from ...models.review_rerag import (
    IndexReviewEvidenceRequest,
    IndexReviewEvidenceResponse,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
)
from .dependencies import ReviewContextServiceDep, ReviewQueueDep, handle_api_errors

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


@router.post(
    "/{review_id}/evidence/index",
    response_model=IndexReviewEvidenceResponse,
    operation_id="index_review_evidence",
    summary="Queue review-scoped evidence preparation",
)
@handle_api_errors
async def index_review_evidence(
    review_id: str,
    request: IndexReviewEvidenceRequest,
    queue: ReviewQueueDep,
) -> IndexReviewEvidenceResponse:
    queued = 0
    already_prepared = 0
    for pmid in request.pmids:
        if await queue.enqueue_pmid(review_id, pmid):
            queued += 1
        else:
            already_prepared += 1
    for url in request.curated_urls:
        if await queue.enqueue_curated_url(review_id, url):
            queued += 1
        else:
            already_prepared += 1
    status = await queue.repository.preparation_status(review_id)
    return IndexReviewEvidenceResponse(
        review_id=review_id,
        queued=queued,
        already_prepared=already_prepared,
        preparation_status=status,
    )


@router.post(
    "/{review_id}/context",
    response_model=RetrieveReviewContextResponse,
    operation_id="retrieve_review_context",
    summary="Retrieve a compact review-scoped context pack",
)
@handle_api_errors
async def retrieve_review_context(
    review_id: str,
    request: RetrieveReviewContextRequest,
    service: ReviewContextServiceDep,
) -> RetrieveReviewContextResponse:
    return await service.retrieve_context(review_id=review_id, request=request)
