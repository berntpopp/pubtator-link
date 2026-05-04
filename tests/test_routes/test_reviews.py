from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import (
    get_research_session_service,
    get_review_audit_service,
    get_review_context_service,
    get_review_evidence_certainty_service,
    get_review_index_lifecycle_service,
    get_review_queue,
    get_source_preflight_service,
)
from pubtator_link.models.review_rerag import (
    ContextPack,
    EvidenceCertaintyRecord,
    EvidenceCertaintyResponse,
    InspectReviewIndexResponse,
    ListEvidenceCertaintyResponse,
    ListResearchSessionsResponse,
    ListReviewIndexesResponse,
    PreparationStatus,
    QueryDiagnosticsSummary,
    ResearchSessionManifest,
    ResearchSessionStatusResponse,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
    ReviewAuditBundle,
    ReviewIndexInventoryItem,
    ReviewIndexSummaryResponse,
    ReviewIndexTotals,
    ReviewPassageLookupResponse,
    ReviewSourceSummary,
    SourceCoverageHint,
    StageResearchSessionResponse,
)
from pubtator_link.server_manager import UnifiedServerManager


def test_stage_research_session_route_is_registered(app) -> None:
    route_paths = {route.path for route in app.routes}
    assert "/api/reviews/{review_id}/sessions/stage" in route_paths
    assert "/api/reviews/{review_id}/sessions/{session_id}" in route_paths
    assert "/api/reviews/{review_id}/sessions" in route_paths


