from __future__ import annotations

from typing import Protocol

from pubtator_link.models.review_rerag import (
    RecordReviewContextRequest,
    RecordReviewContextResponse,
    ReviewLlmContext,
)


class LlmReviewContextRepository(Protocol):
    async def record_llm_context_event(
        self, review_id: str, request: RecordReviewContextRequest
    ) -> RecordReviewContextResponse:
        """Persist one LLM context snapshot and append-only context event."""

    async def get_latest_llm_context(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewLlmContext | None:
        """Return the latest compact LLM context snapshot for a review."""


class LlmReviewContextService:
    """Service for durable, text-free LLM review context."""

    def __init__(self, repository: LlmReviewContextRepository) -> None:
        self.repository = repository

    async def record_context(
        self, review_id: str, request: RecordReviewContextRequest
    ) -> RecordReviewContextResponse:
        if not review_id.strip():
            raise ValueError("review_id is required")
        has_event_detail = any(
            (
                request.summary,
                request.pmids,
                request.passage_ids,
                request.queries,
                request.decision,
            )
        )
        has_snapshot_detail = any(
            (
                request.topic,
                request.research_question,
                request.question_hash,
                request.request,
                request.response_summary,
                request.selected_pmids,
                request.rejected_pmids,
                request.preferred_entity_ids,
                request.active_queries,
                request.successful_queries,
                request.failed_queries,
                request.selected_passage_ids,
                request.audit_passage_ids,
                request.open_questions,
                request.user_decisions,
                request.last_next_commands,
                request.stable_citation_keys,
                request.cache_key,
            )
        )
        if not (has_event_detail or has_snapshot_detail):
            raise ValueError(
                "record_review_context requires summary, pmids, passage_ids, queries, "
                "decision, or durable context fields"
            )
        return await self.repository.record_llm_context_event(review_id, request)

    async def get_latest_context(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewLlmContext | None:
        if not review_id.strip():
            raise ValueError("review_id is required")
        return await self.repository.get_latest_llm_context(review_id, session_id=session_id)
