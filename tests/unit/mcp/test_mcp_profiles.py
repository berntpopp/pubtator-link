from __future__ import annotations

import pytest

from pubtator_link.mcp.profiles import LEAN_TOOLS, WRITE_TOOLS, normalize_mcp_profile

EXPECTED_WRITE_TOOLS = {
    "index_review_evidence",
    "ground_question",
    "record_review_context",
    "stage_research_session",
    "review_quickstart",
    "add_evidence_certainty",
    "submit_text_annotation",
    "export_review_audit_bundle",
}

EXPECTED_LEAN_TOOLS = {
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
}


def _tool_names(profile: str) -> set[str]:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    return set(create_pubtator_mcp(profile=profile)._tool_manager._tools)


def test_lean_tools_constant_is_exact() -> None:
    assert set(LEAN_TOOLS) == EXPECTED_LEAN_TOOLS


def test_write_tool_inventory_is_exact() -> None:
    assert set(WRITE_TOOLS) == EXPECTED_WRITE_TOOLS


def test_registered_write_annotations_match_inventory() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tools = create_pubtator_mcp(profile="full")._tool_manager._tools
    annotated_writes = {
        name
        for name, tool in tools.items()
        if tool.annotations is not None and tool.annotations.readOnlyHint is False
    }
    assert annotated_writes == EXPECTED_WRITE_TOOLS


def test_readonly_preserves_full_surface_read_tools() -> None:
    full_names = _tool_names("full")
    readonly_names = _tool_names("readonly")
    assert EXPECTED_WRITE_TOOLS <= full_names
    assert readonly_names == full_names - EXPECTED_WRITE_TOOLS
    assert {
        "get_publication_annotations",
        "get_pmc_annotations",
        "build_topic_literature_map",
    } <= readonly_names


def test_normalize_mcp_profile_accepts_supported_values() -> None:
    assert normalize_mcp_profile(None) == "readonly"
    assert normalize_mcp_profile("") == "readonly"
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
    assert "get_review_context" in tool_names
    assert "get_review_passages_by_id" in tool_names
    assert "get_neighboring_review_passages" in tool_names
    assert "export_review_audit_bundle" in tool_names


def test_create_pubtator_mcp_readonly_profile_excludes_write_and_export_tools() -> None:
    tool_names = _tool_names("readonly")

    assert "index_review_evidence" not in tool_names
    assert "ground_question" not in tool_names
    assert "record_review_context" not in tool_names
    assert "export_review_audit_bundle" not in tool_names
    assert "get_publication_annotations" in tool_names
    assert "get_pmc_annotations" in tool_names
    assert "get_review_context_batch" in tool_names
    assert "get_review_audit_trail" in tool_names


def test_ground_question_is_lean_and_full_but_not_readonly() -> None:
    assert "ground_question" in _tool_names("lean")
    assert "ground_question" in _tool_names("full")
    assert "ground_question" not in _tool_names("readonly")


def test_citation_graph_is_lean_full_and_readonly() -> None:
    tool_name = "get_publication_citation_graph"

    assert tool_name in _tool_names("lean")
    assert tool_name in _tool_names("full")
    assert tool_name in _tool_names("readonly")


def test_related_evidence_is_lean_full_and_readonly() -> None:
    tool_name = "find_related_evidence_candidates"

    assert tool_name in _tool_names("lean")
    assert tool_name in _tool_names("full")
    assert tool_name in _tool_names("readonly")


def test_topic_literature_map_is_available_in_readonly() -> None:
    tool_name = "build_topic_literature_map"

    assert tool_name not in _tool_names("lean")
    assert tool_name in _tool_names("full")
    assert tool_name in _tool_names("readonly")


def test_topic_literature_map_is_advertised_in_readonly_profile_metadata() -> None:
    from pubtator_link.mcp.profiles import tool_names_for_profile

    assert "build_topic_literature_map" in tool_names_for_profile("readonly")