@pytest.mark.asyncio
async def test_stage_research_session_route_calls_service_and_serializes_meta() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    manifest = ResearchSessionManifest(
        review_id="review-1",
        session_id="session-1",
        query="FMF",
        preparation_status=PreparationStatus(queued=1),
    )
    service.stage.return_value = StageResearchSessionResponse(
        manifest=manifest,
        _meta={"next_commands": ["pubtator.get_research_session_status"]},
    )
    app.dependency_overrides[get_research_session_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/review-1/sessions/stage",
            json={"query": "FMF", "max_candidates": 1},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["manifest"]["session_id"] == "session-1"
    assert data["manifest"]["preparation_status"]["queued"] == 1
    assert data["_meta"]["next_commands"] == ["pubtator.get_research_session_status"]
    service.stage.assert_awaited_once()
    call_kwargs = service.stage.await_args.kwargs
    assert call_kwargs["review_id"] == "review-1"
    assert call_kwargs["request"].query == "FMF"
    assert call_kwargs["request"].max_candidates == 1


@pytest.mark.asyncio
async def test_get_research_session_status_route_calls_service() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_status.return_value = ResearchSessionStatusResponse(
        manifest=ResearchSessionManifest(
            review_id="review-1",
            session_id="session-1",
            query="FMF",
            preparation_status=PreparationStatus(complete=1),
        )
    )
    app.dependency_overrides[get_research_session_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/sessions/session-1")

    assert response.status_code == 200
    data = response.json()
    assert data["manifest"]["session_id"] == "session-1"
    assert data["manifest"]["preparation_status"]["complete"] == 1
    service.get_status.assert_awaited_once_with(
        review_id="review-1",
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_list_research_sessions_route_calls_service() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.list_sessions.return_value = ListResearchSessionsResponse(
        sessions=[
            ResearchSessionManifest(
                review_id="review-1",
                session_id="session-1",
                query="FMF",
                preparation_status=PreparationStatus(running=1),
            )
        ]
    )
    app.dependency_overrides[get_research_session_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/sessions")

    assert response.status_code == 200
    data = response.json()
    assert data["sessions"][0]["session_id"] == "session-1"
    assert data["sessions"][0]["preparation_status"]["running"] == 1
    service.list_sessions.assert_awaited_once_with(review_id="review-1")


@pytest.mark.asyncio
async def test_get_research_session_status_route_maps_lookup_error_to_404() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_status.side_effect = LookupError("Research session not found: missing")
    app.dependency_overrides[get_research_session_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/sessions/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Research session not found: missing"
    service.get_status.assert_awaited_once_with(
        review_id="review-1",
        session_id="missing",
    )


@pytest.mark.asyncio
async def test_preflight_review_sources_returns_coverage_hints() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.preflight_pmids.return_value = [
        SourceCoverageHint(
            pmid="40234174",
            expected_coverage="abstract_only",
            coverage_reason="no_pmcid",
        )
    ]
    app.dependency_overrides[get_source_preflight_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/source-preflight",
            json={"pmids": ["40234174"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["coverage_hints"][0]["pmid"] == "40234174"
    assert data["coverage_hints"][0]["coverage_reason"] == "no_pmcid"
    service.preflight_pmids.assert_awaited_once_with(["40234174"])


@pytest.mark.asyncio
async def test_list_review_indexes_route_returns_inventory() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.list_indexes.return_value = ListReviewIndexesResponse(
        indexes=[
            ReviewIndexInventoryItem(
                review_id="review-1",
                created_at="2026-05-01T00:00:00Z",
                updated_at="2026-05-01T01:00:00Z",
                preparation_status=PreparationStatus(complete=1),
                passage_count=2,
            )
        ]
    )
    app.dependency_overrides[get_review_index_lifecycle_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews", params={"limit": "10", "offset": "5"})

    assert response.status_code == 200
    assert response.json()["indexes"][0]["review_id"] == "review-1"
    service.list_indexes.assert_awaited_once_with(limit=10, offset=5)


@pytest.mark.asyncio
async def test_get_review_index_summary_route_returns_inventory_item() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_summary.return_value = ReviewIndexSummaryResponse(
        index=ReviewIndexInventoryItem(
            review_id="review-1",
            created_at="2026-05-01T00:00:00Z",
            updated_at="2026-05-01T01:00:00Z",
            preparation_status=PreparationStatus(complete=1),
        )
    )
    app.dependency_overrides[get_review_index_lifecycle_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/summary")

    assert response.status_code == 200
    assert response.json()["index"]["review_id"] == "review-1"
    service.get_summary.assert_awaited_once_with("review-1")


@pytest.mark.asyncio
async def test_review_index_destructive_routes_are_disabled_by_default() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.delete_index.side_effect = PermissionError("Review index deletion is disabled")
    service.cleanup_expired.side_effect = PermissionError(
        "Review index cleanup endpoint is disabled"
    )
    app.dependency_overrides[get_review_index_lifecycle_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        delete_response = await client.delete("/api/reviews/review-1")
        cleanup_response = await client.post("/api/reviews/cleanup-expired")

    assert delete_response.status_code == 403
    assert cleanup_response.status_code == 403


@pytest.mark.asyncio
async def test_evidence_certainty_routes_store_and_return_records() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    record = EvidenceCertaintyRecord(
        certainty_id="00000000-0000-0000-0000-000000000001",
        review_id="review-1",
        outcome="Mortality",
        overall_certainty="low",
        created_at="2026-05-01T00:00:00Z",
        updated_at="2026-05-01T00:00:00Z",
    )
    service.upsert.return_value = EvidenceCertaintyResponse(record=record)
    service.list.return_value = ListEvidenceCertaintyResponse(records=[record])
    service.get.return_value = EvidenceCertaintyResponse(record=record)
    app.dependency_overrides[get_review_evidence_certainty_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post_response = await client.post(
            "/api/reviews/review-1/certainty",
            json={"outcome": "Mortality", "overall_certainty": "low"},
        )
        list_response = await client.get("/api/reviews/review-1/certainty")
        get_response = await client.get(
            "/api/reviews/review-1/certainty/00000000-0000-0000-0000-000000000001"
        )

    assert post_response.status_code == 200
    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert post_response.json()["record"]["overall_certainty"] == "low"
    assert list_response.json()["records"][0]["certainty_id"] == record.certainty_id
    assert get_response.json()["record"]["outcome"] == "Mortality"


@pytest.mark.asyncio
async def test_index_review_evidence_returns_queue_status() -> None:
    app = UnifiedServerManager().create_app()
    queue = AsyncMock()
    queue.enqueue_pmid.return_value = "newly_queued"
    queue.repository.preparation_job_statuses.return_value = {}
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
    assert data["retry_after_ms"] == 3000
    assert data["index_snapshot_date"] is not None


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
        index_snapshot_date="2026-05-02",
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/context",
            json={"question": "colchicine diagnosis"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["preparation_status"]["complete"] == 1
    assert data["index_snapshot_date"] == "2026-05-02"


@pytest.mark.asyncio
async def test_get_review_passages_by_id_route_returns_passages_and_not_found() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_passages_by_id.return_value = ReviewPassageLookupResponse(
        review_id="rev_123",
        passages=[],
        not_found=["missing"],
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/passages/by-id",
            json={"passage_ids": ["missing"]},
        )

    assert response.status_code == 200
    assert response.json()["not_found"] == ["missing"]
    service.get_passages_by_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_neighboring_review_passages_route_returns_passages_and_not_found() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_neighboring_passages.return_value = ReviewPassageLookupResponse(
        review_id="rev_123",
        passages=[],
        not_found=["missing"],
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/passages/neighbors",
            json={"passage_id": "missing", "before": 1, "after": 1},
        )

    assert response.status_code == 200
    assert response.json()["not_found"] == ["missing"]
    service.get_neighboring_passages.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_review_audit_bundle_route_returns_audit_bundle() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.export_bundle.return_value = ReviewAuditBundle(
        review_id="rev_123",
        generated_at="2026-05-01T10:00:00+00:00",
        preparation_status=PreparationStatus(complete=1),
        totals=ReviewIndexTotals(),
        sources=[],
        failed_sources=[],
        coverage_distribution={},
        resolver_attempts=[],
        passage_ids=[],
        stable_citation_keys={},
        index_snapshot_date="2026-05-02",
    )
    app.dependency_overrides[get_review_audit_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/rev_123/audit-bundle")

    assert response.status_code == 200
    data = response.json()
    assert data["review_id"] == "rev_123"
    assert data["index_snapshot_date"] == "2026-05-02"
    service.export_bundle.assert_awaited_once_with("rev_123", session_id=None)


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
                coverage_reason="abstract_fallback_used",
                pmcid="PMC123",
                doi="10.1000/example",
                license_or_access_hint="oa",
                pmc_fallback_available=True,
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
        index_snapshot_date="2026-05-02",
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/reviews/rev_123/index",
            params={
                "include_passage_samples": "true",
                "sample_per_pmid": "1",
                "include_metadata": "true",
                "metadata": "full",
                "response_mode": "compact",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["review_id"] == "rev_123"
    assert data["totals"]["passage_count"] == 1
    assert data["sources"][0]["coverage_reason"] == "abstract_fallback_used"
    assert data["sources"][0]["pmcid"] == "PMC123"
    assert data["sources"][0]["doi"] == "10.1000/example"
    assert data["sources"][0]["pmc_fallback_available"] is True
    assert data["sources"][0]["resolver_attempts"] == []
    assert data["index_snapshot_date"] == "2026-05-02"
    service.inspect_review_index.assert_awaited_once()
    request = service.inspect_review_index.await_args.kwargs["request"]
    assert request.include_metadata is True
    assert request.metadata == "full"
    assert request.response_mode == "compact"


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
        index_snapshot_date="2026-05-02",
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/context/batch",
            json={"queries": ["colchicine children", "FMF phenotype"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["review_id"] == "rev_123"
    assert "merged_context_pack" in data
    assert data["index_snapshot_date"] == "2026-05-02"


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
    assert "results" not in data
    assert data["query_summaries"][0]["zero_result_reason"] == "no_candidate_matches"
