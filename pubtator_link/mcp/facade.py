from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal, cast

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.routes.dependencies import (
    get_publication_passage_service,
    get_review_context_service,
    get_review_queue,
)
from pubtator_link.mcp.prompts import (
    annotate_research_text_prompt,
    review_pubtator_annotations_prompt,
    review_rerag_workflow_prompt,
    search_biomedical_literature_prompt,
)
from pubtator_link.mcp.resources import (
    RESEARCH_USE_NOTICE,
    get_bioconcepts_resource,
    get_capabilities_resource,
    get_formats_resource,
    get_relation_types_resource,
    get_research_use_resource,
    get_text_processing_resource,
)
from pubtator_link.mcp.service_adapters import (
    estimate_publication_context_impl,
    fetch_pmc_annotations_impl,
    fetch_publication_annotations_impl,
    find_entity_relations_impl,
    get_publication_passages_impl,
    get_text_annotation_results_impl,
    index_review_evidence_impl,
    inspect_review_index_impl,
    retrieve_review_context_batch_impl,
    retrieve_review_context_impl,
    search_biomedical_entities_impl,
    search_literature_impl,
    submit_text_annotation_impl,
)
from pubtator_link.mcp.tools import (
    EstimatePublicationContextMcpRequest,
    FetchPmcAnnotationsRequest,
    FetchPublicationAnnotationsRequest,
    FindEntityRelationsRequest,
    GetTextAnnotationResultsRequest,
    IndexReviewEvidenceMcpRequest,
    SubmitTextAnnotationRequest,
)
from pubtator_link.models.publication_passages import PublicationPassageMode
from pubtator_link.models.review_rerag import ReviewBatchResponseMode, ReviewTableMode
from pubtator_link.services.publication_service import PublicationService

READ_ONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

READ_ONLY_CLOSED_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

REMOTE_JOB_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

REVIEW_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def _install_inspection_managers(mcp: FastMCP) -> None:
    provider = cast(Any, mcp.providers[0])
    components = provider._components
    tools = {
        component.name: component
        for key, component in components.items()
        if key.startswith("tool:")
    }
    resources = {
        str(component.uri): component
        for key, component in components.items()
        if key.startswith("resource:")
    }
    prompts = {
        component.name: component
        for key, component in components.items()
        if key.startswith("prompt:")
    }

    inspectable_mcp = cast(Any, mcp)
    inspectable_mcp._tool_manager = SimpleNamespace(_tools=tools)
    inspectable_mcp._resource_manager = SimpleNamespace(_resources=resources)
    inspectable_mcp._prompt_manager = SimpleNamespace(_prompts=prompts)


