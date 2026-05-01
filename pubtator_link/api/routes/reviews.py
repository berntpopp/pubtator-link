"""Review-scoped evidence preparation and context retrieval routes."""

from fastapi import APIRouter

from ...models.review_rerag import (
    IndexReviewEvidenceRequest,
    IndexReviewEvidenceResponse,
    InspectReviewIndexRequest,
    InspectReviewIndexResponse,
    PreflightReviewSourcesRequest,
    PreflightReviewSourcesResponse,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    ReviewAuditBundle,
    ReviewNeighboringPassagesRequest,
    ReviewPassageLookupRequest,
    ReviewPassageLookupResponse,
)
from .dependencies import (
    ReviewAuditServiceDep,
    ReviewContextServiceDep,
    ReviewQueueDep,
    SourcePreflightServiceDep,
    handle_api_errors,
)

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


@router.post(
    "/source-preflight",
    response_model=PreflightReviewSourcesResponse,
    operation_id="preflight_review_sources",
    summary="Estimate review source coverage before indexing",
)
@handle_api_errors
async def preflight_review_sources(
    request: PreflightReviewSourcesRequest,
    service: SourcePreflightServiceDep,
) -> PreflightReviewSourcesResponse:
    hints = await service.preflight_pmids(request.pmids)
    return PreflightReviewSourcesResponse(coverage_hints=hints)


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


@router.get(
    "/{review_id}/index",
    response_model=InspectReviewIndexResponse,
    operation_id="inspect_review_index",
    summary="Inspect review-scoped index contents",
)
@handle_api_errors
async def inspect_review_index(
    review_id: str,
    service: ReviewContextServiceDep,
    pmids: str | None = None,
    include_passage_samples: bool = False,
    sample_per_pmid: int = 2,
) -> InspectReviewIndexResponse:
    pmid_list = [pmid.strip() for pmid in pmids.split(",") if pmid.strip()] if pmids else []
    return await service.inspect_review_index(
        review_id=review_id,
        request=InspectReviewIndexRequest(
            pmids=pmid_list,
            include_passage_samples=include_passage_samples,
            sample_per_pmid=sample_per_pmid,
        ),
    )


@router.get(
    "/{review_id}/audit-bundle",
    response_model=ReviewAuditBundle,
    operation_id="export_review_audit_bundle",
    summary="Export a PRISMA-style review audit bundle",
)
@handle_api_errors
async def export_review_audit_bundle(
    review_id: str,
    service: ReviewAuditServiceDep,
) -> ReviewAuditBundle:
    return await service.export_bundle(review_id)


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


@router.post(
    "/{review_id}/passages/by-id",
    response_model=ReviewPassageLookupResponse,
    operation_id="get_review_passages_by_id",
    summary="Get review passages by stable passage ID",
)
@handle_api_errors
async def get_review_passages_by_id(
    review_id: str,
    request: ReviewPassageLookupRequest,
    service: ReviewContextServiceDep,
) -> ReviewPassageLookupResponse:
    return await service.get_passages_by_id(
        review_id=review_id,
        passage_ids=request.passage_ids,
        max_chars_per_passage=request.max_chars_per_passage,
    )


@router.post(
    "/{review_id}/passages/neighbors",
    response_model=ReviewPassageLookupResponse,
    operation_id="get_neighboring_review_passages",
    summary="Get neighboring review passages around a stable passage ID",
)
@handle_api_errors
async def get_neighboring_review_passages(
    review_id: str,
    request: ReviewNeighboringPassagesRequest,
    service: ReviewContextServiceDep,
) -> ReviewPassageLookupResponse:
    return await service.get_neighboring_passages(
        review_id=review_id,
        passage_id=request.passage_id,
        before=request.before,
        after=request.after,
        same_section=request.same_section,
        max_chars_per_passage=request.max_chars_per_passage,
    )


@router.post(
    "/{review_id}/context/batch",
    response_model=RetrieveReviewContextBatchResponse,
    operation_id="retrieve_review_context_batch",
    summary="Retrieve compact review-scoped context for multiple query variants",
)
@handle_api_errors
async def retrieve_review_context_batch(
    review_id: str,
    request: RetrieveReviewContextBatchRequest,
    service: ReviewContextServiceDep,
) -> RetrieveReviewContextBatchResponse:
    return await service.retrieve_context_batch(review_id=review_id, request=request)
