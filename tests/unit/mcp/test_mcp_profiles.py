from __future__ import annotations

import pytest

from pubtator_link.mcp.profiles import LEAN_TOOLS, normalize_mcp_profile

EXPECTED_LEAN_TOOLS = {
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
}


def _tool_names(profile: str) -> set[str]:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    return set(create_pubtator_mcp(profile=profile)._tool_manager._tools)


def test_lean_tools_constant_is_exact() -> None:
    assert set(LEAN_TOOLS) == EXPECTED_LEAN_TOOLS


def test_normalize_mcp_profile_accepts_supported_values() -> None:
    assert normalize_mcp_profile(None) == "lean"
    assert normalize_mcp_profile("") == "lean"
    assert normalize_mcp_profile("lean") == "lean"
    assert normalize_mcp_profile("full") == "full"
    assert normalize_mcp_profile("readonly") == "readonly"


def test_normalize_mcp_profile_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="mcp_profile must be one of: lean, full, readonly"):
        normalize_mcp_profile("compact")


def test_create_pubtator_mcp_lean_profile_exposes_exact_lean_tools() -> None:
    assert _tool_names("lean") == set(LEAN_TOOLS)


def test_create_pubtator_mcp_full_profile_keeps_compatibility_tools() -> None:
    tool_names = _tool_names("full")

    assert set(LEAN_TOOLS) <= tool_names
    assert "pubtator_retrieve_review_context" in tool_names
    assert "pubtator_get_review_passages_by_id" in tool_names
    assert "pubtator_get_neighboring_review_passages" in tool_names
    assert "pubtator_export_review_audit_bundle" in tool_names


def test_create_pubtator_mcp_readonly_profile_excludes_write_and_export_tools() -> None:
    tool_names = _tool_names("readonly")

    assert "pubtator_index_review_evidence" not in tool_names
    assert "pubtator_ground_question" not in tool_names
    assert "pubtator_record_review_context" not in tool_names
    assert "pubtator_export_review_audit_bundle" not in tool_names
    assert "pubtator_fetch_publication_annotations" not in tool_names
    assert "pubtator_fetch_pmc_annotations" not in tool_names
    assert "pubtator_retrieve_review_context_batch" in tool_names
    assert "pubtator_get_review_audit_trail" in tool_names


def test_ground_question_is_lean_and_full_but_not_readonly() -> None:
    assert "pubtator_ground_question" in _tool_names("lean")
    assert "pubtator_ground_question" in _tool_names("full")
    assert "pubtator_ground_question" not in _tool_names("readonly")


def test_citation_graph_is_lean_full_and_readonly() -> None:
    tool_name = "pubtator_get_publication_citation_graph"

    assert tool_name in _tool_names("lean")
    assert tool_name in _tool_names("full")
    assert tool_name in _tool_names("readonly")


def test_related_evidence_is_lean_full_and_readonly() -> None:
    tool_name = "pubtator_find_related_evidence_candidates"

    assert tool_name in _tool_names("lean")
    assert tool_name in _tool_names("full")
    assert tool_name in _tool_names("readonly")


def test_topic_literature_map_is_full_only() -> None:
    tool_name = "pubtator_build_topic_literature_map"

    assert tool_name not in _tool_names("lean")
    assert tool_name in _tool_names("full")
    assert tool_name not in _tool_names("readonly")


def test_topic_literature_map_is_not_advertised_in_readonly_profile_metadata() -> None:
    from pubtator_link.mcp.profiles import tool_names_for_profile

    assert "pubtator_build_topic_literature_map" not in tool_names_for_profile("readonly")
