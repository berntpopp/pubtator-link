from __future__ import annotations


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
