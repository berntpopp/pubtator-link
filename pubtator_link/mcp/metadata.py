from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from pubtator_link.api.routes.dependencies import (
    get_llm_review_context_service,
    get_research_session_service,
    get_review_audit_service,
    get_review_context_service,
    get_review_index_lifecycle_service,
)
from pubtator_link.mcp.annotations import READ_ONLY_CLOSED_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
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
from pubtator_link.mcp.review_resources import (
    get_review_audit_resource,
    get_review_llm_context_resource,
    get_review_passage_audit_resource,
    get_review_passage_resource,
    get_review_session_detail_resource,
    get_review_sessions_resource,
    get_review_summary_resource,
    get_tool_detail_resource,
)
from pubtator_link.mcp.untrusted_content import FORBIDDEN_CODEPOINTS
from pubtator_link.services.workflow_help import WorkflowHelpService

logger = logging.getLogger(__name__)

_MAX_REVIEW_ID_CHARS = 512


def _is_valid_review_id(review_id: str) -> bool:
    """A review id is echoable only if it is bounded and carries no forbidden
    control/zero-width/bidi/NUL code point.

    Callers may supply arbitrary review ids (the tools only enforce
    ``min_length=1``), so this is deliberately permissive about ordinary
    characters -- it strictly rejects exactly the code points the untrusted-text
    fence forbids, which are the ones that could break out of a JSON string or a
    structured log value. A non-matching id is never echoed back.
    """
    return (
        bool(review_id)
        and len(review_id) <= _MAX_REVIEW_ID_CHARS
        and not any(ord(char) in FORBIDDEN_CODEPOINTS for char in review_id)
    )


async def _safe_review_resource(
    review_id: str, build: Callable[[], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    """Run a review-resource body, converting any failure into a fixed payload.

    Two leaks are closed here:

    * The caller-supplied ``review_id`` is validated against the id grammar
      BEFORE the body runs. A non-matching id (hostile prose / control-code
      points) is rejected with a fixed payload that never echoes it, so it can
      reach neither a downstream (empty-result) payload nor a log record.
    * A raw exception escaping a resource handler is otherwise rendered verbatim
      by FastMCP (message + traceback) into its logs. It is caught at the
      boundary and replaced with a fixed, identifier-free payload; only the
      exception type is logged (never ``review_id`` or the exception text).
    """
    if not _is_valid_review_id(review_id):
        logger.warning(
            "Review resource rejected an invalid review id",
            extra={"error_code": "invalid_review_id"},
        )
        return {
            "success": False,
            "error_code": "invalid_review_id",
            "message": "The review id is invalid.",
        }
    try:
        return await build()
    except Exception as exc:
        logger.warning(
            "Review resource read failed",
            extra={"error_type": type(exc).__name__},
        )
        return {
            "success": False,
            "error_code": "resource_unavailable",
            "message": "The review resource is temporarily unavailable.",
        }


class ServerCapabilitiesResponse(BaseModel):
    """Response schema for PubTator-Link capability discovery."""

    model_config = ConfigDict(extra="allow")

    server: str
    transport: str
    endpoint: str
    research_use_only: bool
    core_workflow_tools: list[str]
    tool_categories: dict[str, list[str]]
    next_tool: str
    details: dict[str, Any] | None = Field(default=None)


def register_metadata(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    @mcp.tool(
        name="get_server_capabilities",
        title="Get PubTator-Link Capabilities",
        output_schema=None,
        annotations=READ_ONLY_CLOSED_WORLD,
    )
    async def get_server_capabilities(
        details: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional capability sections to expand (e.g. 'tools', 'workflow_help'); "
                    "omit for the default summary."
                ),
                examples=[["tools", "workflow_help"]],
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Use this when a client needs supported tools, transports, formats, and limitations. Do not use this for task-specific workflow guidance; use workflow_help. Next: workflow_help."""

        async def call() -> dict[str, Any]:
            return get_capabilities_resource(details=details, profile=profile)

        return await run_mcp_tool("get_server_capabilities", call)

    @mcp.tool(
        name="workflow_help",
        title="Workflow Help",
        output_schema=None,
        annotations=READ_ONLY_CLOSED_WORLD,
        tags={"meta"},
    )
    async def workflow_help(
        task: Annotated[
            str,
            Field(
                description=(
                    "Workflow to describe; defaults to the canonical "
                    "'clinical_genetics_review' pipeline."
                ),
                examples=["clinical_genetics_review"],
            ),
        ] = "clinical_genetics_review",
    ) -> dict[str, Any]:
        """Use this when a fresh context needs the canonical PubTator-Link research workflow."""

        async def call() -> dict[str, Any]:
            return WorkflowHelpService(profile=profile).get_help(task).model_dump(by_alias=True)

        return await run_mcp_tool("workflow_help", call)

    @mcp.resource("pubtator://capabilities")
    def capabilities() -> dict[str, Any]:
        return get_capabilities_resource(profile=profile)

    @mcp.resource("pubtator://workflow-help")
    def workflow_help_resource() -> dict[str, Any]:
        return get_workflow_help_resource(profile=profile)

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

    @mcp.resource("pubtator://reviews/{review_id}")
    async def review_summary(review_id: str) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_review_index_lifecycle_service()
            return await get_review_summary_resource(service=service, review_id=review_id)

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://reviews/{review_id}/sessions")
    async def review_sessions(review_id: str) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_research_session_service()
            return await get_review_sessions_resource(service=service, review_id=review_id)

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://reviews/{review_id}/sessions/{session_id}")
    async def review_session_detail(review_id: str, session_id: str) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_research_session_service()
            return await get_review_session_detail_resource(
                service=service,
                review_id=review_id,
                session_id=session_id,
            )

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://reviews/{review_id}/passages/{passage_id}")
    @mcp.resource("pubtator://reviews/{review_id}/passages/{passage_id}{?before,after,session_id}")
    async def review_passage(
        review_id: str,
        passage_id: str,
        before: int | None = None,
        after: int | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_review_context_service()
            return await get_review_passage_resource(
                service=service,
                review_id=review_id,
                passage_id=passage_id,
                before=before,
                after=after,
                session_id=session_id,
            )

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://reviews/{review_id}/audit")
    async def review_audit(review_id: str) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_review_audit_service()
            return await get_review_audit_resource(service=service, review_id=review_id)

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://reviews/{review_id}/audit/{passage_id}")
    @mcp.resource("pubtator://reviews/{review_id}/audit/{passage_id}{?session_id}")
    async def review_passage_audit(
        review_id: str,
        passage_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_review_context_service()
            return await get_review_passage_audit_resource(
                service=service,
                review_id=review_id,
                passage_id=passage_id,
                session_id=session_id,
            )

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://reviews/{review_id}/llm-context")
    @mcp.resource("pubtator://reviews/{review_id}/llm-context{?session_id}")
    async def review_llm_context(
        review_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_llm_review_context_service()
            return await get_review_llm_context_resource(
                service=service,
                review_id=review_id,
                session_id=session_id,
            )

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://reviews/{review_id}/llm-context/latest")
    @mcp.resource("pubtator://reviews/{review_id}/llm-context/latest{?session_id}")
    async def review_latest_llm_context(
        review_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            service = await get_llm_review_context_service()
            return await get_review_llm_context_resource(
                service=service,
                review_id=review_id,
                latest=True,
                session_id=session_id,
            )

        return await _safe_review_resource(review_id, build)

    @mcp.resource("pubtator://capabilities/tools/{tool_name}")
    def tool_detail(tool_name: str) -> dict[str, Any]:
        return get_tool_detail_resource(tool_name)

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
