from __future__ import annotations

from typing import Literal, cast

MCPToolProfile = Literal["lean", "full", "readonly"]

DEFAULT_MCP_PROFILE: MCPToolProfile = "lean"

LEAN_TOOLS: tuple[str, ...] = (
    "pubtator_workflow_help",
    "pubtator_get_server_capabilities",
    "pubtator_diagnostics",
    "pubtator_search_literature",
    "pubtator_search_guidelines",
    "pubtator_search_biomedical_entities",
    "pubtator_lookup_variant_evidence",
    "pubtator_get_publication_metadata",
    "pubtator_get_publication_passages",
    "pubtator_get_publication_citation_graph",
    "pubtator_find_related_evidence_candidates",
    "pubtator_preflight_review_sources",
    "pubtator_index_review_evidence",
    "pubtator_inspect_review_index",
    "pubtator_ground_question",
    "pubtator_retrieve_review_context_batch",
    "pubtator_get_review_audit_trail",
    "pubtator_record_review_context",
)

FULL_ONLY_TOOLS: tuple[str, ...] = (
    "pubtator_review_quickstart",
    "pubtator_convert_article_ids",
    "pubtator_lookup_mesh",
    "pubtator_lookup_citation",
    "pubtator_find_related_articles",
    "pubtator_suggest_corpus",
    "pubtator_build_topic_literature_map",
    "pubtator_fetch_publication_annotations",
    "pubtator_estimate_publication_context",
    "pubtator_fetch_pmc_annotations",
    "pubtator_find_entity_relations",
    "pubtator_submit_text_annotation",
    "pubtator_get_text_annotation_results",
    "pubtator_retrieve_review_context",
    "pubtator_get_review_passages_by_id",
    "pubtator_get_neighboring_review_passages",
    "pubtator_export_review_audit_bundle",
    "pubtator_list_review_indexes",
    "pubtator_get_review_index_summary",
    "pubtator_add_evidence_certainty",
    "pubtator_list_evidence_certainty",
    "pubtator_get_evidence_certainty",
    "pubtator_stage_research_session",
    "pubtator_get_research_session_status",
    "pubtator_list_research_sessions",
)

READONLY_TOOLS: tuple[str, ...] = tuple(
    name
    for name in (*LEAN_TOOLS, *FULL_ONLY_TOOLS)
    if name
    not in {
        "pubtator_index_review_evidence",
        "pubtator_ground_question",
        "pubtator_record_review_context",
        "pubtator_submit_text_annotation",
        "pubtator_export_review_audit_bundle",
        "pubtator_add_evidence_certainty",
        "pubtator_stage_research_session",
        "pubtator_review_quickstart",
        "pubtator_build_topic_literature_map",
        "pubtator_fetch_publication_annotations",
        "pubtator_fetch_pmc_annotations",
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
