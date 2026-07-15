from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_corpus_suggestion_service,
    get_discovery_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.argument_aliases import merge_pmids
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import suggest_corpus_impl
from pubtator_link.models.discovery import ArticleIdKind, RelatedArticleMode


def register_discovery_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    if profile == "lean":
        return

    @mcp.tool(
        name="suggest_corpus",
        title="Suggest Corpus",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def suggest_corpus(
        question: Annotated[
            str,
            Field(
                min_length=3,
                max_length=1000,
                description="Research question to assemble a compact candidate PMID corpus for.",
                examples=["Does colchicine prevent FMF flares?"],
            ),
        ],
        max_pmids: Annotated[
            int,
            Field(ge=1, le=20, description="Maximum candidate PMIDs to return."),
        ] = 8,
        entity_ids: Annotated[
            list[str] | None,
            Field(
                description="Optional PubTator entity IDs to anchor the corpus on.",
                examples=[["@GENE_MEFV"]],
            ),
        ] = None,
        must_include_pmids: Annotated[
            list[str] | None,
            Field(
                description="PMIDs that MUST appear in the returned corpus.",
                examples=[["31036433"]],
            ),
        ] = None,
        prefer_guidelines: Annotated[
            bool,
            Field(description="Bias selection toward guideline / review articles."),
        ] = True,
        include_metadata: Annotated[
            bool,
            Field(description="Attach per-PMID citation metadata to each candidate."),
        ] = True,
    ) -> dict[str, Any]:
        """Use this when a user needs a compact, review-feeding PMID corpus for a research question. Returns candidate PMIDs, roles, coverage hints, metadata, and next commands."""

        async def call() -> dict[str, Any]:
            selected_question = question
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

        return await run_mcp_tool("suggest_corpus", call)

    @mcp.tool(
        name="convert_article_ids",
        title="Convert Article IDs",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def convert_article_ids(
        ids: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=200,
                description="Article identifiers (PMIDs, PMCIDs, or DOIs) to normalize to PMIDs.",
                examples=[["PMC123456", "10.1000/example"]],
            ),
        ],
        source: Annotated[
            ArticleIdKind,
            Field(
                description=(
                    "Identifier kind: 'auto' (default, detect), 'pmid', 'pmcid', or 'doi'."
                ),
            ),
        ] = "auto",
    ) -> dict[str, Any]:
        """Use this when a user provides article identifiers such as PMIDs, PMCIDs, or DOIs and needs normalized candidate PMIDs for research workflows."""

        async def call() -> dict[str, Any]:
            service = await get_discovery_service()
            response = await service.convert_article_ids(ids=ids, source=source)
            return response.model_dump(by_alias=True)

        return await run_mcp_tool("convert_article_ids", call)

    @mcp.tool(
        name="get_mesh",
        title="Lookup MeSH",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_mesh(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Term to resolve to MeSH descriptors and candidate search terms.",
                examples=["breast cancer"],
            ),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="Maximum MeSH descriptors to return."),
        ] = 10,
        exact: Annotated[
            bool,
            Field(description="Require an exact descriptor match instead of prefix/fuzzy."),
        ] = False,
    ) -> dict[str, Any]:
        """Use this when a user needs MeSH descriptors and candidate PubMed search terms for a biomedical research query."""

        async def call() -> dict[str, Any]:
            selected_query = query
            service = await get_discovery_service()
            response = await service.lookup_mesh(query=selected_query, limit=limit, exact=exact)
            return response.model_dump(by_alias=True)

        return await run_mcp_tool("get_mesh", call)

    @mcp.tool(
        name="get_citation",
        title="Lookup Citation",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_citation(
        citations: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=100,
                description="Free-text citation strings to resolve to candidate PMIDs.",
                examples=[["Smith J. Example disease study. 2024."]],
            ),
        ],
    ) -> dict[str, Any]:
        """Use this when a user provides free-text citations and needs candidate PMIDs for research evidence gathering."""

        async def call() -> dict[str, Any]:
            service = await get_discovery_service()
            response = await service.lookup_citation(citations=citations)
            return response.model_dump(by_alias=True)

        return await run_mcp_tool("get_citation", call)

    @mcp.tool(
        name="find_related_articles",
        title="Find Related Articles",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_related_articles(
        pmids: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=100,
                description="Seed PMIDs to expand from.",
                examples=[["25741868"]],
            ),
        ],
        mode: Annotated[
            RelatedArticleMode,
            Field(
                description=(
                    "Relation to follow: 'similar' (default), 'cited_by', or 'references'."
                ),
            ),
        ] = "similar",
        limit: Annotated[
            int,
            Field(ge=1, le=100, description="Maximum related articles to return."),
        ] = 20,
    ) -> dict[str, Any]:
        """Use this when a user has seed PMIDs and needs similar, cited-by, or reference-linked articles to expand a research corpus."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, None, max_items=100)
            service = await get_discovery_service()
            response = await service.find_related_articles(
                pmids=selected_pmids,
                mode=mode,
                limit=limit,
            )
            return response.model_dump(by_alias=True)

        try:
            tool_pmids = merge_pmids(pmids, None, max_items=100)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool("find_related_articles", call, pmids=tool_pmids)
