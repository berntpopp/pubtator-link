import pytest
from pydantic import ValidationError

from pubtator_link.mcp.facade import create_pubtator_mcp


def test_review_rerag_tools_are_exposed_with_expected_names() -> None:
    mcp = create_pubtator_mcp()
    tool_names = set(mcp._tool_manager._tools)

    assert "pubtator.index_review_evidence" in tool_names
    assert "pubtator.inspect_review_index" in tool_names
    assert "pubtator.retrieve_review_context" in tool_names
    assert "pubtator.retrieve_review_context_batch" in tool_names


def test_review_tools_are_registered_with_flat_canonical_schemas() -> None:
    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    removed_suffix = "_v" + "2"
    for removed_name in (
        f"pubtator.inspect_review_index{removed_suffix}",
        f"pubtator.retrieve_review_context{removed_suffix}",
        f"pubtator.retrieve_review_context_batch{removed_suffix}",
    ):
        assert removed_name not in tools

    schema = tools["pubtator.retrieve_review_context_batch"].parameters
    properties = schema["properties"]
    assert "review_id" in properties
    assert "queries" in properties
    assert "request" not in properties
    assert properties["response_mode"]["default"] == "compact"


def test_review_rerag_tool_descriptions_explain_workflow_and_query_style() -> None:
    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    index_description = tools["pubtator.index_review_evidence"].description
    inspect_description = tools["pubtator.inspect_review_index"].description
    retrieve_description = tools["pubtator.retrieve_review_context"].description
    batch_description = tools["pubtator.retrieve_review_context_batch"].description

    assert "Call this before retrieve_review_context" in index_description
    assert "preparation_status" in index_description
    assert inspect_description.startswith("Use this when")
    assert "PMIDs, sections, passage counts, and failures" in inspect_description
    assert "short keyword query" in retrieve_description
    assert "If zero passages are returned" in retrieve_description
    assert "fetch_publication_annotations" in retrieve_description
    assert batch_description.startswith("Use this when")
    assert "multiple short review retrieval query variants" in batch_description

    for name in (
        "pubtator.fetch_publication_annotations",
        "pubtator.retrieve_review_context",
        "pubtator.index_review_evidence",
    ):
        assert tools[name].description.startswith("Use this when")


def test_review_rerag_workflow_prompt_is_registered() -> None:
    mcp = create_pubtator_mcp()

    assert "review_rerag_workflow" in mcp._prompt_manager._prompts


def test_index_review_evidence_mcp_request_rejects_unknown_prepare_mode() -> None:
    from pubtator_link.models.review_rerag import IndexReviewEvidenceRequest

    with pytest.raises(ValidationError):
        IndexReviewEvidenceRequest(
            pmids=["40234174"],
            prepare_mode="screened",
        )
