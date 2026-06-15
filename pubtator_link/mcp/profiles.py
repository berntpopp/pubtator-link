from __future__ import annotations

from typing import Literal, cast

MCPToolProfile = Literal["lean", "full", "readonly"]

DEFAULT_MCP_PROFILE: MCPToolProfile = "lean"

LEAN_TOOLS: tuple[str, ...] = (
    "workflow_help",
    "get_server_capabilities",
    "diagnostics",
    "search_literature",
    "search_guidelines",
    "search_biomedical_entities",
    "get_variant_evidence",
    "get_publication_metadata",
    "get_publication_passages",
    "get_publication_citation_graph",
    "find_related_evidence_candidates",
    "preflight_review_sources",
    "index_review_evidence",
    "inspect_review_index",
    "ground_question",
    "get_review_context_batch",
    "get_review_audit_trail",
    "record_review_context",
)

FULL_ONLY_TOOLS: tuple[str, ...] = (
    "review_quickstart",
    "convert_article_ids",
    "get_mesh",
    "get_citation",
    "find_related_articles",
    "suggest_corpus",
    "build_topic_literature_map",
    "get_publication_annotations",
    "estimate_publication_context",
    "get_pmc_annotations",
    "find_entity_relations",
    "submit_text_annotation",
    "get_text_annotation_results",
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
)

READONLY_TOOLS: tuple[str, ...] = tuple(
    name
    for name in (*LEAN_TOOLS, *FULL_ONLY_TOOLS)
    if name
    not in {
        "index_review_evidence",
        "ground_question",
        "record_review_context",
        "submit_text_annotation",
        "export_review_audit_bundle",
        "add_evidence_certainty",
        "stage_research_session",
        "review_quickstart",
        "build_topic_literature_map",
        "get_publication_annotations",
        "get_pmc_annotations",
    }
)


def normalize_mcp_profile(value: str | None) -> MCPToolProfile:
    if value is None or value == "":
        return DEFAULT_MCP_PROFILE
    if value in ("lean", "full", "readonly"):
        return cast(MCPToolProfile, value)
    raise ValueError("mcp_profile must be one of: lean, full, readonly")


def tool_names_for_profile(profile: MCPToolProfile) -> set[str]:
    if profile == "lean":
        return set(LEAN_TOOLS)
    if profile == "readonly":
        return set(READONLY_TOOLS)
    return {*LEAN_TOOLS, *FULL_ONLY_TOOLS}