def create_pubtator_mcp() -> FastMCP:
    mcp = FastMCP(
        name="pubtator-link",
        instructions=(
            "PubTator-Link grounds biomedical literature work: search PubMed/PubTator, "
            "fetch compact passages or raw BioC, inspect review indexes, retrieve "
            "review-scoped RAG context, find entity relations, and submit/get text annotations. "
            "If tools are deferred, search for pubtator tools or call "
            "pubtator.get_server_capabilities. For grounded answers use "
            "search -> index -> inspect -> retrieve. Prefer compact passage tools before "
            "raw export because raw full BioC can be large. If retrieval returns zero "
            "passages, inspect the review index and retry shorter keyword queries or PMID "
            f"filters. {RESEARCH_USE_NOTICE}"
        ),
    )

    @mcp.tool(
        name="pubtator.get_server_capabilities",
        title="Get PubTator-Link Capabilities",
        annotations=READ_ONLY_CLOSED_WORLD,
    )
    def get_server_capabilities() -> dict[str, Any]:
        """Use this when a client needs supported tools, transports, formats, and limitations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        return get_capabilities_resource()

    @mcp.tool(
        name="pubtator.search_literature",
        title="Search Biomedical Literature",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_literature(
        text: str,
        page: int = 1,
        sort: str | None = None,
        filters: str | None = None,
        sections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Use this when a user needs PubMed literature search through PubTator3. Use short biomedical queries, optional sort such as 'score desc' or 'date desc', and optional section filters. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await search_literature_impl(
                client=client,
                text=text,
                page=page,
                sort=sort,
                filters=filters,
                sections=sections,
            )

    @mcp.tool(
        name="pubtator.fetch_publication_annotations",
        title="Fetch Publication Annotations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def fetch_publication_annotations(
        request: FetchPublicationAnnotationsRequest,
    ) -> dict[str, Any]:
        """Use this when a user provides PubMed IDs and needs raw PubTator BioC/annotation export; prefer compact passage or review context tools for grounded answers because full BioC can be large. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            service = PublicationService(client=client)
            return await fetch_publication_annotations_impl(request, service=service)

    @mcp.tool(
        name="pubtator.get_publication_passages",
        title="Get Publication Passages",
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
    ) -> dict[str, Any]:
        """Use this when a user needs compact citable publication passages from PMIDs without raw BioC. Prefer this over raw annotation export for routine grounding. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
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
        )

    @mcp.tool(
        name="pubtator.estimate_publication_context",
        title="Estimate Publication Context",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def estimate_publication_context(
        request: EstimatePublicationContextMcpRequest,
    ) -> dict[str, Any]:
        """Use this when a user needs to estimate passage count and context size before fetching publication passages. Inputs mirror get_publication_passages except max_chars; output includes estimated_passages, estimated_chars, sections_by_pmid, recommended_mode, and warning. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_publication_passage_service()
        return await estimate_publication_context_impl(request, service=service)

    @mcp.tool(
        name="pubtator.fetch_pmc_annotations",
        title="Fetch PMC Annotations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def fetch_pmc_annotations(request: FetchPmcAnnotationsRequest) -> dict[str, Any]:
        """Use this when a user provides PMC IDs and needs raw PubTator full-text BioC/annotation export; prefer compact passage or review context tools for focused grounding because full text can be large. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            service = PublicationService(client=client)
            return await fetch_pmc_annotations_impl(request, service=service)

    @mcp.tool(
        name="pubtator.search_biomedical_entities",
        title="Search Biomedical Entities",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_biomedical_entities(
        query: str,
        concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"]
        | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Use this when a user needs canonical PubTator biomedical entity IDs for genes, diseases, chemicals, species, variants, or cell lines. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await search_biomedical_entities_impl(
                client=client,
                query=query,
                concept=concept,
                limit=limit,
            )

    @mcp.tool(
        name="pubtator.find_entity_relations",
        title="Find Entity Relations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_entity_relations(request: FindEntityRelationsRequest) -> dict[str, Any]:
        """Use this when a user has a PubTator entity ID and needs literature-derived related entities. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await find_entity_relations_impl(request, client=client)

    @mcp.tool(
        name="pubtator.submit_text_annotation",
        title="Submit Text Annotation",
        annotations=REMOTE_JOB_ANNOTATIONS,
    )
    async def submit_text_annotation(request: SubmitTextAnnotationRequest) -> dict[str, Any]:
        """Use this when research text should be submitted for PubTator biomedical named entity recognition. Do not submit identifiable patient data to public demo instances."""
        async with PubTator3Client() as client:
            return await submit_text_annotation_impl(request, client=client)

    @mcp.tool(
        name="pubtator.get_text_annotation_results",
        title="Get Text Annotation Results",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_text_annotation_results(
        request: GetTextAnnotationResultsRequest,
    ) -> dict[str, Any]:
        """Use this when a user has a PubTator text annotation session ID and needs its results."""
        async with PubTator3Client() as client:
            return await get_text_annotation_results_impl(request, client=client)

    @mcp.tool(
        name="pubtator.index_review_evidence",
        title="Index Review Evidence",
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def index_review_evidence(request: IndexReviewEvidenceMcpRequest) -> dict[str, Any]:
        """Use this when a review needs review-scoped evidence preparation for a review_id and PMIDs/curated URLs. Call this before retrieve_review_context, then watch preparation_status until jobs are complete, partial, or failed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        queue = await get_review_queue()
        return await index_review_evidence_impl(request, queue=queue)

    @mcp.tool(
        name="pubtator.inspect_review_index",
        title="Inspect Review Index",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def inspect_review_index(
        review_id: str,
        pmids: list[str] | None = None,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
    ) -> dict[str, Any]:
        """Use this when a user needs to inspect indexed PMIDs, sections, passage counts, and failures for a review_id, including source coverage. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await inspect_review_index_impl(
            service=service,
            review_id=review_id,
            pmids=pmids,
            include_passage_samples=include_passage_samples,
            sample_per_pmid=sample_per_pmid,
        )

    @mcp.tool(
        name="pubtator.retrieve_review_context",
        title="Retrieve Review Context",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context(
        review_id: str,
        question: str,
        pmids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        sections: list[str] | None = None,
        max_passages: int = 8,
        max_chars: int = 6000,
        include_diagnostics: bool = False,
        include_tables: bool = False,
        include_references: bool = False,
        table_mode: ReviewTableMode = "preview",
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this when a review needs compact citable context from prepared review passages instead of raw BioC export. Use a short keyword query, PMID filters for paper-specific evidence, and diagnostics for zero-result debugging. If zero passages are returned, simplify the query, inspect the review index, or fall back to fetch_publication_annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await retrieve_review_context_impl(
            service=service,
            review_id=review_id,
            question=question,
            pmids=pmids,
            entity_ids=entity_ids,
            sections=sections,
            max_passages=max_passages,
            max_chars=max_chars,
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        )

    @mcp.tool(
        name="pubtator.retrieve_review_context_batch",
        title="Retrieve Review Context Batch",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context_batch(
        review_id: str,
        queries: list[str],
        pmids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        sections: list[str] | None = None,
        response_mode: ReviewBatchResponseMode = "compact",
        max_passages_per_query: int = 8,
        max_total_passages: int = 20,
        max_chars: int = 12000,
        max_response_chars: int = 24000,
        deduplicate_passages: bool = True,
        include_diagnostics: bool = True,
        include_tables: bool = False,
        include_references: bool = False,
        table_mode: ReviewTableMode = "preview",
        allow_truncated_passages: bool = True,
        max_chars_per_passage: int = 2200,
    ) -> dict[str, Any]:
        """Use this when a user wants multiple short review retrieval query variants in one call. Default compact mode returns merged passages plus per-query summaries; use diagnostics for query refinement and full only when per-query passage text is needed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await retrieve_review_context_batch_impl(
            service=service,
            review_id=review_id,
            queries=queries,
            pmids=pmids,
            entity_ids=entity_ids,
            sections=sections,
            response_mode=response_mode,
            max_passages_per_query=max_passages_per_query,
            max_total_passages=max_total_passages,
            max_chars=max_chars,
            max_response_chars=max_response_chars,
            deduplicate_passages=deduplicate_passages,
            include_diagnostics=include_diagnostics,
            include_tables=include_tables,
            include_references=include_references,
            table_mode=table_mode,
            allow_truncated_passages=allow_truncated_passages,
            max_chars_per_passage=max_chars_per_passage,
        )

    @mcp.resource("pubtator://capabilities")
    def capabilities() -> dict[str, Any]:
        return get_capabilities_resource()

    @mcp.resource("pubtator://bioconcepts")
    def bioconcepts() -> dict[str, Any]:
        return get_bioconcepts_resource()

    @mcp.resource("pubtator://relation-types")
    def relation_types() -> dict[str, Any]:
        return get_relation_types_resource()

    @mcp.resource("pubtator://formats")
    def formats() -> dict[str, Any]:
        return get_formats_resource()

    @mcp.resource("pubtator://text-processing")
    def text_processing() -> dict[str, Any]:
        return get_text_processing_resource()

    @mcp.resource("pubtator://compliance/research-use")
    def research_use() -> dict[str, str]:
        return get_research_use_resource()

    @mcp.prompt(name="search_biomedical_literature", title="Search Biomedical Literature")
    def search_literature_prompt() -> str:
        return search_biomedical_literature_prompt()

    @mcp.prompt(name="annotate_research_text", title="Annotate Research Text")
    def annotate_text_prompt() -> str:
        return annotate_research_text_prompt()

    @mcp.prompt(name="review_pubtator_annotations", title="Review PubTator Annotations")
    def review_annotations_prompt() -> str:
        return review_pubtator_annotations_prompt()

    @mcp.prompt(name="review_rerag_workflow", title="Review Re-RAG Workflow")
    def review_rerag_prompt() -> str:
        return review_rerag_workflow_prompt()

    _install_inspection_managers(mcp)
    return mcp
