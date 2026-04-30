from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import get_review_context_service, get_review_queue
from pubtator_link.models.review_rerag import (
    ContextPack,
    InspectReviewIndexResponse,
    PreparationStatus,
    QueryDiagnosticsSummary,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
    ReviewIndexTotals,
    ReviewSourceSummary,
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


@pytest.mark.asyncio
async def test_inspect_review_index_returns_sources_and_failures() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.inspect_review_index.return_value = InspectReviewIndexResponse(
        review_id="rev_123",
        preparation_status=PreparationStatus(complete=1, failed=1),
        sources=[
            ReviewSourceSummary(
                source_id="111",
                pmid="111",
                source_kind="pubtator_abstract",
                job_status="complete",
                sections=["abstract"],
                passage_count=1,
                char_count=13,
            )
        ],
        totals=ReviewIndexTotals(
            pmid_count=1,
            source_count=1,
            passage_count=1,
            char_count=13,
            failed_source_count=1,
        ),
        failed_sources=[],
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/reviews/rev_123/index",
            params={"include_passage_samples": "true", "sample_per_pmid": "1"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["review_id"] == "rev_123"
    assert data["totals"]["passage_count"] == 1
    service.inspect_review_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_returns_merged_context() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.retrieve_context_batch.return_value = RetrieveReviewContextBatchResponse(
        review_id="rev_123",
        results=[
            RetrieveReviewContextResponse(
                review_id="rev_123",
                context_pack=ContextPack(
                    question="colchicine children",
                    passages=[],
                    citation_map={},
                ),
                preparation_status=PreparationStatus(complete=1),
            )
        ],
        merged_context_pack=ContextPack(
            question="colchicine children\nFMF phenotype",
            passages=[],
            citation_map={},
        ),
        preparation_status=PreparationStatus(complete=1),
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/context/batch",
            json={"queries": ["colchicine children", "FMF phenotype"]},
        )

    assert response.status_code == 200
    assert response.json()["review_id"] == "rev_123"
    assert "merged_context_pack" in response.json()


@pytest.mark.asyncio
async def test_retrieve_review_context_batch_accepts_response_mode() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.retrieve_context_batch.return_value = RetrieveReviewContextBatchResponse(
        review_id="rev_123",
        response_mode="diagnostics",
        results=[],
        query_summaries=[
            QueryDiagnosticsSummary(
                query="MEFV",
                query_tokens=["mefv"],
                candidate_count=0,
                selected_count=0,
                returned_count=0,
                dropped_count=0,
                zero_result_reason="no_candidate_matches",
                suggested_queries=["colchicine"],
            )
        ],
        merged_context_pack=ContextPack(
            question="MEFV",
            passages=[],
            citation_map={},
        ),
        preparation_status=PreparationStatus(complete=1),
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/context/batch",
            json={"queries": ["MEFV"], "response_mode": "diagnostics"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["response_mode"] == "diagnostics"
    assert data["results"] == []
    assert data["query_summaries"][0]["zero_result_reason"] == "no_candidate_matches"
