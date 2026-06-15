import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from pubtator_link.mcp.facade import create_pubtator_mcp


def test_review_rerag_tools_are_exposed_with_expected_names() -> None:
    mcp = create_pubtator_mcp(profile="full")
    tool_names = set(mcp._tool_manager._tools)

    assert "index_review_evidence" in tool_names
    assert "inspect_review_index" in tool_names
    assert "get_review_context" in tool_names
    assert "get_review_context_batch" in tool_names


def test_review_tools_are_registered_with_flat_canonical_schemas() -> None:
    mcp = create_pubtator_mcp(profile="full")
    tools = mcp._tool_manager._tools

    removed_suffix = "_v" + "2"
    for removed_name in (
        f"inspect_review_index{removed_suffix}",
        f"get_review_context{removed_suffix}",
        f"get_review_context_batch{removed_suffix}",
    ):
        assert removed_name not in tools

    schema = tools["get_review_context_batch"].parameters
    properties = schema["properties"]
    assert "review_id" in properties
    assert "queries" in properties
    assert "request" not in properties
    assert properties["response_mode"]["default"] == "compact"
    assert properties["dry_run"]["default"] is False
    assert properties["min_passages_per_pmid"]["default"] == 0
    assert properties["include_diagnostics"]["default"] is False
    assert "prioritize_pmids" in properties
    inspect_properties = tools["inspect_review_index"].parameters["properties"]
    assert inspect_properties["include_metadata"]["default"] is False
    assert inspect_properties["metadata"]["default"] == "basic"


def test_batch_response_mode_schema_includes_quotes() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["get_review_context_batch"].parameters

    assert "quotes" in schema["properties"]["response_mode"]["enum"]


def test_inspect_review_index_schema_exposes_pagination_args() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["inspect_review_index"].parameters

    assert schema["properties"]["limit"]["default"] == 50
    assert "cursor" in schema["properties"]


def test_retrieve_review_context_batch_schema_uses_auto_fit_budget_defaults() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["get_review_context_batch"].parameters

    assert "max_chars" not in schema.get("required", [])
    assert "max_response_chars" not in schema.get("required", [])
    max_chars_schema = schema["properties"]["max_chars"]
    assert max_chars_schema.get("default") is None
    any_of = max_chars_schema.get("anyOf", [])
    assert (
        any(option.get("type") == "null" for option in any_of)
        or max_chars_schema.get("type") == "null"
    )
    assert schema["properties"]["max_response_chars"]["default"] == "auto"


def test_retrieve_batch_schema_exposes_verbosity_and_auto_response_budget() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["get_review_context_batch"].parameters

    assert schema["properties"]["verbosity"]["default"] == "standard"
    assert set(schema["properties"]["verbosity"]["enum"]) == {"lean", "standard", "full"}
    assert schema["properties"]["max_response_chars"]["default"] == "auto"


def test_review_tools_accept_context_without_exposing_ctx_parameter() -> None:
    mcp = create_pubtator_mcp()
    tool = mcp._tool_manager._tools["get_review_context_batch"]
    schema = tool.parameters

    assert "ctx" not in schema["properties"]


