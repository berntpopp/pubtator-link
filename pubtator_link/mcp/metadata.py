from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from pubtator_link.mcp.annotations import READ_ONLY_CLOSED_WORLD
from pubtator_link.mcp.prompts import (
    annotate_research_text_prompt,
    review_pubtator_annotations_prompt,
    review_rerag_workflow_prompt,
    search_biomedical_literature_prompt,
)
from pubtator_link.mcp.resources import (
    get_bioconcepts_resource,
    get_capabilities_resource,
    get_formats_resource,
    get_relation_types_resource,
    get_research_use_resource,
    get_text_processing_resource,
)


def register_metadata(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.get_server_capabilities",
        title="Get PubTator-Link Capabilities",
        annotations=READ_ONLY_CLOSED_WORLD,
    )
    def get_server_capabilities() -> dict[str, Any]:
        """Use this when a client needs supported tools, transports, formats, and limitations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        return get_capabilities_resource()

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
