from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.routes.dependencies import get_review_context_service, get_review_queue
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
    fetch_pmc_annotations_impl,
    fetch_publication_annotations_impl,
    find_entity_relations_impl,
    get_text_annotation_results_impl,
    index_review_evidence_impl,
    retrieve_review_context_impl,
    search_biomedical_entities_impl,
    search_literature_impl,
    submit_text_annotation_impl,
)
from pubtator_link.mcp.tools import (
    FetchPmcAnnotationsRequest,
    FetchPublicationAnnotationsRequest,
    FindEntityRelationsRequest,
    GetTextAnnotationResultsRequest,
    IndexReviewEvidenceMcpRequest,
    RetrieveReviewContextMcpRequest,
    SearchBiomedicalEntitiesRequest,
    SearchLiteratureRequest,
    SubmitTextAnnotationRequest,
)
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
            "PubTator-Link exposes PubTator3 biomedical literature, entity, relation, "
            f"and text annotation capabilities. {RESEARCH_USE_NOTICE}"
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
    async def search_literature(request: SearchLiteratureRequest) -> dict[str, Any]:
        """Use this when a user needs PubMed literature search through PubTator3. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await search_literature_impl(request, client=client)

    @mcp.tool(
        name="pubtator.fetch_publication_annotations",
        title="Fetch Publication Annotations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def fetch_publication_annotations(
        request: FetchPublicationAnnotationsRequest,
    ) -> dict[str, Any]:
        """Use this when a user provides PubMed IDs and needs PubTator annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            service = PublicationService(client=client)
            return await fetch_publication_annotations_impl(request, service=service)

    @mcp.tool(
        name="pubtator.fetch_pmc_annotations",
        title="Fetch PMC Annotations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def fetch_pmc_annotations(request: FetchPmcAnnotationsRequest) -> dict[str, Any]:
        """Use this when a user provides PMC IDs and needs PubTator full-text annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            service = PublicationService(client=client)
            return await fetch_pmc_annotations_impl(request, service=service)

    @mcp.tool(
        name="pubtator.search_biomedical_entities",
        title="Search Biomedical Entities",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_biomedical_entities(
        request: SearchBiomedicalEntitiesRequest,
    ) -> dict[str, Any]:
        """Use this when a user needs canonical PubTator biomedical entity IDs. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await search_biomedical_entities_impl(request, client=client)

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
        """Queue review-scoped evidence preparation for a review_id and PMIDs/curated URLs. Call this before retrieve_review_context, then watch preparation_status until jobs are complete, partial, or failed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        queue = await get_review_queue()
        return await index_review_evidence_impl(request, queue=queue)

    @mcp.tool(
        name="pubtator.retrieve_review_context",
        title="Retrieve Review Context",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context(request: RetrieveReviewContextMcpRequest) -> dict[str, Any]:
        """Retrieve a compact citable context pack from prepared review passages. Best results usually come from a short keyword query; use pmids when focusing on a specific paper. If zero passages are returned, simplify the query or fall back to fetch_publication_annotations with full=true. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await retrieve_review_context_impl(request, service=service)

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
