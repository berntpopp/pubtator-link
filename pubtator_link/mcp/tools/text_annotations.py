from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import get_api_client
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD, REMOTE_JOB_ANNOTATIONS
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (
    get_text_annotation_results_impl,
    submit_text_annotation_impl,
)
from pubtator_link.models.responses import (
    TextAnnotationResultResponse,
    TextAnnotationSubmitResponse,
)


def _submit_text_annotation_output_schema() -> dict[str, Any]:
    schema = TextAnnotationSubmitResponse.model_json_schema()
    properties = schema.setdefault("properties", {})
    result_properties = TextAnnotationResultResponse.model_json_schema().get("properties", {})
    if isinstance(properties, dict) and isinstance(result_properties, dict):
        properties.update(
            {
                key: value
                for key, value in result_properties.items()
                if key not in {"success", "message", "session_id", "status"}
            }
        )
    return schema


def register_text_annotation_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    if profile == "full":

        @mcp.tool(
            name="pubtator_submit_text_annotation",
            title="Submit Text Annotation",
            output_schema=_submit_text_annotation_output_schema(),
            annotations=REMOTE_JOB_ANNOTATIONS,
        )
        async def submit_text_annotation(
            text: Annotated[str, Field(min_length=1, max_length=10000)],
            bioconcepts: Annotated[
                str, Field(description="Comma-separated PubTator bioconcepts or 'all'.")
            ] = "Gene",
            wait: Annotated[
                bool, Field(description="Poll briefly and return results when ready.")
            ] = False,
            timeout_ms: Annotated[int, Field(ge=1000, le=30000)] = 30000,
        ) -> dict[str, Any]:
            """Use this when research text should be submitted for PubTator biomedical named entity recognition. Do not use this for PubMed or PMC IDs; use pubtator_fetch_publication_annotations. Next: pubtator_get_text_annotation_results."""

            async def call() -> dict[str, Any]:
                client = await get_api_client()
                return await submit_text_annotation_impl(
                    client=client,
                    text=text,
                    bioconcepts=bioconcepts,
                    wait=wait,
                    timeout_ms=timeout_ms,
                )

            return await run_mcp_tool("pubtator_submit_text_annotation", call)

    if profile == "lean":
        return

    @mcp.tool(
        name="pubtator_get_text_annotation_results",
        title="Get Text Annotation Results",
        output_schema=TextAnnotationResultResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_text_annotation_results(
        session_id: Annotated[str, Field(min_length=8)],
    ) -> dict[str, Any]:
        """Use this when a user has a PubTator text annotation session ID and needs its results. Do not use this for entity lookup from names; use pubtator_search_biomedical_entities. Next: pubtator_search_biomedical_entities."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            return await get_text_annotation_results_impl(client=client, session_id=session_id)

        return await run_mcp_tool("pubtator_get_text_annotation_results", call)
