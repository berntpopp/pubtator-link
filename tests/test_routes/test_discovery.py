from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import get_discovery_service
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
