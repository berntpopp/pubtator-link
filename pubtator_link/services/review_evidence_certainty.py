"""Evidence certainty storage service."""

from __future__ import annotations

from fastapi import HTTPException

from pubtator_link.models.review_rerag import (
    EvidenceCertaintyResponse,
    ListEvidenceCertaintyResponse,
    UpsertEvidenceCertaintyRequest,
)
from pubtator_link.repositories.review_rerag import ReviewReragRepository


class ReviewEvidenceCertaintyService:
    """Store and retrieve user-supplied certainty judgments."""

    def __init__(self, repository: ReviewReragRepository) -> None:
        self.repository = repository

    async def upsert(
        self,
        review_id: str,
        request: UpsertEvidenceCertaintyRequest,
        *,
        certainty_id: str | None = None,
    ) -> EvidenceCertaintyResponse:
        record = await self.repository.upsert_evidence_certainty(
            review_id,
            request,
            certainty_id=certainty_id,
        )
        return EvidenceCertaintyResponse(record=record)

    async def list(self, review_id: str) -> ListEvidenceCertaintyResponse:
        records = await self.repository.list_evidence_certainty(review_id)
        return ListEvidenceCertaintyResponse(records=records)

    async def get(self, review_id: str, certainty_id: str) -> EvidenceCertaintyResponse:
        record = await self.repository.get_evidence_certainty(review_id, certainty_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Evidence certainty record not found")
        return EvidenceCertaintyResponse(record=record)
