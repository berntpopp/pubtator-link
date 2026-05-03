from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import (
    get_citation_graph_service,
    get_related_evidence_service,
)
from pubtator_link.models.literature_graph import (
    LiteraturePaper,
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidatesResponse,
)
from pubtator_link.server_manager import UnifiedServerManager


@pytest.mark.asyncio
async def test_citation_graph_route_rejects_both_identifiers_without_calling_service() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    app.dependency_overrides[get_citation_graph_service] = lambda: service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/publications/citation-graph",
            json={"pmid": "40562663", "doi": "10.1016/j.ard.2025.05.020"},
        )

    assert response.status_code == 422
    service.get_citation_graph.assert_not_called()


@pytest.mark.asyncio
async def test_citation_graph_route_returns_response_and_passes_request() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_citation_graph.return_value = PublicationCitationGraphResponse(
        source=LiteraturePaper(pmid="40562663"),
        cited_by=[LiteraturePaper(pmid="40600001", title="Citing study")],
        candidate_pmids=["40600001"],
    )
    app.dependency_overrides[get_citation_graph_service] = lambda: service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/publications/citation-graph",
            json={"pmid": "40562663"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_pmids"] == ["40600001"]
    assert payload["cited_by"][0]["title"] == "Citing study"
    request = service.get_citation_graph.call_args.args[0]
    assert request.pmid == "40562663"


@pytest.mark.asyncio
async def test_related_evidence_route_returns_response_and_passes_request() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.find_candidates.return_value = RelatedEvidenceCandidatesResponse(
        source=LiteraturePaper(pmid="111"),
        candidate_pmids=["222"],
    )
    app.dependency_overrides[get_related_evidence_service] = lambda: service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/publications/related-evidence",
            json={"pmid": "111"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_pmids"] == ["222"]
    request = service.find_candidates.call_args.args[0]
    assert request.pmid == "111"


@pytest.mark.asyncio
async def test_related_evidence_route_rejects_nonnumeric_pmid_without_calling_service() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    app.dependency_overrides[get_related_evidence_service] = lambda: service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/publications/related-evidence",
            json={"pmid": "not-a-pmid"},
        )

    assert response.status_code == 422
    service.find_candidates.assert_not_called()
