from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from pubtator_link.mcp.profiles import (
    LEAN_TOOLS,
    WRITE_TOOLS,
    MCPToolProfile,
    filter_reachable_hints,
    normalize_mcp_profile,
    reachable_tools,
    tool_names_for_profile,
)

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
    assert full_names >= EXPECTED_WRITE_TOOLS
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


def _hinted_tool_names(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "tool" and isinstance(item, str):
                yield item
            elif key in {"next_tools", "next_commands"} and isinstance(item, list):
                for command in item:
                    if isinstance(command, str):
                        match = re.match(r"([a-z][a-z0-9_]*)", command)
                        if match is not None:
                            yield match.group(1)
                    yield from _hinted_tool_names(command)
            else:
                yield from _hinted_tool_names(item)
    elif isinstance(value, list):
        for item in value:
            yield from _hinted_tool_names(item)


def _tool_tokens(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(re.findall(r"[a-z][a-z0-9_]*", value))
    if isinstance(value, Mapping):
        tokens: set[str] = set()
        for key, item in value.items():
            tokens |= _tool_tokens(key)
            tokens |= _tool_tokens(item)
        return tokens
    if isinstance(value, list):
        tokens = set()
        for item in value:
            tokens |= _tool_tokens(item)
        return tokens
    return set()


def test_reachable_tools_uses_profile_inventory_and_preserves_preference_order() -> None:
    preferred = (
        "preflight_review_sources",
        "index_review_evidence",
        "get_publication_passages",
    )

    assert reachable_tools("readonly", preferred) == [
        "preflight_review_sources",
        "get_publication_passages",
    ]


def test_filter_reachable_hints_removes_unavailable_tools_from_next_steps() -> None:
    payload = {
        "next_steps": [
            "Continue with index_review_evidence for durable retrieval.",
            "Use get_publication_passages for direct retrieval.",
        ]
    }

    assert filter_reachable_hints("readonly", payload) == {
        "next_steps": ["Use get_publication_passages for direct retrieval."]
    }


def test_filter_reachable_hints_preserves_non_hint_tool_fields() -> None:
    payload = {
        "results": [
            {
                "tool": "index_review_evidence",
                "text": "This evidence record names index_review_evidence historically.",
            }
        ],
        "_meta": {
            "next_commands": ["Use index_review_evidence after selecting the final PMID corpus."]
        },
    }

    result = filter_reachable_hints("readonly", payload)

    assert result["results"] == payload["results"]
    assert result["_meta"]["next_commands"] == []


def test_readonly_capabilities_resources_and_prompts_only_reference_registered_tools() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp
    from pubtator_link.mcp.resources import get_capabilities_resource

    mcp = create_pubtator_mcp(profile="readonly")
    registered_tools = set(mcp._tool_manager._tools)
    capabilities = get_capabilities_resource(
        details=[
            "llm_driver_contract",
            "recommended_workflows",
            "discovery_workflow",
            "core_tools",
            "advanced_tools",
            "review_rerag",
            "workflow_help",
        ],
        profile="readonly",
    )
    resource_payloads = [resource.fn() for resource in mcp._resource_manager._resources.values()]
    payloads = [capabilities, *resource_payloads]

    for payload in payloads:
        assert set(_hinted_tool_names(payload)) <= registered_tools

    unavailable = set(WRITE_TOOLS) - registered_tools
    for payload in payloads:
        payload_text = json.dumps(payload, sort_keys=True, default=str)
        assert not (set(re.findall(r"[a-z][a-z0-9_]*", payload_text)) & unavailable)

    for prompt in mcp._prompt_manager._prompts.values():
        prompt_text = prompt.fn()
        assert not (set(re.findall(r"[a-z][a-z0-9_]*", prompt_text)) & unavailable)


@pytest.mark.parametrize("profile", ["lean", "full", "readonly"])
def test_profile_advice_surfaces_only_advertise_reachable_tools(
    profile: MCPToolProfile,
) -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp
    from pubtator_link.mcp.resources import get_capabilities_resource

    mcp = create_pubtator_mcp(profile=profile)
    registered_tools = set(mcp._tool_manager._tools)
    unavailable = tool_names_for_profile("full") - registered_tools
    capabilities = get_capabilities_resource(
        details=[
            "llm_driver_contract",
            "tools",
            "workflow",
            "workflow_help",
            "recommended_workflows",
            "discovery_workflow",
            "core_tools",
            "advanced_tools",
            "review_rerag",
            "sample_calls",
            "schema_policy",
            "preferred_tool_names",
        ],
        profile=profile,
    )
    detail = capabilities["details"]

    for advice in [
        mcp.instructions or "",
        *(prompt.fn() for prompt in mcp._prompt_manager._prompts.values()),
        capabilities,
    ]:
        assert not (_tool_tokens(advice) & unavailable)

    for workflow in (
        capabilities["core_workflow_tools"],
        capabilities["workflow_bundles"]["literature_graph"]["tools"],
        detail["llm_driver_contract"]["core_workflow_tools"],
        detail["workflow"]["recommended_tools"],
        detail["workflow_help"]["tool_sequence"],
    ):
        assert set(workflow) <= registered_tools

    if profile == "lean":
        assert detail["workflow"]["recommended_tools"] == [
            "search_literature",
            "preflight_review_sources",
            "index_review_evidence",
            "inspect_review_index",
            "get_review_context_batch",
        ]
    if profile == "readonly":
        assert detail["workflow"]["recommended_tools"] == [
            "search_literature",
            "preflight_review_sources",
            "get_publication_passages",
        ]


@pytest.mark.asyncio
async def test_readonly_capabilities_tool_redacts_writes_from_every_supported_detail() -> None:
    from fastmcp import Client

    from pubtator_link.mcp.facade import create_pubtator_mcp

    details = [
        "server",
        "transport",
        "endpoint",
        "llm_driver_contract",
        "tools",
        "workflow_help",
        "sample_calls",
        "schema_policy",
        "preferred_tool_names",
    ]
    mcp = create_pubtator_mcp(profile="readonly")

    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_server_capabilities",
            {"details": details},
            raise_on_error=False,
        )

    assert result.is_error is False
    payload = result.structured_content
    assert isinstance(payload, dict)
    assert set(details) <= set(payload["details"])
    assert payload["core_workflow_tools"] == [
        "search_literature",
        "preflight_review_sources",
        "get_publication_passages",
    ]
    serialized = json.dumps(payload, sort_keys=True)
    assert not (set(re.findall(r"[a-z][a-z0-9_]*", serialized)) & set(WRITE_TOOLS))


def test_readonly_capabilities_workflow_detail_is_a_contiguous_direct_retrieval_path() -> None:
    from pubtator_link.mcp.resources import get_capabilities_resource

    payload = get_capabilities_resource(details=["workflow"], profile="readonly")

    assert payload["core_workflow_tools"] == [
        "search_literature",
        "preflight_review_sources",
        "get_publication_passages",
    ]
    assert payload["details"]["workflow"]["recommended_tools"] == [
        "search_literature",
        "preflight_review_sources",
        "get_publication_passages",
    ]


def test_readonly_server_advice_and_schema_keep_direct_passage_retrieval_reachable() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp
    from pubtator_link.mcp.resources import get_capabilities_resource

    mcp = create_pubtator_mcp(profile="readonly")
    unavailable = set(WRITE_TOOLS) - set(mcp._tool_manager._tools)

    assert "search -> preflight -> get_publication_passages" in mcp.instructions
    assert not (set(re.findall(r"[a-z][a-z0-9_]*", mcp.instructions)) & unavailable)
    for tool in mcp._tool_manager._tools.values():
        schema_text = f"{tool.description} {json.dumps(tool.parameters, sort_keys=True)}"
        assert not (set(re.findall(r"[a-z][a-z0-9_]*", schema_text)) & unavailable)

    bundles = get_capabilities_resource(profile="readonly")["workflow_bundles"]
    assert bundles["literature_graph"]["tools"] == [
        "search_literature",
        "build_topic_literature_map",
        "get_publication_citation_graph",
        "find_related_evidence_candidates",
        "preflight_review_sources",
        "get_publication_passages",
    ]
