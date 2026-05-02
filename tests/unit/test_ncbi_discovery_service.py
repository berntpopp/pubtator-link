from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest

from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdKind,
    CitationLookupRecord,
    MeshDescriptor,
    RelatedArticleMode,
    RelatedArticleRecord,
)
from pubtator_link.services.ncbi_discovery import DiscoveryService, NcbiDiscoveryClient


class MockTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.payload, request=request)


class FakeDiscoveryClient:
    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind,
    ) -> list[ArticleIdConversionRecord]:
        return [
            ArticleIdConversionRecord(
                input_id="PMC123",
                input_kind="pmcid",
                status="resolved",
                pmid="123",
                pmcid="PMC123",
            ),
            ArticleIdConversionRecord(
                input_id="bad",
                input_kind="auto",
                status="unresolved",
                reason="not_found",
            ),
        ]

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]:
        return [
            MeshDescriptor(
                ui="D010505",
                name="Familial Mediterranean Fever",
                search_terms=["familial mediterranean fever"],
            )
        ]

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        return [
            CitationLookupRecord(citation="citation 1", status="matched", pmid="123"),
            CitationLookupRecord(citation="citation 2", status="matched", pmid="123"),
            CitationLookupRecord(citation="missing", status="not_found", reason="not_found"),
        ]

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode,
        limit: int,
    ) -> list[RelatedArticleRecord]:
        return [
            RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode),
            RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode),
            RelatedArticleRecord(source_pmid="123", pmid="789", relation=mode),
        ]


@pytest.mark.asyncio
async def test_convert_article_ids_adds_candidates_and_next_commands() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.convert_article_ids(["PMC123", "bad"])

    assert response.candidate_pmids == ["123"]
    assert response.unresolved == ["bad"]
    assert response.meta.next_commands[0]["tool"] == "pubtator.stage_research_session"


@pytest.mark.asyncio
async def test_ncbi_client_parses_id_conversion_json() -> None:
    transport = MockTransport(
        {
            "records": [
                {
                    "requested-id": "10.1000/example",
                    "pmid": "456",
                    "pmcid": "PMC456",
                    "doi": "10.1000/example",
                },
                {"pmid": "123", "pmcid": "PMC123", "doi": "10.1000/example"},
                {"requested-id": "bad", "status": "error"},
            ]
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.convert_article_ids(["10.1000/example", "PMC123", "bad"], "auto")

    assert [record.input_id for record in records] == ["10.1000/example", "PMC123", "bad"]
    assert records[0].status == "resolved"
    assert records[0].pmid == "456"
    assert records[0].pmcid == "PMC456"
    assert records[0].doi == "10.1000/example"
    assert records[1].status == "resolved"
    assert records[1].pmid == "123"
    assert records[1].pmcid == "PMC123"
    assert records[2].status == "unresolved"
    assert records[2].reason == "not_found"
    assert (
        str(transport.requests[0].url.copy_with(query=None))
        == "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
    )
    assert transport.requests[0].url.params["ids"] == "10.1000/example,PMC123,bad"
    assert transport.requests[0].url.params["format"] == "json"
    assert transport.requests[0].url.params["tool"] == "pubtator-link"
    assert "idtype" not in transport.requests[0].url.params
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_sends_idtype_for_explicit_source() -> None:
    transport = MockTransport(
        {"records": [{"requested-id": "PMC123", "pmid": "123", "pmcid": "PMC123"}]}
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.convert_article_ids(["PMC123"], "pmcid")

    assert records[0].status == "resolved"
    assert transport.requests[0].url.params["ids"] == "PMC123"
    assert transport.requests[0].url.params["idtype"] == "pmcid"
    await client.close()


@pytest.mark.asyncio
async def test_lookup_mesh_returns_search_next_command() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.lookup_mesh("familial mediterranean fever")

    assert response.descriptors[0].ui == "D010505"
    assert response.meta.next_commands[0]["tool"] == "pubtator.search_literature"


@pytest.mark.asyncio
async def test_lookup_citation_deduplicates_candidate_pmids() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.lookup_citation(["citation 1", "citation 2", "missing"])

    assert response.candidate_pmids == ["123"]


@pytest.mark.asyncio
async def test_find_related_articles_deduplicates_candidates() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.find_related_articles(["123", "999"])

    assert response.candidate_pmids == ["456", "789"]
    assert response.meta.next_commands[0]["arguments"] == {"candidate_pmids": ["456", "789"]}
    assert response.unresolved == ["999"]
