"""Discovery routes for research-use literature candidate expansion."""

from typing import Annotated

from fastapi import APIRouter, Query

from ...models.discovery import (
    ArticleIdConversionRequest,
    ArticleIdConversionResponse,
    CitationLookupRequest,
    CitationLookupResponse,
    MeshLookupResponse,
    RelatedArticlesRequest,
    RelatedArticlesResponse,
)
from .dependencies import DiscoveryServiceDep, handle_api_errors

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post(
    "/convert-article-ids",
    response_model=ArticleIdConversionResponse,
)
@handle_api_errors
async def convert_article_ids(
    request: ArticleIdConversionRequest,
    service: DiscoveryServiceDep,
) -> ArticleIdConversionResponse:
    return await service.convert_article_ids(ids=request.ids, source=request.source)


@router.get(
    "/mesh",
    response_model=MeshLookupResponse,
)
@handle_api_errors
async def lookup_mesh(
    service: DiscoveryServiceDep,
    query: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    exact: bool = False,
) -> MeshLookupResponse:
    return await service.lookup_mesh(query=query, limit=limit, exact=exact)


@router.post(
    "/lookup-citations",
    response_model=CitationLookupResponse,
)
@handle_api_errors
async def lookup_citations(
    request: CitationLookupRequest,
    service: DiscoveryServiceDep,
) -> CitationLookupResponse:
    return await service.lookup_citation(citations=request.citations)


@router.post(
    "/related-articles",
    response_model=RelatedArticlesResponse,
)
@handle_api_errors
async def related_articles(
    request: RelatedArticlesRequest,
    service: DiscoveryServiceDep,
) -> RelatedArticlesResponse:
    return await service.find_related_articles(
        pmids=request.pmids,
        mode=request.mode,
        limit=request.limit,
    )
