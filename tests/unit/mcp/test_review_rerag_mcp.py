from pubtator_link.mcp.facade import create_pubtator_mcp


def test_review_rerag_tools_are_exposed_with_expected_names() -> None:
    mcp = create_pubtator_mcp()
    tool_names = set(mcp._tool_manager._tools)

    assert "pubtator.index_review_evidence" in tool_names
    assert "pubtator.retrieve_review_context" in tool_names


def test_review_rerag_tool_descriptions_explain_workflow_and_query_style() -> None:
    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    index_description = tools["pubtator.index_review_evidence"].description
    retrieve_description = tools["pubtator.retrieve_review_context"].description

    assert "Call this before retrieve_review_context" in index_description
    assert "preparation_status" in index_description
    assert "short keyword query" in retrieve_description
    assert "If zero passages are returned" in retrieve_description
    assert "fetch_publication_annotations" in retrieve_description


def test_review_rerag_workflow_prompt_is_registered() -> None:
    mcp = create_pubtator_mcp()

    assert "review_rerag_workflow" in mcp._prompt_manager._prompts
