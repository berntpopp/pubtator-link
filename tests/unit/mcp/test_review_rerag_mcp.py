from pubtator_link.mcp.facade import create_pubtator_mcp


def test_review_rerag_tools_are_exposed_with_expected_names() -> None:
    mcp = create_pubtator_mcp()
    tool_names = set(mcp._tool_manager._tools)

    assert "pubtator.index_review_evidence" in tool_names
    assert "pubtator.retrieve_review_context" in tool_names
