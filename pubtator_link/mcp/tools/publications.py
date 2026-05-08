from __future__ import annotations

from typing import Annotated, Any, Literal

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
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (
    build_topic_literature_map_impl,
    estimate_publication_context_impl,
    fetch_pmc_annotations_impl,
    fetch_publication_annotations_impl,
    find_related_evidence_candidates_impl,
    get_publication_citation_graph_impl,
    get_publication_metadata_impl,
    get_publication_passages_impl,
)
from pubtator_link.models.literature_graph import (
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidatesResponse,
    TopicLiteratureMapResponse,
)
from pubtator_link.models.publication_metadata import PublicationMetadataResponse
from pubtator_link.models.publication_passages import (
    PublicationContextEstimateResponse,
    PublicationPassageMode,
    PublicationPassageResponse,
    Verbosity,
)
from pubtator_link.models.responses import PublicationExportResponse

LiteratureGraphResponseModeArg = Literal["compact", "nodes_edges", "full"]
LiteratureGraphBias = Literal[
    "guideline",
    "cohort",
    "genotype_phenotype",
    "treatment",
    "pediatric",
    "population",
]


def register_publication_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    if profile == "full":

        @mcp.tool(
            name="pubtator.fetch_publication_annotations",
            title="Fetch Publication Annotations",
            output_schema=PublicationExportResponse.model_json_schema(),
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def fetch_publication_annotations(
            pmids: Annotated[list[str], Field(min_length=1, max_length=50)],
            format: Literal["pubtator", "biocxml", "biocjson"] = "biocjson",
            full: bool = False,
        ) -> dict[str, Any]:
            """Use this when a user provides PubMed IDs and needs raw PubTator BioC annotation export. Do not use this for compact grounded answers; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages."""

            async def call() -> dict[str, Any]:
                service = await get_publication_service()
                return await fetch_publication_annotations_impl(
                    service=service,
                    pmids=pmids,
                    format=format,
                    full=full,
                )

            return await run_mcp_tool("pubtator.fetch_publication_annotations", call, pmids=pmids)

        @mcp.tool(
            name="pubtator.build_topic_literature_map",
            title="Build Topic Literature Map",
            output_schema=TopicLiteratureMapResponse.model_json_schema(),
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def build_topic_literature_map(
            query: Annotated[str | None, Field(min_length=1, max_length=1000)] = None,
            pmids: Annotated[list[str] | None, Field(min_length=1, max_length=100)] = None,
            max_seed_papers: Annotated[int, Field(ge=1, le=50)] = 25,
            max_neighbors_per_paper: Annotated[int, Field(ge=1, le=20)] = 10,
            response_mode: LiteratureGraphResponseModeArg = "compact",
            max_candidates: Annotated[int, Field(ge=1, le=50)] = 12,
            include_demoted: bool = True,
            max_demoted: Annotated[int, Field(ge=0, le=20)] = 3,
            bias_toward: list[LiteratureGraphBias] | None = None,
            max_graph_nodes: Annotated[int, Field(ge=1, le=200)] = 30,
            max_graph_edges: Annotated[int, Field(ge=1, le=400)] = 60,
            include_authors: bool = True,
            include_citations: bool = True,
            include_pubtator_entities: bool = True,
            include_related_candidates: bool = True,
            year_min: int | None = None,
            year_max: int | None = None,
            prefer_full_text: bool = True,
            timeout_ms: Annotated[int, Field(ge=0, le=120_000)] = 25_000,
            partial_ok: bool = True,
            citation_graph_timeout_ms: Annotated[int | None, Field(ge=1, le=120_000)] = None,
            related_evidence_timeout_ms: Annotated[int | None, Field(ge=1, le=120_000)] = None,
            metadata_backfill_timeout_ms: Annotated[int | None, Field(ge=1, le=120_000)] = None,
        ) -> dict[str, Any]:
            """Use this when a user needs a bounded topic-level literature map from a query or seed PMIDs. Returns response_size_class. response_mode='compact' is the MCP default for LLM candidate selection; full can be large and is for explicit debug graph inspection. Next: pubtator.get_publication_passages."""

            async def call() -> dict[str, Any]:
                service = await get_topic_literature_map_service()
                return await build_topic_literature_map_impl(
                    service=service,
                    query=query,
                    pmids=pmids,
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
                    citation_graph_timeout_ms=citation_graph_timeout_ms,
                    related_evidence_timeout_ms=related_evidence_timeout_ms,
                    metadata_backfill_timeout_ms=metadata_backfill_timeout_ms,
                )

            return await run_mcp_tool(
                "pubtator.build_topic_literature_map",
                call,
                pmids=pmids,
            )

    @mcp.tool(
        name="pubtator.get_publication_passages",
        title="Get Publication Passages",
        output_schema=PublicationPassageResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_passages(
        pmids: list[str],
        sections: list[str] | None = None,
        mode: PublicationPassageMode = "compact_passages",
        full: bool = False,
        max_passages_per_pmid: int = 6,
        max_chars: int = 12000,
        include_tables: bool = True,
        include_references: bool = False,
        dry_run: bool = False,
        verbosity: Verbosity = "standard",
    ) -> dict[str, Any]:
        """Use this when a user needs compact citable publication passages from PMIDs without raw BioC. Do not use this for prepared review RAG; use pubtator.retrieve_review_context_batch. Next: pubtator.retrieve_review_context_batch."""

        async def call() -> dict[str, Any]:
            service = await get_publication_passage_service()
            return await get_publication_passages_impl(
                service=service,
                pmids=pmids,
                sections=sections,
                mode=mode,
                full=full,
                max_passages_per_pmid=max_passages_per_pmid,
                max_chars=max_chars,
                include_tables=include_tables,
                include_references=include_references,
                dry_run=dry_run,
                verbosity=verbosity,
            )

        return await run_mcp_tool("pubtator.get_publication_passages", call, pmids=pmids)

    @mcp.tool(
        name="pubtator.get_publication_metadata",
        title="Get Publication Metadata",
        output_schema=PublicationMetadataResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_metadata(
        pmids: Annotated[list[str], Field(min_length=1, max_length=100)],
        include_mesh: bool = True,
        include_publication_types: bool = True,
        include_citations: Literal["none", "nlm", "bibtex", "both"] = "both",
        include_coverage: bool = True,
    ) -> dict[str, Any]:
        """Use this when a user needs citation-grade metadata for known PMIDs. Do not use this for article text or annotations; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages."""

        async def call() -> dict[str, Any]:
            service = await get_publication_metadata_service()
            return await get_publication_metadata_impl(
                service=service,
                pmids=pmids,
                include_mesh=include_mesh,
                include_publication_types=include_publication_types,
                include_citations=include_citations,
                include_coverage=include_coverage,
            )

        return await run_mcp_tool("pubtator.get_publication_metadata", call, pmids=pmids)

    @mcp.tool(
        name="pubtator.get_publication_citation_graph",
        title="Get Publication Citation Graph",
        output_schema=PublicationCitationGraphResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_citation_graph(
        pmid: str | None = None,
        doi: str | None = None,
        query: Annotated[str | None, Field(min_length=1, max_length=1000)] = None,
        direction: Literal["references", "cited_by", "both"] = "both",
        response_mode: LiteratureGraphResponseModeArg = "compact",
        resolve_metadata: bool = True,
        resolve_reference_pmids: bool = True,
        max_reference_resolution: Annotated[int, Field(ge=0, le=100)] = 20,
        include_provider_status: bool = True,
        include_open_access_status: bool = True,
        max_results: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        """Use this when a user needs reference or cited-by neighbors for one publication. Returns response_size_class. response_mode='compact' is the MCP default for LLM candidate selection; full can be large and is for explicit debug graph inspection. Next: pubtator.get_publication_passages."""

        async def call() -> dict[str, Any]:
            service = await get_citation_graph_service()
            return await get_publication_citation_graph_impl(
                service=service,
                pmid=pmid,
                doi=doi,
                query=query,
                direction=direction,
                response_mode=response_mode,
                resolve_metadata=resolve_metadata,
                resolve_reference_pmids=resolve_reference_pmids,
                max_reference_resolution=max_reference_resolution,
                include_provider_status=include_provider_status,
                include_open_access_status=include_open_access_status,
                max_results=max_results,
            )

        return await run_mcp_tool(
            "pubtator.get_publication_citation_graph",
            call,
            pmids=[pmid] if pmid else None,
        )

    @mcp.tool(
        name="pubtator.find_related_evidence_candidates",
        title="Find Related Evidence Candidates",
        output_schema=RelatedEvidenceCandidatesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_related_evidence_candidates(
        pmid: str,
        max_results: Annotated[int, Field(ge=1, le=100)] = 25,
        response_mode: LiteratureGraphResponseModeArg = "compact",
        prefer_full_text: bool = True,
        include_pubtator_search: bool = True,
        include_citation_neighbors: bool = True,
        publication_types: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> dict[str, Any]:
        """Use this when a user has one PMID and needs related full-text-preferred candidates. Returns response_size_class. response_mode='compact' is the MCP default for LLM candidate selection; full can be large and is for explicit debug graph inspection. Next: pubtator.get_publication_passages."""

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
                publication_types=publication_types,
                year_min=year_min,
                year_max=year_max,
            )

        return await run_mcp_tool(
            "pubtator.find_related_evidence_candidates",
            call,
            pmids=[pmid],
        )

    if profile != "lean":

        @mcp.tool(
            name="pubtator.estimate_publication_context",
            title="Estimate Publication Context",
            output_schema=PublicationContextEstimateResponse.model_json_schema(),
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def estimate_publication_context(
            pmids: Annotated[list[str], Field(min_length=1, max_length=25)],
            sections: list[str] | None = None,
            mode: PublicationPassageMode = "compact_passages",
            full: bool = False,
            max_passages_per_pmid: Annotated[int, Field(ge=1, le=30)] = 6,
            include_tables: bool = True,
            include_references: bool = False,
        ) -> dict[str, Any]:
            """Use this when a user needs to estimate passage count and context size before fetching publication passages. Do not use this for text retrieval; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages."""

            async def call() -> dict[str, Any]:
                service = await get_publication_passage_service()
                return await estimate_publication_context_impl(
                    service=service,
                    pmids=pmids,
                    sections=sections,
                    mode=mode,
                    full=full,
                    max_passages_per_pmid=max_passages_per_pmid,
                    include_tables=include_tables,
                    include_references=include_references,
                )

            return await run_mcp_tool("pubtator.estimate_publication_context", call, pmids=pmids)

        if profile == "full":

            @mcp.tool(
                name="pubtator.fetch_pmc_annotations",
                title="Fetch PMC Annotations",
                output_schema=PublicationExportResponse.model_json_schema(),
                annotations=READ_ONLY_OPEN_WORLD,
            )
            async def fetch_pmc_annotations(
                pmcids: Annotated[list[str], Field(min_length=1, max_length=50)],
                format: Literal["biocxml", "biocjson"] = "biocjson",
            ) -> dict[str, Any]:
                """Use this when a user provides PMC IDs and needs raw PubTator full-text BioC annotation export. Do not use this for compact grounded answers; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages."""

                async def call() -> dict[str, Any]:
                    service = await get_publication_service()
                    return await fetch_pmc_annotations_impl(
                        service=service,
                        pmcids=pmcids,
                        format=format,
                    )

                return await run_mcp_tool("pubtator.fetch_pmc_annotations", call)
