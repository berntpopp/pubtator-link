"""Lock down the set of MCP tools registered by register_review_tools."""

from __future__ import annotations

from fastmcp import FastMCP

from pubtator_link.mcp.compat import install_inspection_managers
from pubtator_link.mcp.profiles import FULL_ONLY_TOOLS, LEAN_TOOLS
from pubtator_link.mcp.tools.review import register_review_tools

LEGACY_PUBLIC_IMPORTS = {
    "Annotated",
    "Any",
    "BudgetStrategy",
    "Callable",
    "Context",
    "EvidenceCertaintyResponse",
    "EvidenceCertaintyLabel",
    "FILE_EXPORT_ANNOTATIONS",
    "FastMCP",
    "Field",
    "GroundQuestionResponse",
    "IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS",
    "IndexReviewEvidenceResponse",
    "InspectReviewIndexResponse",
    "ListEvidenceCertaintyResponse",
    "ListResearchSessionsResponse",
    "ListReviewIndexesResponse",
    "Literal",
    "MCPToolProfile",
    "MaxResponseChars",
    "McpReviewAuditBundleResponse",
    "NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS",
    "PreflightReviewSourcesResponse",
    "READ_ONLY_OPEN_WORLD",
    "RecordReviewContextResponse",
    "ResearchSessionStatusResponse",
    "RetrieveReviewContextBatchResponse",
    "RetrieveReviewContextResponse",
    "ReviewAuditTrailResponse",
    "ReviewBatchResponseMode",
    "ReviewIndexSummaryResponse",
    "ReviewLlmContextEventType",
    "ReviewPassageLookupResponse",
    "ReviewQuickstartResponse",
    "ReviewResponseVerbosity",
    "ReviewTableMode",
    "SampleSectionPolicy",
    "StageResearchSessionResponse",
    "cast",
    "run_mcp_tool",
}

REVIEW_TOOLS_IN_LEAN = frozenset(
    {
        "preflight_review_sources",
        "index_review_evidence",
        "inspect_review_index",
        "ground_question",
        "get_review_context_batch",
        "get_review_audit_trail",
        "record_review_context",
    }
)

REVIEW_TOOLS_IN_FULL_ONLY = frozenset(
    {
        "review_quickstart",
        "get_review_context",
        "get_review_passages_by_id",
        "get_neighboring_review_passages",
        "export_review_audit_bundle",
        "list_review_indexes",
        "get_review_index_summary",
        "add_evidence_certainty",
        "list_evidence_certainty",
        "get_evidence_certainty",
        "stage_research_session",
        "get_research_session_status",
        "list_research_sessions",
    }
)


def _registered(profile: str) -> set[str]:
    mcp = FastMCP("test")
    register_review_tools(mcp, profile=profile)
    install_inspection_managers(mcp)
    return set(mcp._tool_manager._tools)


def test_lean_profile_registers_expected_review_tools() -> None:
    registered = _registered("lean")
    missing = REVIEW_TOOLS_IN_LEAN - registered
    assert not missing, f"missing lean review tools after split: {missing}"
    leaked = REVIEW_TOOLS_IN_FULL_ONLY & registered
    assert not leaked, f"full-only tool leaked into lean profile: {leaked}"


def test_full_profile_registers_lean_plus_full_only() -> None:
    full = _registered("full")
    expected = REVIEW_TOOLS_IN_LEAN | REVIEW_TOOLS_IN_FULL_ONLY
    missing = expected - full
    assert not missing, f"missing review tools in full profile: {missing}"


def test_inventory_constants_match_canonical_profile_tuples() -> None:
    assert set(LEAN_TOOLS) >= REVIEW_TOOLS_IN_LEAN
    assert set(FULL_ONLY_TOOLS) >= REVIEW_TOOLS_IN_FULL_ONLY


def test_legacy_public_imports_still_resolve_from_review_root() -> None:
    import pubtator_link.mcp.tools.review as review

    missing = sorted(name for name in LEGACY_PUBLIC_IMPORTS if not hasattr(review, name))
    assert not missing, f"missing legacy review imports after split: {missing}"
