"""Review index inventory and lifecycle orchestration."""

from __future__ import annotations

from pubtator_link.config import ReviewReragConfig
from pubtator_link.models.review_rerag import (
    CleanupExpiredReviewIndexesResponse,
    DeleteReviewIndexResponse,
    ListReviewIndexesResponse,
    ReviewIndexSummaryResponse,
)
from pubtator_link.repositories.review_rerag import ReviewReragRepository


class ReviewIndexLifecycleService:
    """Coordinate review index inventory and gated cleanup operations."""

    def __init__(self, repository: ReviewReragRepository, config: ReviewReragConfig) -> None:
        self.repository = repository
        self.config = config

    async def list_indexes(self, *, limit: int = 50, offset: int = 0) -> ListReviewIndexesResponse:
        indexes = await self.repository.list_review_indexes(
            limit=limit,
            offset=offset,
            ttl_seconds=self.config.index_ttl_seconds,
        )
        return ListReviewIndexesResponse(indexes=indexes)

    async def get_summary(self, review_id: str) -> ReviewIndexSummaryResponse:
        index = await self.repository.get_review_index_summary(
            review_id,
            ttl_seconds=self.config.index_ttl_seconds,
        )
        return ReviewIndexSummaryResponse(index=index)

    async def delete_index(self, review_id: str) -> DeleteReviewIndexResponse:
        if not self.config.enable_index_delete:
            raise PermissionError("Review index deletion is disabled")
        deleted = await self.repository.delete_review_index(review_id)
        return DeleteReviewIndexResponse(review_id=review_id, deleted=deleted)

    async def cleanup_expired(self) -> CleanupExpiredReviewIndexesResponse:
        if not self.config.enable_index_cleanup_endpoint:
            raise PermissionError("Review index cleanup endpoint is disabled")
        if self.config.index_ttl_seconds is None:
            return CleanupExpiredReviewIndexesResponse(deleted_review_ids=[])
        deleted = await self.repository.cleanup_expired_review_indexes(
            ttl_seconds=self.config.index_ttl_seconds,
        )
        return CleanupExpiredReviewIndexesResponse(deleted_review_ids=deleted)
