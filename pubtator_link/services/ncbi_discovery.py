"""NCBI E-utilities discovery client and response mapping service."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

import httpx
from httpx._types import QueryParamTypes

from pubtator_link.api.retry import RetryPolicy, call_with_retries
from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdConversionResponse,
    ArticleIdKind,
    CitationLookupRecord,
    CitationLookupResponse,
    DiscoveryMeta,
    MeshDescriptor,
    MeshLookupResponse,
    RelatedArticleMode,
    RelatedArticleRecord,
    RelatedArticlesResponse,
)

NCBI_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_EUTILS_SOURCE_URL = "https://www.ncbi.nlm.nih.gov/books/NBK25501/"
NCBI_MESH_SOURCE_URL = "https://www.ncbi.nlm.nih.gov/mesh/"


class NcbiDiscoveryClientProtocol(Protocol):
    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind,
    ) -> list[ArticleIdConversionRecord]:
        """Convert article identifiers to PubMed-centered records."""

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]:
        """Look up MeSH descriptors for a query."""

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        """Resolve free-text citations to article records."""

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode,
        limit: int,
    ) -> list[RelatedArticleRecord]:
        """Find related PubMed articles for source PMIDs."""


class NcbiDiscoveryClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = NCBI_EUTILS_BASE_URL,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self.base_url = base_url.rstrip("/")
        self.retry_policy = retry_policy or RetryPolicy()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: QueryParamTypes) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response, _metadata = await call_with_retries(
            lambda: self._client.get(url, params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        return response

    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind,
    ) -> list[ArticleIdConversionRecord]:
        raise NotImplementedError

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]:
        raise NotImplementedError

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        raise NotImplementedError

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode,
        limit: int,
    ) -> list[RelatedArticleRecord]:
        raise NotImplementedError


class DiscoveryService:
    def __init__(self, client: NcbiDiscoveryClientProtocol) -> None:
        self.client = client

    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind = "auto",
    ) -> ArticleIdConversionResponse:
        records = await self.client.convert_article_ids(ids, source)
        candidate_pmids = _dedupe(record.pmid for record in records if record.pmid is not None)
        unresolved = [record.input_id for record in records if record.status != "resolved"]
        return ArticleIdConversionResponse(
            records=records,
            candidate_pmids=candidate_pmids,
            unresolved=unresolved,
            _meta=_candidate_meta(candidate_pmids),
        )

    async def lookup_mesh(
        self,
        query: str,
        limit: int = 10,
        exact: bool = False,
    ) -> MeshLookupResponse:
        descriptors = await self.client.lookup_mesh(query, limit, exact)
        next_commands: list[dict[str, object]] = [
            {
                "tool": "pubtator.search_literature",
                "arguments": {
                    "text": descriptor.search_terms[0]
                    if descriptor.search_terms
                    else descriptor.name
                },
            }
            for descriptor in descriptors
        ]
        return MeshLookupResponse(
            query=query,
            descriptors=descriptors,
            _meta=DiscoveryMeta(
                source_urls=[NCBI_MESH_SOURCE_URL],
                next_commands=next_commands,
            ),
        )

    async def lookup_citation(self, citations: Sequence[str]) -> CitationLookupResponse:
        records = await self.client.lookup_citations(citations)
        candidate_pmids = _dedupe(record.pmid for record in records if record.pmid is not None)
        return CitationLookupResponse(
            records=records,
            candidate_pmids=candidate_pmids,
            _meta=_candidate_meta(candidate_pmids),
        )

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode = "similar",
        limit: int = 20,
    ) -> RelatedArticlesResponse:
        related_articles = await self.client.find_related_articles(pmids, mode, limit)
        candidate_pmids = _dedupe(record.pmid for record in related_articles)
        resolved_source_pmids = {record.source_pmid for record in related_articles}
        unresolved = [pmid for pmid in pmids if pmid not in resolved_source_pmids]
        return RelatedArticlesResponse(
            source_pmids=list(pmids),
            mode=mode,
            related_articles=related_articles,
            candidate_pmids=candidate_pmids,
            unresolved=unresolved,
            _meta=_candidate_meta(candidate_pmids),
        )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _candidate_meta(candidate_pmids: list[str]) -> DiscoveryMeta:
    next_commands: list[dict[str, object]] = []
    if candidate_pmids:
        next_commands = [
            {
                "tool": "pubtator.stage_research_session",
                "arguments": {"candidate_pmids": candidate_pmids},
            },
            {
                "tool": "pubtator.index_review_evidence",
                "arguments": {"pmids": candidate_pmids, "prepare_mode": "selected"},
            },
        ]
    return DiscoveryMeta(
        source_urls=[NCBI_EUTILS_SOURCE_URL],
        next_commands=next_commands,
    )
