from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import get_discovery_service
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.models.discovery import (
    ArticleIdConversionResponse,
    ArticleIdKind,
    CitationLookupResponse,
    MeshLookupResponse,
    RelatedArticleMode,
    RelatedArticlesResponse,
)


def register_discovery_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.convert_article_ids",
        title="Convert Article IDs",
        output_schema=ArticleIdConversionResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def convert_article_ids(
        ids: Annotated[list[str], Field(min_length=1, max_length=200)],
        source: ArticleIdKind = "auto",
    ) -> dict[str, Any]:
        """Use this when a user provides article identifiers such as PMIDs, PMCIDs, or DOIs and needs normalized candidate PMIDs for research workflows. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_discovery_service()
        response = await service.convert_article_ids(ids=ids, source=source)
        return response.model_dump(by_alias=True)

    @mcp.tool(
        name="pubtator.lookup_mesh",
        title="Lookup MeSH",
        output_schema=MeshLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_mesh(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        exact: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user needs MeSH descriptors and candidate PubMed search terms for a biomedical research query. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_discovery_service()
        response = await service.lookup_mesh(query=query, limit=limit, exact=exact)
        return response.model_dump(by_alias=True)

    @mcp.tool(
        name="pubtator.lookup_citation",
        title="Lookup Citation",
        output_schema=CitationLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_citation(
        citations: Annotated[list[str], Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Use this when a user provides free-text citations and needs candidate PMIDs for research evidence gathering. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_discovery_service()
        response = await service.lookup_citation(citations=citations)
        return response.model_dump(by_alias=True)

    @mcp.tool(
        name="pubtator.find_related_articles",
        title="Find Related Articles",
        output_schema=RelatedArticlesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_related_articles(
        pmids: Annotated[list[str], Field(min_length=1, max_length=100)],
        mode: RelatedArticleMode = "similar",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """Use this when a user has seed PMIDs and needs similar, cited-by, or reference-linked articles to expand a research corpus. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_discovery_service()
        response = await service.find_related_articles(pmids=pmids, mode=mode, limit=limit)
        return response.model_dump(by_alias=True)
