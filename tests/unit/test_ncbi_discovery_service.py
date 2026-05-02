from __future__ import annotations

from collections.abc import Sequence

import pytest

from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdKind,
    CitationLookupRecord,
    MeshDescriptor,
    RelatedArticleMode,
    RelatedArticleRecord,
)
from pubtator_link.services.ncbi_discovery import DiscoveryService


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
