from __future__ import annotations

import pytest

from pubtator_link.models.review_rerag import (
    RecordReviewContextRequest,
    RecordReviewContextResponse,
    ReviewLlmContext,
    ReviewLlmContextEvent,
)
from pubtator_link.services.llm_review_context import LlmReviewContextService


class FakeLlmContextRepository:
    def __init__(self, latest: ReviewLlmContext | None = None) -> None:
        self.latest = latest
        self.recorded: list[tuple[str, RecordReviewContextRequest]] = []

    async def record_llm_context_event(
        self, review_id: str, request: RecordReviewContextRequest
    ) -> RecordReviewContextResponse:
        self.recorded.append((review_id, request))
        context = ReviewLlmContext(
            context_id="ctx-1",
            review_id=review_id,
            session_id=request.session_id,
            selected_passage_ids=request.selected_passage_ids,
            created_at="2026-05-03T00:00:00Z",
            updated_at="2026-05-03T00:00:00Z",
        )
        event = ReviewLlmContextEvent(
            event_id="event-1",
            context_id="ctx-1",
            review_id=review_id,
            session_id=request.session_id,
            event_type=request.event_type,
            summary=request.summary,
            passage_ids=request.passage_ids,
            created_at="2026-05-03T00:00:00Z",
        )
        return RecordReviewContextResponse(context=context, event=event)

    async def get_latest_llm_context(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewLlmContext | None:
        return self.latest


@pytest.mark.asyncio
async def test_record_context_rejects_empty_event() -> None:
    service = LlmReviewContextService(repository=FakeLlmContextRepository())

    with pytest.raises(
        ValueError,
        match="summary, pmids, passage_ids, queries, decision, or durable context fields",
    ):
        await service.record_context(
            "review-1",
            RecordReviewContextRequest(event_type="decision_recorded"),
        )


@pytest.mark.asyncio
async def test_record_context_delegates_nonempty_event_to_repository() -> None:
    repository = FakeLlmContextRepository()
    service = LlmReviewContextService(repository=repository)

    response = await service.record_context(
        "review-1",
        RecordReviewContextRequest(
            session_id="session-1",
            event_type="passage_selected",
            passage_ids=["p1"],
            selected_passage_ids=["p1"],
        ),
    )

    assert response.success is True
    assert response.context.review_id == "review-1"
    assert repository.recorded[0][0] == "review-1"
    assert repository.recorded[0][1].passage_ids == ["p1"]


@pytest.mark.asyncio
async def test_record_context_accepts_snapshot_only_context() -> None:
    repository = FakeLlmContextRepository()
    service = LlmReviewContextService(repository=repository)

    await service.record_context(
        "review-1",
        RecordReviewContextRequest(
            event_type="pmids_selected",
            selected_pmids=["123"],
        ),
    )

    assert repository.recorded[0][1].selected_pmids == ["123"]


@pytest.mark.asyncio
async def test_record_context_accepts_question_metadata_only_context() -> None:
    repository = FakeLlmContextRepository()
    service = LlmReviewContextService(repository=repository)

    await service.record_context(
        "review-1",
        RecordReviewContextRequest(
            event_type="context_summarized",
            question_hash="abc123",
        ),
    )

    assert repository.recorded[0][1].question_hash == "abc123"


@pytest.mark.asyncio
async def test_get_latest_context_returns_repository_snapshot() -> None:
    context = ReviewLlmContext(
        context_id="ctx-1",
        review_id="review-1",
        session_id="session-1",
        selected_passage_ids=["p1"],
        created_at="2026-05-03T00:00:00Z",
        updated_at="2026-05-03T00:00:00Z",
    )
    service = LlmReviewContextService(repository=FakeLlmContextRepository(latest=context))

    result = await service.get_latest_context("review-1", session_id="session-1")

    assert result == context
