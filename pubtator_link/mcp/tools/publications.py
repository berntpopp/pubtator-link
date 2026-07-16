from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import (
    get_citation_graph_service,
    get_publication_metadata_service,
    get_publication_passage_service,
    get_publication_service,
    get_related_evidence_service,
    get_topic_literature_map_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.argument_aliases import merge_pmids
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.meta_budget import strip_meta_for_repeated_call
from pubtator_link.mcp.pmc_annotations import fetch_pmc_annotations_impl
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (
    build_topic_literature_map_impl,
    estimate_publication_context_impl,
    fetch_publication_annotations_impl,
    find_related_evidence_candidates_impl,
    get_publication_citation_graph_impl,
    get_publication_metadata_impl,
    get_publication_passages_impl,
)
from pubtator_link.mcp.tools._vocab import PassageSection, PublicationType
from pubtator_link.models.publication_passages import (
    PublicationPassageMode,
    Verbosity,
)

LiteratureGraphResponseModeArg = Literal["compact", "nodes_edges", "full"]
LiteratureGraphBias = Literal[
    "guideline",
    "cohort",
    "genotype_phenotype",
    "treatment",
    "pediatric",
    "population",
]

# BioC passage section labels get_publication_passages filters on (case-insensitive upstream).
_SECTIONS_FIELD = Field(
    description=(
        "Restrict to these BioC section labels (case-insensitive); omit for all sections. An "
        "article that lacks a requested section simply contributes no passages for it."
    ),
    examples=[["ABSTRACT", "RESULTS"]],
)


def register_publication_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    if profile in ("full", "readonly"):

        @mcp.tool(
            name="get_publication_annotations",
            title="Fetch Publication Annotations",
            output_schema=None,
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def fetch_publication_annotations(
            pmids: Annotated[
                list[str],
                Field(
                    min_length=1,
                    max_length=50,
                    description="PubMed IDs to export raw PubTator BioC annotations for.",
                    examples=[["25741868"]],
                ),
            ],
            format: Annotated[
                Literal["pubtator", "biocxml", "biocjson"],
                Field(
                    description="Export serialization: 'biocjson' (default), 'biocxml', or 'pubtator'."
                ),
            ] = "biocjson",
            full: Annotated[
                bool,
                Field(description="Request full-text annotations where available (else abstract)."),
            ] = False,
        ) -> dict[str, Any]:
            """Use this when a user provides PubMed IDs and needs raw PubTator BioC annotation export. Do not use this for compact grounded answers; use get_publication_passages. Next: get_publication_passages."""

            async def call() -> dict[str, Any]:
                selected_pmids = merge_pmids(pmids, None, max_items=50)
                service = await get_publication_service()
                return await fetch_publication_annotations_impl(
                    service=service,
                    pmids=selected_pmids,
                    format=format,
                    full=full,
                )

            try:
                tool_pmids = merge_pmids(pmids, None, max_items=50)
            except ValueError:
                tool_pmids = None
            return await run_mcp_tool(
                "get_publication_annotations",
                call,
                pmids=tool_pmids,
            )

        @mcp.tool(
            name="build_topic_literature_map",
            title="Build Topic Literature Map",
            output_schema=None,
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def build_topic_literature_map(
            query: Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=1000,
                    description="Topic or research question to build the literature map around.",
                    examples=["familial Mediterranean fever colchicine"],
                ),
            ],
            pmids: Annotated[
                list[str] | None,
                Field(
                    min_length=1,
                    max_length=100,
                    description="Optional seed PMIDs to anchor the map on.",
                    examples=[["31036433"]],
                ),
            ] = None,
            max_seed_papers: Annotated[
                int, Field(ge=1, le=50, description="Maximum seed papers to expand.")
            ] = 10,
            max_neighbors_per_paper: Annotated[
                int, Field(ge=1, le=20, description="Maximum neighbors per seed paper.")
            ] = 5,
            response_mode: Annotated[
                LiteratureGraphResponseModeArg,
                Field(description="Payload shape: 'compact' (default), 'nodes_edges', or 'full'."),
            ] = "compact",
            max_candidates: Annotated[
                int, Field(ge=1, le=50, description="Maximum ranked candidate papers.")
            ] = 8,
            include_demoted: Annotated[
                bool, Field(description="Include demoted (lower-ranked) candidates.")
            ] = True,
            max_demoted: Annotated[
                int, Field(ge=0, le=20, description="Maximum demoted candidates to include.")
            ] = 3,
            bias_toward: Annotated[
                list[LiteratureGraphBias] | None,
                Field(
                    description="Bias ranking toward these evidence flavors.",
                    examples=[["guideline", "treatment"]],
                ),
            ] = None,
            max_graph_nodes: Annotated[
                int, Field(ge=1, le=200, description="Maximum nodes in the returned graph.")
            ] = 30,
            max_graph_edges: Annotated[
                int, Field(ge=1, le=400, description="Maximum edges in the returned graph.")
            ] = 60,
            include_authors: Annotated[
                bool, Field(description="Include author lists on graph nodes.")
            ] = True,
            include_citations: Annotated[
                bool, Field(description="Include citation edges in the graph.")
            ] = True,
            include_pubtator_entities: Annotated[
                bool, Field(description="Attach PubTator entity annotations to nodes.")
            ] = True,
            include_related_candidates: Annotated[
                bool, Field(description="Include related-evidence candidates in the result.")
            ] = True,
            year_min: Annotated[
                int | None,
                Field(ge=1800, le=2030, description="Earliest publication year, inclusive."),
            ] = None,
            year_max: Annotated[
                int | None,
                Field(ge=1800, le=2030, description="Latest publication year, inclusive."),
            ] = None,
            prefer_full_text: Annotated[
                bool, Field(description="Prefer open-access full-text candidates.")
            ] = True,
            timeout_ms: Annotated[
                int, Field(ge=0, le=120_000, description="Overall soft timeout in milliseconds.")
            ] = 45_000,
            partial_ok: Annotated[
                bool, Field(description="Return a partial map if a sub-step times out.")
            ] = True,
            expand_query_seeds: Annotated[
                bool, Field(description="Seed the map from a query search when no PMIDs are given.")
            ] = False,
            citation_graph_timeout_ms: Annotated[
                int | None,
                Field(ge=1, le=120_000, description="Per-step timeout for citation-graph lookups."),
            ] = 15_000,
            related_evidence_timeout_ms: Annotated[
                int | None,
                Field(
                    ge=1, le=120_000, description="Per-step timeout for related-evidence lookups."
                ),
            ] = 20_000,
            metadata_backfill_timeout_ms: Annotated[
                int | None,
                Field(ge=1, le=120_000, description="Per-step timeout for metadata backfill."),
            ] = 10_000,
            include_meta: Annotated[
                bool, Field(description="Include the _meta orientation block.")
            ] = True,
        ) -> dict[str, Any]:
            """Use this when a user needs a bounded topic-level literature map from a topic query, optionally seeded with PMIDs. Returns response_size_class. response_mode='compact' is the MCP default for LLM candidate selection; full can be large and is for explicit debug graph inspection. Next: get_publication_passages."""

            async def call() -> dict[str, Any]:
                selected_query = query
                selected_pmids = merge_pmids(pmids, None, max_items=100) if pmids else None
                service = await get_topic_literature_map_service()
                return await build_topic_literature_map_impl(
                    service=service,
                    query=selected_query,
                    pmids=selected_pmids,
                    max_seed_papers=max_seed_papers,
                    max_neighbors_per_paper=max_neighbors_per_paper,
                    response_mode=response_mode,
                    max_candidates=max_candidates,
                    include_demoted=include_demoted,
                    max_demoted=max_demoted,
                    bias_toward=bias_toward,
                    max_graph_nodes=max_graph_nodes,
                    max_graph_edges=max_graph_edges,
                    include_authors=include_authors,
                    include_citations=include_citations,
                    include_pubtator_entities=include_pubtator_entities,
                    include_related_candidates=include_related_candidates,
                    year_min=year_min,
                    year_max=year_max,
                    prefer_full_text=prefer_full_text,
                    timeout_ms=timeout_ms,
                    partial_ok=partial_ok,
                    expand_query_seeds=expand_query_seeds,
                    citation_graph_timeout_ms=citation_graph_timeout_ms,
                    related_evidence_timeout_ms=related_evidence_timeout_ms,
                    metadata_backfill_timeout_ms=metadata_backfill_timeout_ms,
                    profile=profile,
                )

            try:
                tool_pmids = merge_pmids(pmids, None, max_items=100)
            except ValueError:
                tool_pmids = None
            result = await run_mcp_tool("build_topic_literature_map", call, pmids=tool_pmids)
            return result if include_meta else strip_meta_for_repeated_call(result)

    @mcp.tool(
        name="get_publication_passages",
        title="Get Publication Passages",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_passages(
        pmids: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=25,
                description="PubMed IDs to fetch compact citable passages for.",
                examples=[["25741868"]],
            ),
        ],
        sections: Annotated[list[PassageSection] | None, _SECTIONS_FIELD] = None,
        mode: Annotated[
            PublicationPassageMode,
            Field(
                description=(
                    "Passage selection: 'compact_passages' (default), 'full_abstract' (all "
                    "title/abstract passages), 'abstracts', or 'section_text'."
                ),
            ),
        ] = "compact_passages",
        full: Annotated[
            bool, Field(description="Prefer full-text passages where the article is open-access.")
        ] = False,
        max_passages_per_pmid: Annotated[
            int, Field(ge=1, le=50, description="Maximum passages returned per PMID.")
        ] = 6,
        max_chars: Annotated[
            int, Field(ge=200, le=60_000, description="Soft total character budget for passages.")
        ] = 12000,
        include_tables: Annotated[bool, Field(description="Include table passages.")] = True,
        include_references: Annotated[
            bool, Field(description="Include reference-list passages.")
        ] = False,
        dry_run: Annotated[
            bool, Field(description="Return a size/coverage estimate without passage text.")
        ] = False,
        verbosity: Annotated[
            Verbosity,
            Field(description="Field verbosity: 'lean', 'standard' (default), or 'full'."),
        ] = "standard",
    ) -> dict[str, Any]:
        """Use this when a user needs compact citable publication passages from PMIDs without raw BioC. For article-local answering, use mode='full_abstract' first; it returns all title/abstract passages without truncating structured abstracts. If full=True returns only abstracts, inspect coverage_by_pmid and answer from available evidence. Do not use for prepared review RAG; use get_review_context_batch."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, None, max_items=25)
            service = await get_publication_passage_service()
            return await get_publication_passages_impl(
                service=service,
                pmids=selected_pmids,
                sections=cast("list[str] | None", sections),
                mode=mode,
                full=full,
                max_passages_per_pmid=max_passages_per_pmid,
                max_chars=max_chars,
                include_tables=include_tables,
                include_references=include_references,
                dry_run=dry_run,
                verbosity=verbosity,
            )

        try:
            tool_pmids = merge_pmids(pmids, None, max_items=25)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool("get_publication_passages", call, pmids=tool_pmids)

    @mcp.tool(
        name="get_publication_metadata",
        title="Get Publication Metadata",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_metadata(
        pmids: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=100,
                description="PubMed IDs to fetch citation-grade metadata for.",
                examples=[["25741868"]],
            ),
        ],
        include_mesh: Annotated[bool, Field(description="Include MeSH descriptors.")] = True,
        include_publication_types: Annotated[
            bool, Field(description="Include PubMed publication types.")
        ] = True,
        include_citations: Annotated[
            Literal["none", "nlm", "bibtex", "both"],
            Field(description="Citation rendering: 'none', 'nlm', 'bibtex', or 'both' (default)."),
        ] = "both",
        include_coverage: Annotated[
            bool, Field(description="Include per-PMID source-coverage hints.")
        ] = True,
    ) -> dict[str, Any]:
        """Use this when a user needs citation-grade metadata for known PMIDs. Do not use this for article text or annotations; use get_publication_passages. Next: get_publication_passages."""

        async def call() -> dict[str, Any]:
            selected_pmids = merge_pmids(pmids, None, max_items=100)
            service = await get_publication_metadata_service()
            return await get_publication_metadata_impl(
                service=service,
                pmids=selected_pmids,
                include_mesh=include_mesh,
                include_publication_types=include_publication_types,
                include_citations=include_citations,
                include_coverage=include_coverage,
                profile=profile,
            )

        try:
            tool_pmids = merge_pmids(pmids, None, max_items=100)
        except ValueError:
            tool_pmids = None
        return await run_mcp_tool("get_publication_metadata", call, pmids=tool_pmids)

    @mcp.tool(
        name="get_publication_citation_graph",
        title="Get Publication Citation Graph",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_citation_graph(
        pmid: Annotated[
            str,
            Field(
                min_length=1,
                description="PubMed ID of the publication whose citation neighbors are wanted.",
                examples=["40562663"],
            ),
        ],
        direction: Annotated[
            Literal["references", "cited_by", "both"],
            Field(description="Which neighbors: 'references', 'cited_by', or 'both' (default)."),
        ] = "both",
        response_mode: Annotated[
            LiteratureGraphResponseModeArg,
            Field(description="Payload shape: 'compact' (default), 'nodes_edges', or 'full'."),
        ] = "compact",
        resolve_metadata: Annotated[
            bool, Field(description="Resolve title/author metadata for neighbor PMIDs.")
        ] = True,
        resolve_reference_pmids: Annotated[
            bool, Field(description="Resolve DOIs in the reference list back to PMIDs.")
        ] = True,
        max_reference_resolution: Annotated[
            int, Field(ge=0, le=100, description="Maximum reference DOIs to resolve.")
        ] = 20,
        include_provider_status: Annotated[
            bool, Field(description="Include per-provider availability status.")
        ] = True,
        include_open_access_status: Annotated[
            bool, Field(description="Include open-access status per neighbor.")
        ] = True,
        max_results: Annotated[
            int, Field(ge=1, le=100, description="Maximum neighbor publications to return.")
        ] = 50,
    ) -> dict[str, Any]:
        """Use this when a user needs reference or cited-by neighbors for one publication. Returns response_size_class. response_mode='compact' is the MCP default for LLM candidate selection; full can be large and is for explicit debug graph inspection. Next: get_publication_passages."""

        async def call() -> dict[str, Any]:
            service = await get_citation_graph_service()
            return await get_publication_citation_graph_impl(
                service=service,
                pmid=pmid,
                direction=direction,
                response_mode=response_mode,
                resolve_metadata=resolve_metadata,
                resolve_reference_pmids=resolve_reference_pmids,
                max_reference_resolution=max_reference_resolution,
                include_provider_status=include_provider_status,
                include_open_access_status=include_open_access_status,
                max_results=max_results,
                profile=profile,
            )

        return await run_mcp_tool(
            "get_publication_citation_graph",
            call,
            pmids=[pmid] if pmid else None,
        )

    @mcp.tool(
        name="find_related_evidence_candidates",
        title="Find Related Evidence Candidates",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_related_evidence_candidates(
        pmid: Annotated[
            str,
            Field(
                min_length=1,
                description="Seed PubMed ID to find related evidence candidates for.",
                examples=["40562663"],
            ),
        ],
        max_results: Annotated[
            int, Field(ge=1, le=100, description="Maximum candidate publications to return.")
        ] = 12,
        response_mode: Annotated[
            LiteratureGraphResponseModeArg,
            Field(description="Payload shape: 'compact' (default), 'nodes_edges', or 'full'."),
        ] = "compact",
        prefer_full_text: Annotated[
            bool, Field(description="Prefer open-access full-text candidates.")
        ] = True,
        include_pubtator_search: Annotated[
            bool, Field(description="Include PubTator entity-search neighbors.")
        ] = True,
        include_citation_neighbors: Annotated[
            bool, Field(description="Include citation-graph neighbors.")
        ] = False,
        publication_types: Annotated[
            list[PublicationType] | None,
            Field(
                description="Restrict candidates to these PubMed publication types.",
                examples=[["Review"]],
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
        citation_graph_timeout_ms: Annotated[
            int, Field(ge=1, le=120_000, description="Per-step timeout for citation-graph lookups.")
        ] = 15_000,
        metadata_timeout_ms: Annotated[
            int, Field(ge=1, le=120_000, description="Per-step timeout for metadata resolution.")
        ] = 20_000,
        include_meta: Annotated[
            bool, Field(description="Include the _meta orientation block.")
        ] = True,
    ) -> dict[str, Any]:
        """Use this when a user has one PMID and needs related full-text-preferred candidates. Returns response_size_class. response_mode='compact' is the MCP default for LLM candidate selection; full can be large and is for explicit debug graph inspection. Next: get_publication_passages."""

        async def call() -> dict[str, Any]:
            service = await get_related_evidence_service()
            return await find_related_evidence_candidates_impl(
                service=service,
                pmid=pmid,
                max_results=max_results,
                response_mode=response_mode,
                prefer_full_text=prefer_full_text,
                include_pubtator_search=include_pubtator_search,
                include_citation_neighbors=include_citation_neighbors,
                publication_types=cast("list[str] | None", publication_types),
                year_min=year_min,
                year_max=year_max,
                citation_graph_timeout_ms=citation_graph_timeout_ms,
                metadata_timeout_ms=metadata_timeout_ms,
                profile=profile,
            )

        result = await run_mcp_tool(
            "find_related_evidence_candidates",
            call,
            pmids=[pmid],
        )
        return result if include_meta else strip_meta_for_repeated_call(result)

    if profile != "lean":

        @mcp.tool(
            name="estimate_publication_context",
            title="Estimate Publication Context",
            output_schema=None,
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def estimate_publication_context(
            pmids: Annotated[
                list[str],
                Field(
                    min_length=1,
                    max_length=25,
                    description="PubMed IDs to estimate passage count and context size for.",
                    examples=[["25741868"]],
                ),
            ],
            sections: Annotated[list[PassageSection] | None, _SECTIONS_FIELD] = None,
            mode: Annotated[
                PublicationPassageMode,
                Field(
                    description=(
                        "Passage selection to estimate under: 'compact_passages' (default), "
                        "'full_abstract', 'abstracts', or 'section_text'."
                    ),
                ),
            ] = "compact_passages",
            full: Annotated[
                bool, Field(description="Estimate under full-text retrieval where available.")
            ] = False,
            max_passages_per_pmid: Annotated[
                int, Field(ge=1, le=30, description="Maximum passages per PMID to assume.")
            ] = 6,
            include_tables: Annotated[
                bool, Field(description="Count table passages in the estimate.")
            ] = True,
            include_references: Annotated[
                bool, Field(description="Count reference-list passages in the estimate.")
            ] = False,
        ) -> dict[str, Any]:
            """Use this when a user needs to estimate passage count and context size before fetching publication passages. Do not use this for text retrieval; use get_publication_passages. Next: get_publication_passages."""

            async def call() -> dict[str, Any]:
                selected_pmids = merge_pmids(pmids, None, max_items=25)
                service = await get_publication_passage_service()
                return await estimate_publication_context_impl(
                    service=service,
                    pmids=selected_pmids,
                    sections=cast("list[str] | None", sections),
                    mode=mode,
                    full=full,
                    max_passages_per_pmid=max_passages_per_pmid,
                    include_tables=include_tables,
                    include_references=include_references,
                )

            try:
                tool_pmids = merge_pmids(pmids, None, max_items=25)
            except ValueError:
                tool_pmids = None
            return await run_mcp_tool(
                "estimate_publication_context",
                call,
                pmids=tool_pmids,
            )

        if profile in ("full", "readonly"):

            @mcp.tool(
                name="get_pmc_annotations",
                title="Fetch PMC Annotations",
                output_schema=None,
                annotations=READ_ONLY_OPEN_WORLD,
            )
            async def fetch_pmc_annotations(
                pmcids: Annotated[
                    list[str],
                    Field(
                        min_length=1,
                        max_length=50,
                        description="PMC IDs to export raw PubTator full-text BioC annotations for.",
                        examples=[["PMC5334499"]],
                    ),
                ],
                format: Annotated[
                    Literal["biocxml", "biocjson"],
                    Field(description="Export serialization: 'biocjson' (default) or 'biocxml'."),
                ] = "biocjson",
            ) -> dict[str, Any]:
                """Use this when a user provides PMC IDs and needs raw PubTator full-text BioC annotation export. Do not use this for compact grounded answers; use get_publication_passages. Next: get_publication_passages."""

                async def call() -> dict[str, Any]:
                    service = await get_publication_service()
                    return await fetch_pmc_annotations_impl(
                        service=service,
                        pmcids=pmcids,
                        format=format,
                    )

                return await run_mcp_tool("get_pmc_annotations", call)
