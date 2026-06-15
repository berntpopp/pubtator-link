from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes import dependencies
from pubtator_link.api.routes.dependencies import (
    cleanup_dependencies,
    get_corpus_suggestion_service,
    get_discovery_service,
)
from pubtator_link.models.corpus_suggestion import CorpusSuggestionResponse
from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdConversionResponse,
    CitationLookupRecord,
    CitationLookupResponse,
    MeshDescriptor,
    MeshLookupResponse,
    RelatedArticleRecord,
    RelatedArticlesResponse,
)
from pubtator_link.server_manager import UnifiedServerManager


@pytest.mark.asyncio
async def test_convert_article_ids_route_returns_candidates() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.convert_article_ids.return_value = ArticleIdConversionResponse(
        records=[
            ArticleIdConversionRecord(
                input_id="PMC123",
                input_kind="pmcid",
                status="resolved",
                pmid="123",
                pmcid="PMC123",
            )
        ],
        candidate_pmids=["123"],
        unresolved=[],
    )
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/discovery/convert-article-ids",
            json={"ids": ["PMC123"], "source": "auto"},
        )

    assert response.status_code == 200
    assert response.json()["candidate_pmids"] == ["123"]
    service.convert_article_ids.assert_awaited_once_with(ids=["PMC123"], source="auto")


@pytest.mark.asyncio
async def test_convert_article_ids_route_rejects_target_filtering() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.convert_article_ids.return_value = ArticleIdConversionResponse(records=[])
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/discovery/convert-article-ids",
            json={"ids": ["PMC123"], "source": "auto", "target": ["pmid"]},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "target filtering is not supported yet"
    service.convert_article_ids.assert_not_called()


@pytest.mark.asyncio
async def test_discovery_route_maps_request_errors_to_503() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    request = httpx.Request("GET", "https://eutils.ncbi.nlm.nih.gov/")
    service.lookup_mesh.side_effect = httpx.RequestError("network failed", request=request)
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/discovery/mesh", params={"query": "FMF"})

    assert response.status_code == 503
    service.lookup_mesh.assert_awaited_once_with(query="FMF", limit=10, exact=False)


@pytest.mark.asyncio
async def test_discovery_route_maps_upstream_status_errors_to_502() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    request = httpx.Request("GET", "https://eutils.ncbi.nlm.nih.gov/")
    upstream_response = httpx.Response(429, request=request)
    service.lookup_mesh.side_effect = httpx.HTTPStatusError(
        "upstream throttled",
        request=request,
        response=upstream_response,
    )
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/discovery/mesh", params={"query": "FMF"})

    assert response.status_code == 502
    service.lookup_mesh.assert_awaited_once_with(query="FMF", limit=10, exact=False)


@pytest.mark.asyncio
async def test_mesh_route_returns_descriptors() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.lookup_mesh.return_value = MeshLookupResponse(
        query="FMF",
        descriptors=[
            MeshDescriptor(
                ui="D005505",
                name="Familial Mediterranean Fever",
            )
        ],
    )
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/discovery/mesh", params={"query": "FMF", "limit": 5})

    assert response.status_code == 200
    assert response.json()["descriptors"][0]["name"] == "Familial Mediterranean Fever"
    service.lookup_mesh.assert_awaited_once_with(query="FMF", limit=5, exact=False)


@pytest.mark.asyncio
async def test_mesh_route_rejects_limit_below_minimum_without_calling_service() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.lookup_mesh.return_value = MeshLookupResponse(query="FMF")
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/discovery/mesh", params={"query": "FMF", "limit": 0})

    assert response.status_code == 422
    service.lookup_mesh.assert_not_called()


@pytest.mark.asyncio
async def test_mesh_route_rejects_empty_query_without_calling_service() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.lookup_mesh.return_value = MeshLookupResponse(query="")
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/discovery/mesh", params={"query": "", "limit": 5})

    assert response.status_code == 422
    service.lookup_mesh.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_citations_route_returns_matched_status() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.lookup_citation.return_value = CitationLookupResponse(
        records=[
            CitationLookupRecord(
                citation="Ozen et al.",
                status="matched",
                pmid="123",
            )
        ],
        candidate_pmids=["123"],
    )
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/discovery/lookup-citations",
            json={"citations": ["Ozen et al."]},
        )

    assert response.status_code == 200
    assert response.json()["records"][0]["status"] == "matched"
    service.lookup_citation.assert_awaited_once_with(citations=["Ozen et al."])


@pytest.mark.asyncio
async def test_related_articles_route_returns_candidate_pmids() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.find_related_articles.return_value = RelatedArticlesResponse(
        source_pmids=["123"],
        mode="similar",
        related_articles=[
            RelatedArticleRecord(
                source_pmid="123",
                pmid="456",
                relation="similar",
            )
        ],
        candidate_pmids=["456"],
        unresolved=[],
    )
    app.dependency_overrides[get_discovery_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/discovery/related-articles",
            json={"pmids": ["123"], "mode": "similar", "limit": 20},
        )

    assert response.status_code == 200
    assert response.json()["candidate_pmids"] == ["456"]
    service.find_related_articles.assert_awaited_once_with(
        pmids=["123"],
        mode="similar",
        limit=20,
    )


@pytest.mark.asyncio
async def test_suggest_corpus_route_returns_candidate_pmids() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.suggest.return_value = CorpusSuggestionResponse(
        candidate_pmids=["26802180", "33726481"],
        candidates=[],
        searches=[],
        _meta={"next_commands": ["index_review_evidence"]},
    )
    app.dependency_overrides[get_corpus_suggestion_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/discovery/suggest-corpus",
            json={"question": "FMF MEFV VUS colchicine", "max_pmids": 2},
        )

    assert response.status_code == 200
    assert response.json()["candidate_pmids"] == ["26802180", "33726481"]
    service.suggest.assert_awaited_once()
    assert service.suggest.await_args.args[0].question == "FMF MEFV VUS colchicine"


@pytest.mark.asyncio
async def test_cleanup_dependencies_closes_fallback_discovery_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDiscoveryClient:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    client = FakeDiscoveryClient()
    monkeypatch.setattr(dependencies, "_ncbi_discovery_client", client)
    monkeypatch.setattr(dependencies, "_discovery_service", object())
    monkeypatch.setattr(dependencies, "_api_client", None)
    monkeypatch.setattr(dependencies, "_review_queue", None)
    monkeypatch.setattr(dependencies, "_review_pool", None)

    await cleanup_dependencies()

    assert client.closed is True
    assert dependencies._ncbi_discovery_client is None
    assert dependencies._discovery_service is None
