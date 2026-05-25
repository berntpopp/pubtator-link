from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_corpus_suggestion_service,
    get_discovery_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.argument_aliases import coalesce_query, merge_pmids
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import suggest_corpus_impl
from pubtator_link.models.corpus_suggestion import CorpusSuggestionResponse
from pubtator_link.models.discovery import (
    ArticleIdConversionResponse,
    ArticleIdKind,
    CitationLookupResponse,
    MeshLookupResponse,
    RelatedArticleMode,
    RelatedArticlesResponse,
)


def register_discovery_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    if profile == "lean":
        return

    @mcp.tool(
        name="pubtator_suggest_corpus",
        title="Suggest Corpus",
        output_schema=CorpusSuggestionResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def suggest_corpus(
        question: Annotated[str | None, Field(min_length=3, max_length=1000)] = None,
        query: Annotated[str | None, Field(min_length=3, max_length=1000)] = None,
        max_pmids: Annotated[int, Field(ge=1, le=20)] = 8,
        entity_ids: list[str] | None = None,
        must_include_pmids: list[str] | None = None,
        prefer_guidelines: bool = True,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """Use this when a user needs a compact, review-feeding PMID corpus for a research question. Provide one of question or query. Returns candidate PMIDs, roles, coverage hints, metadata, and next commands."""

        async def call() -> dict[str, Any]:
            selected_question = coalesce_query(question, query)
            service = await get_corpus_suggestion_service()
            return await suggest_corpus_impl(
                service=service,
                question=selected_question,
                max_pmids=max_pmids,
                entity_ids=entity_ids,
                must_include_pmids=must_include_pmids,
                prefer_guidelines=prefer_guidelines,
                include_metadata=include_metadata,
            )

        return await run_mcp_tool("pubtator_suggest_corpus", call)

    @mcp.tool(
        name="pubtator_convert_article_ids",
        title="Convert Article IDs",
        output_schema=ArticleIdConversionResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def convert_article_ids(
        ids: Annotated[list[str], Field(min_length=1, max_length=200)],
        source: ArticleIdKind = "auto",
    ) -> dict[str, Any]:
        """Use this when a user provides article identifiers such as PMIDs, PMCIDs, or DOIs and needs normalized candidate PMIDs for research workflows."""

        async def call() -> dict[str, Any]:
            service = await get_discovery_service()
            response = await service.convert_article_ids(ids=ids, source=source)
            return response.model_dump(by_alias=True)

        return await run_mcp_tool("pubtator_convert_article_ids", call)

    @mcp.tool(
        name="pubtator_lookup_mesh",
        title="Lookup MeSH",
        output_schema=MeshLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_mesh(
        query: Annotated[str | None, Field(min_length=1, max_length=500)] = None,
        text: Annotated[str | None, Field(min_length=1, max_length=500)] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        exact: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user needs MeSH descriptors and candidate PubMed search terms for a biomedical research query."""

        async def call() -> dict[str, Any]:
            selected_query = coalesce_query(query, text)
            service = await get_discovery_service()
            response = await service.lookup_mesh(query=selected_query, limit=limit, exact=exact)
            return response.model_dump(by_alias=True)

        return await run_mcp_tool("pubtator_lookup_mesh", call)

    @mcp.tool(
        name="pubtator_lookup_citation",
        title="Lookup Citation",
        output_schema=CitationLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_citation(
        citations: Annotated[list[str], Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Use this when a user provides free-text citations and needs candidate PMIDs for research evidence gathering."""

        async def call() -> dict[str, Any]:
            service = await get_discovery_service()
            response = await service.lookup_citation(citations=citations)
            return response.model_dump(by_alias=True)

        return await run_mcp_tool("pubtator_lookup_citation", call)

    @mcp.tool(
        name="pubtator_find_related_articles",
        title="Find Related Articles",
        output_schema=RelatedArticlesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_related_articles(
        pmids: Annotated[list[str] | None, Field(min_length=1, max_length=100)] = None,
        pmid: Annotated[str | None, Field(min_length=1)] = None,
        mode: RelatedArticleMode = "similar",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """Use this when a user has seed PMIDs and needs similar, cited-by, or reference-linked articles to expand a research corpus."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, pmid, max_items=100)
            service = await get_discovery_service()
            response = await service.find_related_articles(
                pmids=selected_pmids,
                mode=mode,
                limit=limit,
            )
            return response.model_dump(by_alias=True)

        try:
            tool_pmids = merge_pmids(pmids, pmid, max_items=100)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool("pubtator_find_related_articles", call, pmids=tool_pmids)
