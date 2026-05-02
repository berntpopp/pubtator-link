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
    assert properties["dry_run"]["default"] is False
    assert properties["min_passages_per_pmid"]["default"] == 0
    assert "prioritize_pmids" in properties
    inspect_properties = tools["pubtator.inspect_review_index"].parameters["properties"]
    assert inspect_properties["include_metadata"]["default"] is False
    assert inspect_properties["metadata"]["default"] == "basic"


def test_review_tools_accept_context_without_exposing_ctx_parameter() -> None:
    mcp = create_pubtator_mcp()
    tool = mcp._tool_manager._tools["pubtator.retrieve_review_context_batch"]
    schema = tool.parameters

    assert "ctx" not in schema["properties"]


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


def test_index_review_evidence_mcp_schema_does_not_advertise_candidate_fast() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["pubtator.index_review_evidence"].parameters

    assert "prepare_mode" not in schema["properties"]
    assert "candidate_fast" not in str(schema)


@pytest.mark.asyncio
async def test_index_review_evidence_accepts_legacy_prepare_mode_without_schema_exposure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pubtator_link.mcp.tools.review as review_tools
    from pubtator_link.models.review_rerag import PreparationStatus

    class FakeRepository:
        async def research_session_exists(self, review_id: str, session_id: str) -> bool:
            return True

        async def preparation_job_statuses(self, review_id: str, source_ids: list[str]):
            return {}

        async def preparation_status(self, review_id: str, *, session_id: str | None = None):
            return PreparationStatus(queued=1)

        async def link_review_session_source(
            self, review_id: str, session_id: str, source_id: str
        ) -> None:
            return None

    class FakeQueue:
        repository = FakeRepository()

        async def enqueue_pmid(self, review_id: str, pmid: str):
            return "newly_queued"

        async def enqueue_curated_url(self, review_id: str, url: str):
            return "newly_queued"

    async def fake_get_review_queue():
        return FakeQueue()

    monkeypatch.setattr(review_tools, "get_review_queue", fake_get_review_queue)
    mcp = create_pubtator_mcp()
    tool = mcp._tool_manager._tools["pubtator.index_review_evidence"]

    result = await tool.run(
        {
            "review_id": "review-1",
            "pmids": ["40234174"],
            "prepare_mode": "selected",
        }
    )

    assert "prepare_mode" not in tool.parameters["properties"]
    assert result.structured_content["success"] is True
    assert result.structured_content["queued"] == 1