def test_review_rerag_tool_descriptions_explain_workflow_and_query_style() -> None:
    mcp = create_pubtator_mcp(profile="full")
    tools = mcp._tool_manager._tools

    index_description = tools["index_review_evidence"].description
    inspect_description = tools["inspect_review_index"].description
    retrieve_description = tools["get_review_context"].description
    batch_description = tools["get_review_context_batch"].description

    assert "Call this before get_review_context_batch" in index_description
    assert "preparation_status" in index_description
    assert inspect_description.startswith("Use this when")
    assert "PMIDs, sections, passage counts, and failures" in inspect_description
    assert "short keyword query" in retrieve_description
    assert "If zero passages are returned" in retrieve_description
    assert "get_publication_annotations" in retrieve_description
    assert batch_description.startswith("Use this when")
    assert "multiple short review retrieval query variants" in batch_description

    for name in (
        "get_publication_annotations",
        "get_review_context",
        "index_review_evidence",
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
    schema = mcp._tool_manager._tools["index_review_evidence"].parameters

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
    tool = mcp._tool_manager._tools["index_review_evidence"]

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


@pytest.mark.asyncio
async def test_record_review_context_propagates_service_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pubtator_link.mcp.tools.review as review_tools

    class FakeService:
        async def record_context(self, *_args, **_kwargs):
            raise RuntimeError("Review repository does not support context recording.")

    async def fake_get_llm_review_context_service() -> FakeService:
        return FakeService()

    monkeypatch.setattr(
        review_tools,
        "get_llm_review_context_service",
        fake_get_llm_review_context_service,
    )
    tool = create_pubtator_mcp()._tool_manager._tools["record_review_context"]

    with pytest.raises(ToolError):
        await tool.run(
            {
                "review_id": "review-1",
                "event_type": "passage_selected",
                "passage_ids": ["PMID:1:abstract:0"],
            }
        )


@pytest.mark.asyncio
async def test_record_review_context_rejects_empty_passage_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pubtator_link.mcp.tools.review as review_tools

    class FakeService:
        async def record_context(self, *_args, **_kwargs):
            raise AssertionError("empty records should fail before service call")

    async def fake_get_llm_review_context_service() -> FakeService:
        return FakeService()

    monkeypatch.setattr(
        review_tools,
        "get_llm_review_context_service",
        fake_get_llm_review_context_service,
    )
    tool = create_pubtator_mcp()._tool_manager._tools["record_review_context"]

    with pytest.raises(ToolError):
        await tool.run({"review_id": "review-1", "event_type": "passage_selected"})


@pytest.mark.asyncio
async def test_record_review_context_records_audit_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pubtator_link.mcp.tools.review as review_tools

    recorded: list[tuple[str, object]] = []

    class _Dumpable:
        def model_dump(self, **_: object) -> dict[str, object]:
            return {
                "success": True,
                "context": {
                    "context_id": "ctx-1",
                    "review_id": "review-1",
                    "selected_passage_ids": ["PMID:1:abstract:0"],
                },
                "event": {
                    "event_id": "event-1",
                    "review_id": "review-1",
                    "event_type": "passage_selected",
                    "passage_ids": ["PMID:1:abstract:0"],
                },
            }

    class FakeService:
        async def record_context(self, review_id: str, request: object) -> _Dumpable:
            recorded.append((review_id, request))
            return _Dumpable()

    async def fake_get_llm_review_context_service() -> FakeService:
        return FakeService()

    monkeypatch.setattr(
        review_tools,
        "get_llm_review_context_service",
        fake_get_llm_review_context_service,
    )
    tool = create_pubtator_mcp()._tool_manager._tools["record_review_context"]

    result = await tool.run(
        {
            "review_id": "review-1",
            "event_type": "passage_selected",
            "passage_ids": ["PMID:1:abstract:0"],
            "selected_passage_ids": ["PMID:1:abstract:0"],
            "session_id": "session-1",
            "summary": "used in answer",
        }
    )

    assert result.structured_content["success"] is True
    assert result.structured_content["context"]["context_id"] == "ctx-1"
    assert recorded[0][0] == "review-1"
    assert recorded[0][1].passage_ids == ["PMID:1:abstract:0"]
    assert recorded[0][1].selected_passage_ids == ["PMID:1:abstract:0"]


@pytest.mark.asyncio
async def test_index_review_evidence_reports_progress_when_waiting(monkeypatch) -> None:
    progress_calls: list[tuple[float, float | None]] = []

    class FakeContext:
        async def report_progress(self, progress: float, total: float | None = None) -> None:
            progress_calls.append((progress, total))

        async def warning(self, _message: str) -> None:
            return None

    async def fake_impl(**_kwargs):
        return {
            "success": True,
            "review_id": "rev-1",
            "queued": 1,
            "already_prepared": 0,
            "preparation_status": {
                "queued": 0,
                "running": 0,
                "complete": 1,
                "partial": 0,
                "failed": 0,
            },
            "waited_ms": 10,
            "timed_out": False,
        }

    async def fake_get_review_queue():
        return object()

    monkeypatch.setattr("pubtator_link.mcp.tools.review.index_review_evidence_impl", fake_impl)
    monkeypatch.setattr("pubtator_link.mcp.tools.review.get_review_queue", fake_get_review_queue)

    tool = create_pubtator_mcp()._tool_manager._tools["index_review_evidence"]
    await tool.fn(
        review_id="rev-1",
        pmids=["40234174"],
        wait_until_ready=True,
        ctx=FakeContext(),
    )

    assert progress_calls[0] == (0, 100)
    assert progress_calls[-1] == (100, 100)
