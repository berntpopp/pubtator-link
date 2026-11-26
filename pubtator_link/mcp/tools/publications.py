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
from pubtator_link.mcp.argument_aliases import merge_pmids, resolve_pmids, with_resolved_from
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.mcp.meta_budget import strip_meta_for_repeated_call
from pubtator_link.mcp.pmc_annotations import fetch_pmc_annotations_impl
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (
    compute_publication_context_impl,
    fetch_publication_annotations_impl,
    find_related_evidence_candidates_impl,
    generate_topic_literature_map_impl,
    get_publication_citation_graph_impl,
    get_publication_metadata_impl,
    get_publication_passages_impl,
)
from pubtator_link.mcp.tools._vocab import ArticleId, PassageSection, PublicationType
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
        "BioC section labels to keep (case-insensitive); omit for all. A table usually yields a caption and a body passage."
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
                list[ArticleId],
                Field(
                    min_length=1,
                    max_length=50,
                    description="PMIDs (or PMCIDs/DOIs, converted) to export.",
                    examples=[["25741868"]],
                ),
            ],
            format: Annotated[
                Literal["pubtator", "biocxml", "biocjson"],
                Field(description="Export format."),
            ] = "biocjson",
            full: Annotated[
                bool,
                Field(description="Full-text annotations where available (else abstract)."),
            ] = False,
        ) -> dict[str, Any]:
            """Use this when a user needs raw PubTator BioC annotations for PMIDs; returns BioC documents with passages and entity annotations. For grounded answers use get_publication_passages. Next: get_publication_passages."""

            async def call() -> dict[str, Any]:
                if full and format == "pubtator":  # PubTator3 ignores full for this format
                    raise InputNormalizationError(
                        field_errors=[{"field": "full", "reason": "needs biocjson or biocxml"}],
                        recovery_hint="Use format='biocjson' or 'biocxml' with full=true.",
                    )
                selected_pmids, resolved_from = await resolve_pmids(pmids, max_items=50)
                service = await get_publication_service()
                result = await fetch_publication_annotations_impl(
                    service=service,
                    pmids=selected_pmids,
                    format=format,
                    full=full,
                )
                return with_resolved_from(result, resolved_from)

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
            name="generate_topic_literature_map",
            title="Build Topic Literature Map",
            output_schema=None,
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def generate_topic_literature_map(
            query: Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=1000,
                    description="Topic or research question to map.",
                    examples=["familial Mediterranean fever colchicine"],
                ),
            ],
            pmids: Annotated[
                list[ArticleId] | None,
                Field(
                    min_length=1,
                    max_length=100,
                    description="Seed PMIDs (or PMCIDs/DOIs, converted) to anchor the map.",
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
                Field(description="Payload shape."),
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
                bool, Field(description="Seed from a query search when no PMIDs are given.")
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
            include_meta: Annotated[bool, Field(description="Include the _meta block.")] = True,
        ) -> dict[str, Any]:
            """Use this when a user needs a bounded literature map for a topic, optionally seeded with PMIDs; returns candidate PMID lanes with bounded summaries and response_size_class. response_mode='compact' (default) suits candidate selection; full can be large (debug). Next: get_publication_passages."""

            async def call() -> dict[str, Any]:
                selected_query = query
                selected_pmids, resolved_from = (
                    await resolve_pmids(pmids, max_items=100) if pmids else (None, None)
                )
                service = await get_topic_literature_map_service()
                result = await generate_topic_literature_map_impl(
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
                return with_resolved_from(result, resolved_from)

            try:
                tool_pmids = merge_pmids(pmids, None, max_items=100)
            except ValueError:
                tool_pmids = None
            result = await run_mcp_tool("generate_topic_literature_map", call, pmids=tool_pmids)
            return result if include_meta else strip_meta_for_repeated_call(result)

    @mcp.tool(
        name="get_publication_passages",
        title="Get Publication Passages",
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_passages(
        pmids: Annotated[
            list[ArticleId],
            Field(
                min_length=1,
                max_length=25,
                description="PMIDs (or PMCIDs/DOIs, converted) to fetch passages for.",
                examples=[["25741868"]],
            ),
        ],
        sections: Annotated[list[PassageSection] | None, _SECTIONS_FIELD] = None,
        mode: Annotated[
            PublicationPassageMode,
            Field(
                description=(
                    "Passage selection; 'full_abstract' returns all title/abstract passages."
                ),
            ),
        ] = "compact_passages",
        full: Annotated[bool, Field(description="Prefer open-access full-text passages.")] = False,
        max_passages_per_pmid: Annotated[
            int, Field(ge=1, le=30, description="Max passages per PMID (or PMID+section).")
        ] = 6,
        max_chars: Annotated[
            int, Field(ge=1000, le=50_000, description="Soft total character budget for passages.")
        ] = 12000,
        include_tables: Annotated[bool, Field(description="Include table passages.")] = True,
        include_references: Annotated[
            bool, Field(description="Include reference-list passages.")
        ] = False,
        dry_run: Annotated[
            bool, Field(description="Size/coverage estimate only, no passage text.")
        ] = False,
        verbosity: Annotated[
            Verbosity,
            Field(description="Field verbosity; 'full' lists each dropped row."),
        ] = "standard",
    ) -> dict[str, Any]:
        """Use this when a user needs article text by PMID; returns citable passages (title, abstract and, for open-access PMC articles, full text incl. figure captions and tables), not raw BioC. For article-local answers use mode='full_abstract' first (untruncated); sections (FIG, TABLE, RESULTS, ...) select full text; check coverage_by_pmid. For prepared reviews use get_review_context_batch."""

        async def call() -> dict[str, Any]:
            selected_pmids, resolved_from = await resolve_pmids(pmids, max_items=25)
            service = await get_publication_passage_service()
            result = await get_publication_passages_impl(
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
            return with_resolved_from(result, resolved_from)

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
            list[ArticleId],
            Field(
                min_length=1,
                max_length=100,
                description="PMIDs (or PMCIDs/DOIs, converted).",
                examples=[["25741868"]],
            ),
        ],
        include_mesh: Annotated[bool, Field(description="Include MeSH descriptors.")] = True,
        include_publication_types: Annotated[
            bool, Field(description="Include PubMed publication types.")
        ] = True,
        include_citations: Annotated[
            Literal["none", "nlm", "bibtex", "both"],
            Field(description="Citation format."),
        ] = "both",
        include_coverage: Annotated[
            bool, Field(description="Include per-PMID source-coverage hints.")
        ] = True,
    ) -> dict[str, Any]:
        """Use this when a user needs citation metadata for known PMIDs; returns title, authors, journal, year, DOI and formatted citations. For text use get_publication_passages. Next: get_publication_passages."""

        async def call() -> dict[str, Any]:
            selected_pmids, resolved_from = await resolve_pmids(pmids, max_items=100)
            service = await get_publication_metadata_service()
            result = await get_publication_metadata_impl(
                service=service,
                pmids=selected_pmids,
                include_mesh=include_mesh,
                include_publication_types=include_publication_types,
                include_citations=include_citations,
                include_coverage=include_coverage,
                profile=profile,
            )
            return with_resolved_from(result, resolved_from)

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
            ArticleId,
            Field(
                min_length=1,
                description="PMID (or PMCID/DOI, converted) to get citation neighbors for.",
                examples=["40562663"],
            ),
        ],
        direction: Annotated[
            Literal["references", "cited_by", "both"],
            Field(description="Neighbors to return."),
        ] = "both",
        response_mode: Annotated[
            LiteratureGraphResponseModeArg,
            Field(description="Payload shape."),
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
        """Use this when a user needs reference or cited-by neighbors of one publication; returns their PMIDs with bounded summaries and response_size_class. response_mode='compact' (default) suits candidate selection; full can be large (debug). Next: get_publication_passages."""

        async def call() -> dict[str, Any]:
            selected_pmids, resolved_from = await resolve_pmids(None, pmid)
            service = await get_citation_graph_service()
            result = await get_publication_citation_graph_impl(
                service=service,
                pmid=selected_pmids[0],
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
            return with_resolved_from(result, resolved_from)

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
            ArticleId,
            Field(
                min_length=1,
                description="Seed PMID (or PMCID/DOI, converted).",
                examples=["40562663"],
            ),
        ],
        max_results: Annotated[
            int, Field(ge=1, le=100, description="Maximum candidate publications to return.")
        ] = 12,
        response_mode: Annotated[
            LiteratureGraphResponseModeArg,
            Field(description="Payload shape."),
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
                description="PubMed publication types to keep.",
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
        include_meta: Annotated[bool, Field(description="Include the _meta block.")] = True,
    ) -> dict[str, Any]:
        """Use this when a user has one PMID and needs related candidates, full text preferred; returns candidate PMIDs with bounded summaries and response_size_class. response_mode='compact' (default) suits candidate selection; full can be large (debug). Next: get_publication_passages."""

        async def call() -> dict[str, Any]:
            selected_pmids, resolved_from = await resolve_pmids(None, pmid)
            service = await get_related_evidence_service()
            result = await find_related_evidence_candidates_impl(
                service=service,
                pmid=selected_pmids[0],
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
            return with_resolved_from(result, resolved_from)

        result = await run_mcp_tool(
            "find_related_evidence_candidates",
            call,
            pmids=[pmid],
        )
        return result if include_meta else strip_meta_for_repeated_call(result)

    if profile != "lean":

        @mcp.tool(
            name="compute_publication_context",
            title="Estimate Publication Context",
            output_schema=None,
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def compute_publication_context(
            pmids: Annotated[
                list[ArticleId],
                Field(
                    min_length=1,
                    max_length=25,
                    description="PMIDs (or PMCIDs/DOIs, converted) to estimate.",
                    examples=[["25741868"]],
                ),
            ],
            sections: Annotated[list[PassageSection] | None, _SECTIONS_FIELD] = None,
            mode: Annotated[
                PublicationPassageMode,
                Field(
                    description=("Passage selection to estimate under."),
                ),
            ] = "compact_passages",
            full: Annotated[bool, Field(description="Estimate under full-text retrieval.")] = False,
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
            """Use this when a user needs passage-count and size estimates before fetching passages; returns estimated passage and character counts plus a recommended mode. Next: get_publication_passages."""

            async def call() -> dict[str, Any]:
                selected_pmids, resolved_from = await resolve_pmids(pmids, max_items=25)
                service = await get_publication_passage_service()
                result = await compute_publication_context_impl(
                    service=service,
                    pmids=selected_pmids,
                    sections=cast("list[str] | None", sections),
                    mode=mode,
                    full=full,
                    max_passages_per_pmid=max_passages_per_pmid,
                    include_tables=include_tables,
                    include_references=include_references,
                )
                return with_resolved_from(result, resolved_from)

            try:
                tool_pmids = merge_pmids(pmids, None, max_items=25)
            except ValueError:
                tool_pmids = None
            return await run_mcp_tool(
                "compute_publication_context",
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
                        description="PMC IDs to export.",
                        examples=[["PMC5334499"]],
                    ),
                ],
                format: Annotated[
                    Literal["biocxml", "biocjson"],
                    Field(description="Export format."),
                ] = "biocjson",
            ) -> dict[str, Any]:
                """Use this when a user needs raw PubTator full-text BioC annotations for PMC IDs; returns BioC documents with passages and entity annotations. For grounded answers use get_publication_passages. Next: get_publication_passages."""

                async def call() -> dict[str, Any]:
                    service = await get_publication_service()
                    return await fetch_pmc_annotations_impl(
                        service=service,
                        pmcids=pmcids,
                        format=format,
                    )

                return await run_mcp_tool("get_pmc_annotations", call)
