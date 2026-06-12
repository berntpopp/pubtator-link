from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_api_client,
    get_publication_metadata_service,
    get_source_preflight_service,
    get_variant_evidence_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.argument_aliases import coalesce_query
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (
    find_entity_relations_impl,
    lookup_variant_evidence_impl,
    search_biomedical_entities_impl,
    search_literature_impl,
)
from pubtator_link.models.responses import (
    EntityAutocompleteResponse,
    RelationsResponse,
    SearchResponse,
)
from pubtator_link.models.variants import VariantEvidenceResponse, VariantEvidenceSource
from pubtator_link.services.search_coverage import SearchCoverageMode
from pubtator_link.services.search_shaping import (
    IncludeCitations,
    SearchMetadataMode,
    SearchResponseMode,
    TextHighlightFormat,
)


def register_literature_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    @mcp.tool(
        name="pubtator_search_literature",
        title="Search Biomedical Literature",
        output_schema=SearchResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_literature(
        text: str | None = None,
        query: str | None = None,
        page: int = 1,
        sort: Annotated[
            str | None,
            Field(
                description=(
                    "Sort order. Accepts 'date desc' (newest first), 'score desc' "
                    "(relevance, default), or '_id desc'. Synonyms such as 'date' or "
                    "'relevance' are normalized; PubTator3 sorts descending only."
                ),
            ),
        ] = None,
        filters: str | None = None,
        publication_types: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        sections: list[str] | None = None,
        response_mode: SearchResponseMode = "compact",
        include_citations: IncludeCitations = "none",
        text_hl_format: TextHighlightFormat = "plain",
        limit: Annotated[int | None, Field(ge=1, le=20)] = 5,
        entity_ids: list[str] | None = None,
        guideline_boost: bool = False,
        coverage: SearchCoverageMode = "none",
        metadata: SearchMetadataMode = "basic",
        include_meta: bool = True,
    ) -> dict[str, Any]:
        """Use this when a user needs PubMed literature search through PubTator3. Provide one of text or query. Supports flat filters, section filters, and coverage='preflight'. If preflight_error_code is coverage_preflight_internal_error, retryable=false means continue with results or inspect diagnostics."""

        async def call() -> dict[str, Any]:
            search_text = coalesce_query(text, query)
            preflight_service = (
                await get_source_preflight_service() if coverage == "preflight" else None
            )
            metadata_service = (
                await get_publication_metadata_service() if metadata != "none" else None
            )
            client = await get_api_client()
            return await search_literature_impl(
                client=client,
                text=search_text,
                page=page,
                sort=sort,
                filters=filters,
                publication_types=publication_types,
                year_min=year_min,
                year_max=year_max,
                sections=sections,
                response_mode=response_mode,
                include_citations=include_citations,
                text_hl_format=text_hl_format,
                limit=limit,
                entity_ids=entity_ids,
                guideline_boost=guideline_boost,
                coverage=coverage,
                preflight_service=preflight_service,
                metadata=metadata,
                metadata_service=metadata_service,
                include_meta=include_meta,
            )

        return await run_mcp_tool("pubtator_search_literature", call)

    @mcp.tool(
        name="pubtator_search_guidelines",
        title="Search Biomedical Guidelines",
        output_schema=SearchResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_guidelines(
        text: Annotated[str | None, Field(min_length=1, max_length=1000)] = None,
        query: Annotated[str | None, Field(min_length=1, max_length=1000)] = None,
        page: int = 1,
        year_min: int | None = None,
        year_max: int | None = None,
        sections: list[str] | None = None,
        limit: Annotated[int | None, Field(ge=1, le=20)] = 5,
        entity_ids: list[str] | None = None,
        coverage: SearchCoverageMode = "preflight",
    ) -> dict[str, Any]:
        """Use this when a user needs guideline, recommendation, consensus, or systematic review papers for a biomedical research question. Provide one of text or query. Wraps pubtator_search_literature with guideline/systematic-review filters and guideline boosting; not an independent guideline database."""

        async def call() -> dict[str, Any]:
            search_text = coalesce_query(text, query)
            preflight_service = (
                await get_source_preflight_service() if coverage == "preflight" else None
            )
            client = await get_api_client()
            return await search_literature_impl(
                client=client,
                text=search_text,
                page=page,
                sort="score desc",
                publication_types=None,
                year_min=year_min,
                year_max=year_max,
                sections=sections,
                response_mode="standard",
                include_citations="nlm",
                text_hl_format="plain",
                limit=limit,
                entity_ids=entity_ids,
                guideline_boost=True,
                coverage=coverage,
                preflight_service=preflight_service,
            )

        return await run_mcp_tool("pubtator_search_guidelines", call)

    @mcp.tool(
        name="pubtator_search_biomedical_entities",
        title="Search Biomedical Entities",
        output_schema=EntityAutocompleteResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_biomedical_entities(
        query: str | None = None,
        text: str | None = None,
        concept: (
            Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine", "Phenotype"]
            | None
        ) = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Use this when a user needs canonical PubTator biomedical entity IDs for genes, diseases, chemicals, species, variants, or cell lines."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            return await search_biomedical_entities_impl(
                client=client,
                query=query if query and query.strip() else text or "",
                concept=concept,
                limit=limit,
            )

        return await run_mcp_tool("pubtator_search_biomedical_entities", call)

    if profile != "lean":

        @mcp.tool(
            name="pubtator_find_entity_relations",
            title="Find Entity Relations",
            output_schema=RelationsResponse.model_json_schema(),
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def find_entity_relations(
            entity_id: Annotated[
                str,
                Field(
                    min_length=1,
                    description="PubTator entity ID such as @CHEMICAL_remdesivir.",
                ),
            ],
            relation_type: str | None = None,
            target_entity_type: str | None = None,
            limit: Annotated[int, Field(ge=1, le=100)] = 20,
            response_mode: Literal["compact", "standard", "full"] = "compact",
            max_response_chars: Annotated[int, Field(ge=1000, le=50000)] = 12_000,
        ) -> dict[str, Any]:
            """Use this when a user has a PubTator entity ID and needs literature-derived related entities to expand a corpus. Do not use this for canonical entity lookup; use pubtator_search_biomedical_entities. Next: pubtator_search_literature."""

            async def call() -> dict[str, Any]:
                client = await get_api_client()
                return await find_entity_relations_impl(
                    client=client,
                    entity_id=entity_id,
                    relation_type=relation_type,
                    target_entity_type=target_entity_type,
                    limit=limit,
                    response_mode=response_mode,
                    max_response_chars=max_response_chars,
                )

            return await run_mcp_tool("pubtator_find_entity_relations", call)

    @mcp.tool(
        name="pubtator_lookup_variant_evidence",
        title="Lookup Variant Evidence",
        output_schema=VariantEvidenceResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_variant_evidence(
        gene: Annotated[str, Field(min_length=1)],
        variant: Annotated[str | None, Field(min_length=1)] = None,
        protein: Annotated[str | None, Field(min_length=1)] = None,
        condition: Annotated[str | None, Field(min_length=1)] = None,
        sources: list[VariantEvidenceSource] | None = None,
        max_literature_pmids: Annotated[int, Field(ge=0, le=100)] = 20,
        include_citations: bool = True,
    ) -> dict[str, Any]:
        """Use this when a user needs source-attributed variant records and literature evidence for a gene and variant. Does not compute clinical classification."""

        async def call() -> dict[str, Any]:
            service = await get_variant_evidence_service()
            return await lookup_variant_evidence_impl(
                service=service,
                gene=gene,
                variant=variant,
                protein=protein,
                condition=condition,
                sources=sources,
                max_literature_pmids=max_literature_pmids,
                include_citations=include_citations,
            )

        return await run_mcp_tool("pubtator_lookup_variant_evidence", call)
