from __future__ import annotations


def test_server_instructions_are_tool_search_friendly() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    instructions = mcp.instructions or ""

    assert instructions.startswith(
        "PubTator-Link grounds biomedical literature work: search PubMed/PubTator, "
        "fetch compact passages or raw BioC, inspect review indexes, retrieve "
        "review-scoped RAG context, find entity relations, and submit/get text annotations."
    )
    assert len(instructions.encode("utf-8")) < 2048
    assert "pubtator.get_server_capabilities" in instructions
    assert "search -> index -> inspect -> retrieve" in instructions
    assert "raw full BioC can be large" in instructions
    assert "not for diagnosis" in instructions


def test_capabilities_resource_advertises_grounding_workflows() -> None:
    from pubtator_link.mcp.resources import get_capabilities_resource

    capabilities = get_capabilities_resource()

    assert "recommended_workflows" in capabilities
    assert "tool_groups" in capabilities
    assert "large_output_guidance" in capabilities
    assert "review_rerag" in capabilities
    assert "search -> index -> inspect -> retrieve" in capabilities["recommended_workflows"][0]
    assert (
        "pubtator.get_publication_passages" in capabilities["tool_groups"]["publication_grounding"]
    )
    assert "pubtator.inspect_review_index" in capabilities["tool_groups"]["review_grounding"]


def test_curated_facade_registers_pubtator_tools() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tool_names = set(mcp._tool_manager._tools.keys())

    assert "pubtator.search_literature" in tool_names
    assert "pubtator.fetch_publication_annotations" in tool_names
    assert "pubtator.fetch_pmc_annotations" in tool_names
    assert "pubtator.search_biomedical_entities" in tool_names
    assert "pubtator.find_entity_relations" in tool_names
    assert "pubtator.submit_text_annotation" in tool_names
    assert "pubtator.get_text_annotation_results" in tool_names
    assert "pubtator.get_publication_passages" in tool_names
    assert "pubtator.estimate_publication_context" in tool_names
    assert "pubtator.inspect_review_index" in tool_names
    assert "pubtator.retrieve_review_context_batch" in tool_names
    assert "pubtator.get_server_capabilities" in tool_names
    assert "pubtator.clear_api_cache" not in tool_names


def test_curated_facade_registers_resources_and_prompts() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()

    assert "pubtator://capabilities" in mcp._resource_manager._resources
    assert "pubtator://bioconcepts" in mcp._resource_manager._resources
    assert "pubtator://compliance/research-use" in mcp._resource_manager._resources
    assert "search_biomedical_literature" in mcp._prompt_manager._prompts
    assert "annotate_research_text" in mcp._prompt_manager._prompts


def test_tool_metadata_is_research_scoped() -> None:
    from pubtator_link.mcp.resources import RESEARCH_USE_NOTICE

    assert "not for diagnosis" in RESEARCH_USE_NOTICE
    assert "clinical decision support" in RESEARCH_USE_NOTICE


def test_public_hosted_tools_have_expected_annotations() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    for name in (
        "pubtator.search_literature",
        "pubtator.fetch_publication_annotations",
        "pubtator.search_biomedical_entities",
        "pubtator.find_entity_relations",
        "pubtator.get_server_capabilities",
    ):
        tool = tools[name]
        assert "Use this when" in tool.description
        assert "not for diagnosis" in tool.description
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False


def test_open_world_tools_are_marked_open_world() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tool = mcp._tool_manager._tools["pubtator.search_literature"]

    assert tool.annotations.openWorldHint is True


def test_capabilities_resource_tool_names_are_registered() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp
    from pubtator_link.mcp.resources import get_capabilities_resource

    mcp = create_pubtator_mcp()
    registered_tools = set(mcp._tool_manager._tools)
    capabilities = get_capabilities_resource()
    advertised_tools = set(capabilities["tools"])
    for group_tools in capabilities["tool_groups"].values():
        advertised_tools.update(group_tools)
    advertised_tools.update(capabilities["review_rerag"]["tools"])

    assert advertised_tools <= registered_tools
