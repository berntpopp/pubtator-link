from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.routes.dependencies import get_api_client
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD, REMOTE_JOB_ANNOTATIONS
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.service_adapters import (
    get_text_annotation_results_impl,
    submit_text_annotation_impl,
)


def register_text_annotation_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.submit_text_annotation",
        title="Submit Text Annotation",
        annotations=REMOTE_JOB_ANNOTATIONS,
    )
    async def submit_text_annotation(
        text: Annotated[str, Field(min_length=1, max_length=10000)],
        bioconcepts: Annotated[
            str, Field(description="Comma-separated PubTator bioconcepts or 'all'.")
        ] = "Gene",
    ) -> dict[str, Any]:
        """Use this when research text should be submitted for PubTator biomedical named entity recognition. Do not submit identifiable patient data to public demo instances."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            return await submit_text_annotation_impl(
                client=client,
                text=text,
                bioconcepts=bioconcepts,
            )

        return await run_mcp_tool("pubtator.submit_text_annotation", call)

    @mcp.tool(
        name="pubtator.get_text_annotation_results",
        title="Get Text Annotation Results",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_text_annotation_results(
        session_id: Annotated[str, Field(min_length=8)],
    ) -> dict[str, Any]:
        """Use this when a user has a PubTator text annotation session ID and needs its results."""

        async def call() -> dict[str, Any]:
            client = await get_api_client()
            return await get_text_annotation_results_impl(client=client, session_id=session_id)

        return await run_mcp_tool("pubtator.get_text_annotation_results", call)
