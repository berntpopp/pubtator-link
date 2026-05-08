"""Review-scoped evidence preparation and context retrieval routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ...models.review_rerag import (
    CleanupExpiredReviewIndexesResponse,
    DeleteReviewIndexResponse,
    EvidenceCertaintyResponse,
    IndexReviewEvidenceRequest,
    IndexReviewEvidenceResponse,
    InspectReviewIndexRequest,
    InspectReviewIndexResponse,
    ListEvidenceCertaintyResponse,
    ListResearchSessionsResponse,
    ListReviewIndexesResponse,
    PreflightReviewSourcesRequest,
    PreflightReviewSourcesResponse,
    ResearchSessionStatusResponse,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    ReviewAuditBundle,
    ReviewIndexSummaryResponse,
    ReviewNeighboringPassagesRequest,
    ReviewPassageLookupRequest,
    ReviewPassageLookupResponse,
    SampleSectionPolicy,
    StageResearchSessionRequest,
    StageResearchSessionResponse,
    UpsertEvidenceCertaintyRequest,
)
from ...services.review_indexing import ReviewIndexingService
from .dependencies import (
    ResearchSessionServiceDep,
    ReviewAuditServiceDep,
    ReviewContextServiceDep,
    ReviewEvidenceCertaintyServiceDep,
    ReviewIndexLifecycleServiceDep,
    ReviewQueueDep,
    SourcePreflightServiceDep,
    handle_api_errors,
)

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


@router.get(
    "",
    response_model=ListReviewIndexesResponse,
    operation_id="list_review_indexes",
    summary="List persisted review indexes",
)
@handle_api_errors
async def list_review_indexes(
    service: ReviewIndexLifecycleServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ListReviewIndexesResponse:
    return await service.list_indexes(limit=limit, offset=offset)


@router.get(
    "/{review_id}/summary",
    response_model=ReviewIndexSummaryResponse,
    operation_id="get_review_index_summary",
    summary="Get one review index inventory summary",
)
@handle_api_errors
async def get_review_index_summary(
    review_id: str,
    service: ReviewIndexLifecycleServiceDep,
) -> ReviewIndexSummaryResponse:
    return await service.get_summary(review_id)


@router.delete(
    "/{review_id}",
    response_model=DeleteReviewIndexResponse,
    operation_id="delete_review_index",
    summary="Delete one review index when enabled for private deployments",
)
@handle_api_errors
async def delete_review_index(
    review_id: str,
    service: ReviewIndexLifecycleServiceDep,
) -> DeleteReviewIndexResponse:
    try:
        return await service.delete_index(review_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/cleanup-expired",
    response_model=CleanupExpiredReviewIndexesResponse,
    operation_id="cleanup_expired_review_indexes",
    summary="Cleanup expired review indexes when enabled for private deployments",
)
@handle_api_errors
async def cleanup_expired_review_indexes(
    service: ReviewIndexLifecycleServiceDep,
) -> CleanupExpiredReviewIndexesResponse:
    try:
        return await service.cleanup_expired()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/{review_id}/certainty",
    response_model=EvidenceCertaintyResponse,
    operation_id="add_evidence_certainty",
    summary="Store a user-supplied evidence certainty judgment",
)
@handle_api_errors
async def add_evidence_certainty(
    review_id: str,
    request: UpsertEvidenceCertaintyRequest,
    service: ReviewEvidenceCertaintyServiceDep,
) -> EvidenceCertaintyResponse:
    return await service.upsert(review_id, request)


@router.get(
    "/{review_id}/certainty",
    response_model=ListEvidenceCertaintyResponse,
    operation_id="list_evidence_certainty",
    summary="List user-supplied evidence certainty judgments",
)
@handle_api_errors
async def list_evidence_certainty(
    review_id: str,
    service: ReviewEvidenceCertaintyServiceDep,
) -> ListEvidenceCertaintyResponse:
    return await service.list(review_id)


@router.get(
    "/{review_id}/certainty/{certainty_id}",
    response_model=EvidenceCertaintyResponse,
    operation_id="get_evidence_certainty",
    summary="Get one user-supplied evidence certainty judgment",
)
@handle_api_errors
async def get_evidence_certainty(
    review_id: str,
    certainty_id: str,
    service: ReviewEvidenceCertaintyServiceDep,
) -> EvidenceCertaintyResponse:
    return await service.get(review_id, certainty_id)


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
    "/{review_id}/sessions/stage",
    response_model=StageResearchSessionResponse,
    operation_id="stage_research_session",
    summary="Stage a transparent research session",
)
@handle_api_errors
async def stage_research_session(
    review_id: str,
    request: StageResearchSessionRequest,
    service: ResearchSessionServiceDep,
) -> StageResearchSessionResponse:
    return await service.stage(review_id=review_id, request=request)


@router.get(
    "/{review_id}/sessions/{session_id}",
    response_model=ResearchSessionStatusResponse,
    operation_id="get_research_session_status",
    summary="Get staged research session status",
)
@handle_api_errors
async def get_research_session_status(
    review_id: str,
    session_id: str,
    service: ResearchSessionServiceDep,
) -> ResearchSessionStatusResponse:
    try:
        return await service.get_status(review_id=review_id, session_id=session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{review_id}/sessions",
    response_model=ListResearchSessionsResponse,
    operation_id="list_research_sessions",
    summary="List staged research sessions",
)
@handle_api_errors
async def list_research_sessions(
    review_id: str,
    service: ResearchSessionServiceDep,
) -> ListResearchSessionsResponse:
    return await service.list_sessions(review_id=review_id)


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
    service = ReviewIndexingService(repository=queue.repository, queue=queue)
    return await service.index_review_evidence(review_id, request)


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
    session_id: str | None = None,
    include_passage_samples: bool = False,
    sample_per_pmid: int = Query(default=2, ge=0, le=10),
    min_sample_chars: int = Query(default=80, ge=0, le=1000),
    sample_section_policy: SampleSectionPolicy = "evidence_first",
    include_metadata: bool = False,
    metadata: Literal["basic", "full"] = "basic",
    response_mode: Literal["compact", "full"] = "full",
    limit: int | None = Query(default=None, ge=1, le=100),
    cursor: str | None = None,
) -> InspectReviewIndexResponse:
    pmid_list = [pmid.strip() for pmid in pmids.split(",") if pmid.strip()] if pmids else []
    return await service.inspect_review_index(
        review_id=review_id,
        request=InspectReviewIndexRequest(
            session_id=session_id,
            pmids=pmid_list,
            response_mode=response_mode,
            include_passage_samples=include_passage_samples,
            sample_per_pmid=sample_per_pmid,
            min_sample_chars=min_sample_chars,
            sample_section_policy=sample_section_policy,
            include_metadata=include_metadata,
            metadata=metadata,
            limit=limit,
            cursor=cursor,
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
    session_id: str | None = None,
) -> ReviewAuditBundle:
    return await service.export_bundle(review_id, session_id=session_id)


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
        session_id=request.session_id,
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
        session_id=request.session_id,
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
