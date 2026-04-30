from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import get_review_context_service, get_review_queue
from pubtator_link.models.review_rerag import (
    ContextPack,
    PreparationStatus,
    RetrieveReviewContextResponse,
)
from pubtator_link.server_manager import UnifiedServerManager


@pytest.mark.asyncio
async def test_index_review_evidence_returns_queue_status() -> None:
    app = UnifiedServerManager().create_app()
    queue = AsyncMock()
    queue.enqueue_pmid.return_value = True
    queue.repository.preparation_status.return_value = PreparationStatus(queued=1)
    app.dependency_overrides[get_review_queue] = lambda: queue

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/evidence/index",
            json={"pmids": ["40234174"], "prepare_mode": "selected"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["review_id"] == "rev_123"
    assert data["queued"] == 1


@pytest.mark.asyncio
async def test_retrieve_review_context_returns_pack() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.retrieve_context.return_value = RetrieveReviewContextResponse(
        review_id="rev_123",
        context_pack=ContextPack(
            question="colchicine diagnosis",
            passages=[],
            citation_map={},
        ),
        preparation_status=PreparationStatus(complete=1),
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/context",
            json={"question": "colchicine diagnosis"},
        )

    assert response.status_code == 200
    assert response.json()["preparation_status"]["complete"] == 1
