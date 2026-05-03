from __future__ import annotations

import pytest

from pubtator_link.mcp.profiles import LEAN_TOOLS, normalize_mcp_profile

EXPECTED_LEAN_TOOLS = {
    "pubtator.workflow_help",
    "pubtator.get_server_capabilities",
    "pubtator.diagnostics",
    "pubtator.search_literature",
    "pubtator.search_guidelines",
    "pubtator.search_biomedical_entities",
    "pubtator.lookup_variant_evidence",
    "pubtator.get_publication_metadata",
    "pubtator.get_publication_passages",
    "pubtator.preflight_review_sources",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.ground_question",
    "pubtator.retrieve_review_context_batch",
    "pubtator.get_review_audit_trail",
    "pubtator.record_review_context",
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
    assert "pubtator.retrieve_review_context" in tool_names
    assert "pubtator.get_review_passages_by_id" in tool_names
    assert "pubtator.get_neighboring_review_passages" in tool_names
    assert "pubtator.export_review_audit_bundle" in tool_names


def test_create_pubtator_mcp_readonly_profile_excludes_write_and_export_tools() -> None:
    tool_names = _tool_names("readonly")

    assert "pubtator.index_review_evidence" not in tool_names
    assert "pubtator.ground_question" not in tool_names
    assert "pubtator.record_review_context" not in tool_names
    assert "pubtator.export_review_audit_bundle" not in tool_names
    assert "pubtator.fetch_publication_annotations" not in tool_names
    assert "pubtator.fetch_pmc_annotations" not in tool_names
    assert "pubtator.retrieve_review_context_batch" in tool_names
    assert "pubtator.get_review_audit_trail" in tool_names


def test_ground_question_is_lean_and_full_but_not_readonly() -> None:
    assert "pubtator.ground_question" in _tool_names("lean")
    assert "pubtator.ground_question" in _tool_names("full")
    assert "pubtator.ground_question" not in _tool_names("readonly")
