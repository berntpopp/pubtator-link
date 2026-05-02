from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from pubtator_link.mcp.annotations import READ_ONLY_CLOSED_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
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
    get_workflow_help_resource,
)
from pubtator_link.models.workflow_help import WorkflowHelpResponse, WorkflowTask
from pubtator_link.services.workflow_help import WorkflowHelpService


def register_metadata(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.get_server_capabilities",
        title="Get PubTator-Link Capabilities",
        annotations=READ_ONLY_CLOSED_WORLD,
    )
    async def get_server_capabilities() -> dict[str, Any]:
        """Use this when a client needs supported tools, transports, formats, and limitations."""

        async def call() -> dict[str, Any]:
            return get_capabilities_resource()

        return await run_mcp_tool("pubtator.get_server_capabilities", call)

    @mcp.tool(
        name="pubtator.workflow_help",
        title="Workflow Help",
        output_schema=WorkflowHelpResponse.model_json_schema(),
        annotations=READ_ONLY_CLOSED_WORLD,
    )
    async def workflow_help(
        task: WorkflowTask = "clinical_genetics_review",
    ) -> dict[str, Any]:
        """Use this when a fresh context needs the canonical PubTator-Link research workflow."""

        async def call() -> dict[str, Any]:
            return WorkflowHelpService().get_help(task).model_dump(by_alias=True)

        return await run_mcp_tool("pubtator.workflow_help", call)

    @mcp.resource("pubtator://capabilities")
    def capabilities() -> dict[str, Any]:
        return get_capabilities_resource()

    @mcp.resource("pubtator://workflow-help")
    def workflow_help_resource() -> dict[str, Any]:
        return get_workflow_help_resource()

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
