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


def test_common_mcp_tools_are_flat_and_unversioned() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools
    tool_names = set(tools)
    removed_suffix = "_v" + "2"

    assert not any(name.endswith(removed_suffix) for name in tool_names)

    canonical_flat_tools = {
        "pubtator.search_literature": ("text",),
        "pubtator.search_biomedical_entities": ("query",),
        "pubtator.get_publication_passages": ("pmids",),
        "pubtator.inspect_review_index": ("review_id",),
        "pubtator.retrieve_review_context": ("review_id", "question"),
        "pubtator.retrieve_review_context_batch": ("review_id", "queries"),
    }

    for name, required_properties in canonical_flat_tools.items():
        assert name in tools
        properties = tools[name].parameters["properties"]
        assert "request" not in properties
        for property_name in required_properties:
            assert property_name in properties

    batch_schema = tools["pubtator.retrieve_review_context_batch"].parameters
    assert batch_schema["properties"]["response_mode"]["default"] == "compact"
    search_schema = tools["pubtator.search_literature"].parameters
    assert "publication_types" in search_schema["properties"]
    assert "year_min" in search_schema["properties"]
    assert "year_max" in search_schema["properties"]


def test_public_mcp_tools_use_flat_arguments_consistently() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    required_properties = {
        "pubtator.fetch_publication_annotations": ("pmids",),
        "pubtator.estimate_publication_context": ("pmids",),
        "pubtator.fetch_pmc_annotations": ("pmcids",),
        "pubtator.find_entity_relations": ("entity_id",),
        "pubtator.submit_text_annotation": ("text",),
        "pubtator.get_text_annotation_results": ("session_id",),
        "pubtator.index_review_evidence": ("review_id",),
    }
    for name, expected_properties in required_properties.items():
        properties = tools[name].parameters["properties"]
        assert "request" not in properties
        for property_name in expected_properties:
            assert property_name in properties


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


def test_capabilities_include_context_management_cheatsheet() -> None:
    from pubtator_link.mcp.resources import get_capabilities_resource

    capabilities = get_capabilities_resource()

    assert "sample_calls" in capabilities
    assert "output_cheatsheet" in capabilities
    assert "budgeting_defaults" in capabilities
    assert capabilities["budgeting_defaults"]["batch_response_mode"] == "compact"
    removed_suffix = "_v" + "2"
    assert removed_suffix not in repr(capabilities)
    assert "pubtator.search_literature" in capabilities["tools"]
    assert "pubtator.retrieve_review_context_batch" in capabilities["sample_calls"]
    assert capabilities["large_output_guidance"]["prefer"] == "pubtator.get_publication_passages"
    assert capabilities["output_cheatsheet"]["batch_merged_passages"] == (
        "merged_context_pack.passages[]"
    )
