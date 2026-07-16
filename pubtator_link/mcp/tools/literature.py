from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_api_client,
    get_publication_metadata_service,
    get_source_preflight_service,
    get_variant_evidence_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (
    find_entity_relations_impl,
    lookup_variant_evidence_impl,
    search_biomedical_entities_impl,
    search_literature_impl,
)
from pubtator_link.mcp.tools._vocab import PublicationType, SearchSection
from pubtator_link.models.variants import VariantEvidenceSource
from pubtator_link.services.search_coverage import SearchCoverageMode
from pubtator_link.services.search_shaping import (
    IncludeCitations,
    SearchMetadataMode,
    SearchResponseMode,
    TextHighlightFormat,
)


def register_literature_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    @mcp.tool(
        name="search_literature",
        title="Search Biomedical Literature",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_literature(
        text: Annotated[
            str,
            Field(
                min_length=1,
                max_length=1000,
                description=(
                    "Free-text PubMed/PubTator3 query: entity names, gene symbols, HGVS, or a "
                    "natural-language topic. PubTator3 matches across title, abstract, and, for "
                    "open-access articles, full text."
                ),
                examples=["BRCA1 ovarian cancer PARP inhibitor"],
            ),
        ],
        page: Annotated[
            int,
            Field(ge=1, le=1000, description="1-based page number for paging beyond `limit`."),
        ] = 1,
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
        filters: Annotated[
            str | None,
            Field(
                description=(
                    "Advanced PubTator3 filter as a JSON object string, e.g. "
                    '\'{"journal":["Nature"]}\'. Prefer the flat publication_types / year_min / '
                    "year_max parameters; do not also set a JSON `type`/`year` key."
                ),
            ),
        ] = None,
        publication_types: Annotated[
            list[PublicationType] | None,
            Field(
                description=(
                    "Restrict to these PubMed publication types (case-sensitive, Title-Case), "
                    "AND-combined with the query."
                ),
                examples=[["Review", "Meta-Analysis"]],
            ),
        ] = None,
        year_min: Annotated[
            int | None,
            Field(ge=1800, le=2030, description="Earliest publication year, inclusive."),
        ] = None,
        year_max: Annotated[
            int | None,
            Field(ge=1800, le=2030, description="Latest publication year, inclusive."),
        ] = None,
        sections: Annotated[
            list[SearchSection] | None,
            Field(
                description=(
                    "Restrict the text match to these article sections (lowercase, case-sensitive)."
                ),
                examples=[["title", "abstract"]],
            ),
        ] = None,
        response_mode: Annotated[
            SearchResponseMode,
            Field(
                description="Payload verbosity: 'compact' (default, LLM-friendly), 'standard', or 'full'."
            ),
        ] = "compact",
        include_citations: Annotated[
            IncludeCitations,
            Field(
                description="Citation rendering per hit: 'none' (default), 'nlm', 'bibtex', or 'both'."
            ),
        ] = "none",
        text_hl_format: Annotated[
            TextHighlightFormat,
            Field(
                description="Match-highlight rendering: 'none', 'plain' (default), or 'annotated'."
            ),
        ] = "plain",
        limit: Annotated[
            int | None,
            Field(ge=1, le=20, description="Maximum hits to return on this page."),
        ] = 5,
        entity_ids: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Restrict to articles mentioning these PubTator entity IDs (resolve them "
                    "first with search_biomedical_entities), AND-combined with the query."
                ),
                examples=[["@GENE_BRCA1"]],
            ),
        ] = None,
        guideline_boost: Annotated[
            bool,
            Field(
                description="Boost guideline / systematic-review / consensus articles in ranking."
            ),
        ] = False,
        coverage: Annotated[
            SearchCoverageMode,
            Field(description="'none' (default) or 'preflight' to attach source-coverage hints."),
        ] = "none",
        metadata: Annotated[
            SearchMetadataMode,
            Field(
                description=(
                    "Metadata enrichment per hit: 'none', 'basic' (default), 'with_abstract', "
                    "or 'full'."
                ),
            ),
        ] = "basic",
        include_meta: Annotated[
            bool,
            Field(description="Include the _meta orientation block (next_commands, provenance)."),
        ] = True,
    ) -> dict[str, Any]:
        """Use this when a user needs PubMed literature search through PubTator3. Supports flat filters, section filters, and coverage='preflight'. If preflight_error_code is coverage_preflight_internal_error, retryable=false means continue with results or inspect diagnostics."""

        async def call() -> dict[str, Any]:
            search_text = text
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
                publication_types=cast("list[str] | None", publication_types),
                year_min=year_min,
                year_max=year_max,
                sections=cast("list[str] | None", sections),
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
                profile=profile,
            )

        return await run_mcp_tool("search_literature", call)

    @mcp.tool(
        name="search_guidelines",
        title="Search Biomedical Guidelines",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_guidelines(
        text: Annotated[
            str,
            Field(
                min_length=1,
                max_length=1000,
                description=(
                    "Free-text research question to find guideline, recommendation, consensus, "
                    "or systematic-review articles for."
                ),
                examples=["asthma treatment adults"],
            ),
        ],
        page: Annotated[
            int,
            Field(ge=1, le=1000, description="1-based page number for paging beyond `limit`."),
        ] = 1,
        year_min: Annotated[
            int | None,
            Field(ge=1800, le=2030, description="Earliest publication year, inclusive."),
        ] = None,
        year_max: Annotated[
            int | None,
            Field(ge=1800, le=2030, description="Latest publication year, inclusive."),
        ] = None,
        sections: Annotated[
            list[SearchSection] | None,
            Field(
                description="Restrict the text match to these article sections (lowercase).",
                examples=[["title", "abstract"]],
            ),
        ] = None,
        limit: Annotated[
            int | None,
            Field(ge=1, le=20, description="Maximum hits to return on this page."),
        ] = 5,
        entity_ids: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Restrict to articles mentioning these PubTator entity IDs (resolve them "
                    "first with search_biomedical_entities)."
                ),
                examples=[["@GENE_BRCA1"]],
            ),
        ] = None,
        coverage: Annotated[
            SearchCoverageMode,
            Field(description="'preflight' (default) or 'none' to skip source-coverage hints."),
        ] = "preflight",
    ) -> dict[str, Any]:
        """Use this when a user needs guideline, recommendation, consensus, or systematic review papers for a biomedical research question. Wraps search_literature with guideline/systematic-review filters and guideline boosting; not an independent guideline database."""

        async def call() -> dict[str, Any]:
            search_text = text
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
                sections=cast("list[str] | None", sections),
                response_mode="standard",
                include_citations="nlm",
                text_hl_format="plain",
                limit=limit,
                entity_ids=entity_ids,
                guideline_boost=True,
                coverage=coverage,
                preflight_service=preflight_service,
                profile=profile,
            )

        return await run_mcp_tool("search_guidelines", call)

    @mcp.tool(
        name="search_biomedical_entities",
        title="Search Biomedical Entities",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_biomedical_entities(
        query: Annotated[
            str,
            Field(
                min_length=1,
                description="Entity name or fragment to resolve, e.g. a gene symbol or disease name.",
                examples=["TP53"],
            ),
        ],
        concept: Annotated[
            Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine", "Phenotype"]
            | None,
            Field(
                description="Restrict autocomplete to one PubTator concept type; omit for all types."
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=100, description="Maximum entity candidates to return."),
        ] = 10,
    ) -> dict[str, Any]:
        """Use this when a user needs canonical PubTator biomedical entity IDs for genes, diseases, chemicals, species, variants, or cell lines."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            return await search_biomedical_entities_impl(
                client=client,
                query=query,
                concept=concept,
                limit=limit,
            )

        return await run_mcp_tool("search_biomedical_entities", call)

    if profile != "lean":

        @mcp.tool(
            name="find_entity_relations",
            title="Find Entity Relations",
            output_schema=None,
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def find_entity_relations(
            entity_id: Annotated[
                str,
                Field(
                    min_length=1,
                    description=(
                        "PubTator entity ID to expand from, e.g. @CHEMICAL_remdesivir "
                        "(resolve names with search_biomedical_entities first)."
                    ),
                    examples=["@CHEMICAL_remdesivir"],
                ),
            ],
            relation_type: Annotated[
                Literal[
                    "treat",
                    "cause",
                    "cotreat",
                    "convert",
                    "compare",
                    "interact",
                    "associate",
                    "positive_correlate",
                    "negative_correlate",
                    "prevent",
                    "inhibit",
                    "stimulate",
                    "drug_interact",
                ]
                | None,
                Field(
                    description=(
                        "Optional relation type to keep, e.g. 'treat', 'cause', 'associate'; "
                        "omit for all relation types."
                    ),
                ),
            ] = None,
            target_entity_type: Annotated[
                Literal[
                    "Gene",
                    "Disease",
                    "Chemical",
                    "Species",
                    "Variant",
                    "CellLine",
                    "Phenotype",
                ]
                | None,
                Field(
                    description=(
                        "Optional target concept type to keep, e.g. 'Disease' or 'Chemical'; "
                        "omit for all target types."
                    ),
                ),
            ] = None,
            limit: Annotated[
                int,
                Field(ge=1, le=100, description="Maximum related entities to return."),
            ] = 20,
            response_mode: Annotated[
                Literal["compact", "standard", "full"],
                Field(description="Payload verbosity: 'compact' (default), 'standard', or 'full'."),
            ] = "compact",
            max_response_chars: Annotated[
                int,
                Field(
                    ge=1000, le=50000, description="Soft character budget for the response body."
                ),
            ] = 12_000,
        ) -> dict[str, Any]:
            """Use this when a user has a PubTator entity ID and needs literature-derived related entities to expand a corpus. Do not use this for canonical entity lookup; use search_biomedical_entities. Next: search_literature."""

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

            return await run_mcp_tool("find_entity_relations", call)

    @mcp.tool(
        name="get_variant_evidence",
        title="Lookup Variant Evidence",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_variant_evidence(
        gene: Annotated[
            str,
            Field(
                min_length=1,
                description="HGNC gene symbol the variant sits in.",
                examples=["BRCA1"],
            ),
        ],
        variant: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "cDNA/HGVS or rsID variant string. Required; use `protein`/`condition` to "
                    "refine."
                ),
                examples=["c.68_69delAG"],
            ),
        ],
        protein: Annotated[
            str | None,
            Field(min_length=1, description="Protein-level change, e.g. p.Glu23fs, if known."),
        ] = None,
        condition: Annotated[
            str | None,
            Field(min_length=1, description="Optional condition/phenotype to scope the evidence."),
        ] = None,
        sources: Annotated[
            list[VariantEvidenceSource] | None,
            Field(
                description="Evidence sources to include; omit for all.",
                examples=[["clinvar", "pubtator"]],
            ),
        ] = None,
        max_literature_pmids: Annotated[
            int,
            Field(ge=0, le=100, description="Maximum supporting literature PMIDs to attach."),
        ] = 20,
        include_citations: Annotated[
            bool,
            Field(description="Attach formatted citations for the supporting PMIDs."),
        ] = True,
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

        return await run_mcp_tool("get_variant_evidence", call)
