from __future__ import annotations

from fastmcp import FastMCP

from pubtator_link.api.routes.dependencies import (  # noqa: F401
    get_api_client,
    get_llm_review_context_service,
    get_research_session_service,
    get_review_audit_service,
    get_review_context_service,
    get_review_evidence_certainty_service,
    get_review_index_lifecycle_service,
    get_review_queue,
    get_source_preflight_service,
)
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.service_adapters import (  # noqa: F401
    add_evidence_certainty_impl,
    export_review_audit_bundle_impl,
    get_evidence_certainty_impl,
    get_neighboring_review_passages_impl,
    get_research_session_status_impl,
    get_review_audit_trail_impl,
    get_review_index_summary_impl,
    get_review_passages_by_id_impl,
    ground_question_impl,
    index_review_evidence_impl,
    inspect_review_index_impl,
    list_evidence_certainty_impl,
    list_research_sessions_impl,
    list_review_indexes_impl,
    preflight_review_sources_impl,
    record_review_context_impl,
    retrieve_review_context_batch_impl,
    retrieve_review_context_impl,
    review_quickstart_impl,
    stage_research_session_impl,
)
from pubtator_link.mcp.tools.review.evidence_certainty import register_evidence_certainty_tools
from pubtator_link.mcp.tools.review.export import register_export_tools
from pubtator_link.mcp.tools.review.indexes import register_indexes_tools
from pubtator_link.mcp.tools.review.passages import register_passages_tools
from pubtator_link.mcp.tools.review.research import register_research_tools
from pubtator_link.mcp.tools.review.retrieval import register_retrieval_tools

__all__ = [
    "add_evidence_certainty_impl",
    "export_review_audit_bundle_impl",
    "get_api_client",
    "get_evidence_certainty_impl",
    "get_llm_review_context_service",
    "get_neighboring_review_passages_impl",
    "get_research_session_service",
    "get_research_session_status_impl",
    "get_review_audit_service",
    "get_review_audit_trail_impl",
    "get_review_context_service",
    "get_review_evidence_certainty_service",
    "get_review_index_lifecycle_service",
    "get_review_index_summary_impl",
    "get_review_passages_by_id_impl",
    "get_review_queue",
    "get_source_preflight_service",
    "ground_question_impl",
    "index_review_evidence_impl",
    "inspect_review_index_impl",
    "list_evidence_certainty_impl",
    "list_research_sessions_impl",
    "list_review_indexes_impl",
    "preflight_review_sources_impl",
    "record_review_context_impl",
    "register_review_tools",
    "retrieve_review_context_batch_impl",
    "retrieve_review_context_impl",
    "review_quickstart_impl",
    "stage_research_session_impl",
]


def register_review_tools(mcp: FastMCP, profile: MCPToolProfile = "lean") -> None:
    register_indexes_tools(mcp, profile)
    register_evidence_certainty_tools(mcp, profile)
    register_research_tools(mcp, profile)
    register_passages_tools(mcp, profile)
    register_export_tools(mcp, profile)
    register_retrieval_tools(mcp, profile)
