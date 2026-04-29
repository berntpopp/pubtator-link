from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastmcp import FastMCP

from pubtator_link.mcp.prompts import (
    annotate_research_text_prompt,
    review_pubtator_annotations_prompt,
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
from pubtator_link.mcp.tools import (
    FetchPmcAnnotationsRequest,
    FetchPublicationAnnotationsRequest,
    FindEntityRelationsRequest,
    GetTextAnnotationResultsRequest,
    SearchBiomedicalEntitiesRequest,
    SearchLiteratureRequest,
    SubmitTextAnnotationRequest,
)


def _install_inspection_managers(mcp: FastMCP) -> None:
    components = mcp.providers[0]._components
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

    mcp._tool_manager = SimpleNamespace(_tools=tools)
    mcp._resource_manager = SimpleNamespace(_resources=resources)
    mcp._prompt_manager = SimpleNamespace(_prompts=prompts)


def create_pubtator_mcp() -> FastMCP:
    mcp = FastMCP(
        name="pubtator-link",
        instructions=(
            "PubTator-Link exposes PubTator3 biomedical literature, entity, relation, "
            f"and text annotation capabilities. {RESEARCH_USE_NOTICE}"
        ),
    )

    @mcp.tool(name="pubtator.get_server_capabilities", title="Get PubTator-Link Capabilities")
    def get_server_capabilities() -> dict[str, Any]:
        """Use this when a client needs supported tools, transports, formats, and limitations."""
        return get_capabilities_resource()

    @mcp.tool(name="pubtator.search_literature", title="Search Biomedical Literature")
    async def search_literature(request: SearchLiteratureRequest) -> dict[str, Any]:
        """Use this when a user needs PubMed literature search through PubTator3. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.fetch_publication_annotations", title="Fetch Publication Annotations")
    async def fetch_publication_annotations(
        request: FetchPublicationAnnotationsRequest,
    ) -> dict[str, Any]:
        """Use this when a user provides PubMed IDs and needs PubTator annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.fetch_pmc_annotations", title="Fetch PMC Annotations")
    async def fetch_pmc_annotations(request: FetchPmcAnnotationsRequest) -> dict[str, Any]:
        """Use this when a user provides PMC IDs and needs PubTator full-text annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.search_biomedical_entities", title="Search Biomedical Entities")
    async def search_biomedical_entities(request: SearchBiomedicalEntitiesRequest) -> dict[str, Any]:
        """Use this when a user needs canonical PubTator biomedical entity IDs. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.find_entity_relations", title="Find Entity Relations")
    async def find_entity_relations(request: FindEntityRelationsRequest) -> dict[str, Any]:
        """Use this when a user has a PubTator entity ID and needs literature-derived related entities. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.submit_text_annotation", title="Submit Text Annotation")
    async def submit_text_annotation(request: SubmitTextAnnotationRequest) -> dict[str, Any]:
        """Use this when research text should be submitted for PubTator biomedical named entity recognition. Do not submit identifiable patient data to public demo instances."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.get_text_annotation_results", title="Get Text Annotation Results")
    async def get_text_annotation_results(
        request: GetTextAnnotationResultsRequest,
    ) -> dict[str, Any]:
        """Use this when a user has a PubTator text annotation session ID and needs its results."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

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

    _install_inspection_managers(mcp)
    return mcp
