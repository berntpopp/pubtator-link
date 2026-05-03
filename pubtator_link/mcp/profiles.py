from __future__ import annotations

from typing import Literal, cast

MCPToolProfile = Literal["lean", "full", "readonly"]

DEFAULT_MCP_PROFILE: MCPToolProfile = "lean"

LEAN_TOOLS: tuple[str, ...] = (
    "pubtator.workflow_help",
    "pubtator.get_server_capabilities",
    "pubtator.diagnostics",
    "pubtator.search_literature",
    "pubtator.search_guidelines",
    "pubtator.search_biomedical_entities",
    "pubtator.lookup_variant_evidence",
    "pubtator.get_publication_metadata",
    "pubtator.get_publication_passages",
    "pubtator.get_publication_citation_graph",
    "pubtator.find_related_evidence_candidates",
    "pubtator.preflight_review_sources",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.ground_question",
    "pubtator.retrieve_review_context_batch",
    "pubtator.get_review_audit_trail",
    "pubtator.record_review_context",
)

FULL_ONLY_TOOLS: tuple[str, ...] = (
    "pubtator.review_quickstart",
    "pubtator.convert_article_ids",
    "pubtator.lookup_mesh",
    "pubtator.lookup_citation",
    "pubtator.find_related_articles",
    "pubtator.suggest_corpus",
    "pubtator.fetch_publication_annotations",
    "pubtator.estimate_publication_context",
    "pubtator.fetch_pmc_annotations",
    "pubtator.find_entity_relations",
    "pubtator.submit_text_annotation",
    "pubtator.get_text_annotation_results",
    "pubtator.retrieve_review_context",
    "pubtator.get_review_passages_by_id",
    "pubtator.get_neighboring_review_passages",
    "pubtator.export_review_audit_bundle",
    "pubtator.list_review_indexes",
    "pubtator.get_review_index_summary",
    "pubtator.add_evidence_certainty",
    "pubtator.list_evidence_certainty",
    "pubtator.get_evidence_certainty",
    "pubtator.stage_research_session",
    "pubtator.get_research_session_status",
    "pubtator.list_research_sessions",
)

READONLY_TOOLS: tuple[str, ...] = tuple(
    name
    for name in (*LEAN_TOOLS, *FULL_ONLY_TOOLS)
    if name
    not in {
        "pubtator.index_review_evidence",
        "pubtator.ground_question",
        "pubtator.record_review_context",
        "pubtator.submit_text_annotation",
        "pubtator.export_review_audit_bundle",
        "pubtator.add_evidence_certainty",
        "pubtator.stage_research_session",
        "pubtator.review_quickstart",
        "pubtator.fetch_publication_annotations",
        "pubtator.fetch_pmc_annotations",
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
