from __future__ import annotations

import json

import pytest

from pubtator_link.mcp.review_resources import get_tool_detail_resource

EXPECTED_REVIEW_RESOURCE_TEMPLATES = {
    "pubtator://reviews/{review_id}",
    "pubtator://reviews/{review_id}/sessions",
    "pubtator://reviews/{review_id}/sessions/{session_id}",
    "pubtator://reviews/{review_id}/passages/{passage_id}",
    "pubtator://reviews/{review_id}/audit",
    "pubtator://reviews/{review_id}/audit/{passage_id}",
    "pubtator://reviews/{review_id}/llm-context",
    "pubtator://reviews/{review_id}/llm-context/latest",
    "pubtator://capabilities/tools/{tool_name}",
}


class _Dumpable:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, **_: object) -> dict[str, object]:
        return self.payload


def test_lean_mcp_registers_review_resource_templates() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp(profile="lean")

    assert EXPECTED_REVIEW_RESOURCE_TEMPLATES.issubset(mcp._resource_manager._templates)


@pytest.mark.asyncio
async def test_registered_passage_resource_reads_query_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pubtator_link.mcp.metadata as metadata
    from pubtator_link.mcp.facade import create_pubtator_mcp

    class FakeService:
        async def get_neighboring_passages(self, **kwargs: object) -> _Dumpable:
            assert kwargs == {
                "review_id": "review 1",
                "passage_id": "p/1",
                "before": 1,
                "after": 1,
                "same_section": True,
                "session_id": "session 1",
                "max_chars_per_passage": 2200,
            }
            return _Dumpable(
                {
                    "success": True,
                    "review_id": "review 1",
                    "passages": [{"passage_id": "p/1", "text": "context"}],
                    "not_found": [],
                }
            )

    async def fake_get_review_context_service() -> FakeService:
        return FakeService()

    monkeypatch.setattr(metadata, "get_review_context_service", fake_get_review_context_service)
    mcp = create_pubtator_mcp(profile="lean")

    result = await mcp.read_resource(
        "pubtator://reviews/review%201/passages/p%2F1?before=1&after=1&session_id=session+1"
    )
    payload = json.loads(result.contents[0].content)

    assert payload["passages"] == [{"passage_id": "p/1", "text": "context"}]


@pytest.mark.asyncio
async def test_registered_audit_resource_reads_session_query_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pubtator_link.mcp.metadata as metadata
    from pubtator_link.mcp.facade import create_pubtator_mcp

    class FakeService:
        async def get_audit_trail(self, **kwargs: object) -> _Dumpable:
            assert kwargs == {
                "review_id": "review 1",
                "passage_ids": ["p/1"],
                "session_id": "session 1",
                "max_chars_per_passage": 500,
            }
            return _Dumpable(
                {
                    "success": True,
                    "review_id": "review 1",
                    "items": [{"passage_id": "p/1"}],
                    "audit_block": "audit",
                }
            )

    async def fake_get_review_context_service() -> FakeService:
        return FakeService()

    monkeypatch.setattr(metadata, "get_review_context_service", fake_get_review_context_service)
    mcp = create_pubtator_mcp(profile="lean")

    result = await mcp.read_resource(
        "pubtator://reviews/review%201/audit/p%2F1?session_id=session+1"
    )
    payload = json.loads(result.contents[0].content)

    assert payload["items"] == [{"passage_id": "p/1"}]


def test_tool_detail_resource_uses_runtime_tool_metadata() -> None:
    payload = get_tool_detail_resource("pubtator.retrieve_review_context_batch")

    assert payload["name"] == "pubtator.retrieve_review_context_batch"
    assert payload["profile_visibility"] == ["lean", "full", "readonly"]
    assert payload["description"].startswith("Use this when ")


def test_tool_detail_resource_returns_not_found_for_unknown_tool() -> None:
    payload = get_tool_detail_resource("pubtator.nope")

    assert payload == {"error": "not_found", "message": "Unknown tool: pubtator.nope"}


@pytest.mark.asyncio
async def test_review_summary_resource_adapter_returns_bounded_payload() -> None:
    from pubtator_link.mcp.service_adapters import review_summary_resource_impl

    class FakeService:
        upstream_calls = 0

        async def get_summary(self, review_id: str) -> _Dumpable:
            assert review_id == "rev-1"
            return _Dumpable(
                {
                    "success": True,
                    "index": {
                        "review_id": review_id,
                        "source_count": 2,
                        "passage_count": 5,
                    },
                    "ignored_large_field": "x" * 10_000,
                }
            )

    result = await review_summary_resource_impl(service=FakeService(), review_id="rev-1")

    assert result == {
        "success": True,
        "review_id": "rev-1",
        "index": {
            "review_id": "rev-1",
            "source_count": 2,
            "passage_count": 5,
        },
    }
    assert FakeService.upstream_calls == 0


@pytest.mark.asyncio
async def test_review_session_resources_adapter_returns_list_and_detail() -> None:
    from pubtator_link.mcp.service_adapters import (
        review_session_detail_resource_impl,
        review_sessions_resource_impl,
    )

    class FakeService:
        async def list_sessions(self, *, review_id: str) -> _Dumpable:
            assert review_id == "rev-1"
            return _Dumpable(
                {
                    "success": True,
                    "sessions": [
                        {"review_id": review_id, "session_id": "sess-1", "candidate_count": 3}
                    ],
                }
            )

        async def get_status(self, *, review_id: str, session_id: str) -> _Dumpable:
            assert review_id == "rev-1"
            assert session_id == "sess-1"
            return _Dumpable(
                {
                    "success": True,
                    "manifest": {
                        "review_id": review_id,
                        "session_id": session_id,
                        "candidate_count": 3,
                    },
                }
            )

    service = FakeService()

    sessions = await review_sessions_resource_impl(service=service, review_id="rev-1")
    detail = await review_session_detail_resource_impl(
        service=service,
        review_id="rev-1",
        session_id="sess-1",
    )

    assert sessions["sessions"] == [
        {"review_id": "rev-1", "session_id": "sess-1", "candidate_count": 3}
    ]
    assert detail["session"] == {
        "review_id": "rev-1",
        "session_id": "sess-1",
        "candidate_count": 3,
    }


@pytest.mark.asyncio
async def test_review_passage_and_audit_resource_adapters_are_local_and_bounded() -> None:
    from pubtator_link.mcp.service_adapters import (
        review_audit_resource_impl,
        review_passage_audit_resource_impl,
        review_passage_resource_impl,
    )

    class FakeContextService:
        def __init__(self) -> None:
            self.passage_session_id: str | None = None
            self.audit_session_id: str | None = None
            self.neighboring_call: dict[str, object] | None = None

        async def get_passages_by_id(
            self,
            review_id: str,
            passage_ids: list[str],
            session_id: str | None,
            max_chars_per_passage: int,
        ) -> _Dumpable:
            assert review_id == "rev-1"
            assert passage_ids == ["p1"]
            self.passage_session_id = session_id
            assert max_chars_per_passage <= 2200
            return _Dumpable(
                {
                    "success": True,
                    "review_id": review_id,
                    "passages": [
                        {
                            "passage_id": "p1",
                            "pmid": "123",
                            "section": "abstract",
                            "text": "Evidence text.",
                            "source_metadata": {"large": "x" * 10_000},
                        }
                    ],
                    "not_found": [],
                }
            )

        async def get_audit_trail(self, **kwargs: object) -> _Dumpable:
            assert kwargs["review_id"] == "rev-1"
            self.audit_session_id = kwargs["session_id"]  # type: ignore[assignment]
            return _Dumpable(
                {
                    "success": True,
                    "review_id": "rev-1",
                    "items": [
                        {
                            "passage_id": "p1",
                            "stable_citation_key": "c_1",
                            "quote": "Evidence text.",
                        }
                    ],
                    "audit_block": "- c_1 PMID 123 p1 abstract: Evidence text.",
                }
            )

        async def get_neighboring_passages(self, **kwargs: object) -> _Dumpable:
            self.neighboring_call = dict(kwargs)
            return _Dumpable(
                {
                    "success": True,
                    "review_id": "rev-1",
                    "passages": [
                        {
                            "passage_id": "p0",
                            "pmid": "123",
                            "section": "abstract",
                            "text": "Neighbor text.",
                        }
                    ],
                    "not_found": [],
                }
            )

    context_service = FakeContextService()

    passage = await review_passage_resource_impl(
        service=context_service,
        review_id="rev-1",
        passage_id="p1",
        session_id="sess-1",
    )
    neighboring = await review_passage_resource_impl(
        service=context_service,
        review_id="rev-1",
        passage_id="p1",
        before=1,
        after=1,
        session_id="sess-1",
    )
    audit = await review_audit_resource_impl(service=context_service, review_id="rev-1")
    passage_audit = await review_passage_audit_resource_impl(
        service=context_service,
        review_id="rev-1",
        passage_id="p1",
        session_id="sess-1",
    )

    assert passage["passage"] == {
        "passage_id": "p1",
        "pmid": "123",
        "section": "abstract",
        "text": "Evidence text.",
    }
    assert audit["items"] == [
        {"passage_id": "p1", "stable_citation_key": "c_1", "quote": "Evidence text."}
    ]
    assert passage_audit["items"][0]["passage_id"] == "p1"
    assert context_service.passage_session_id == "sess-1"
    assert context_service.audit_session_id == "sess-1"
    assert neighboring["passages"][0]["passage_id"] == "p0"
    assert context_service.neighboring_call == {
        "review_id": "rev-1",
        "passage_id": "p1",
        "before": 1,
        "after": 1,
        "same_section": True,
        "session_id": "sess-1",
        "max_chars_per_passage": 2200,
    }


@pytest.mark.asyncio
async def test_review_audit_resource_uses_bounded_summary_not_full_export() -> None:
    from pubtator_link.mcp.service_adapters import review_audit_resource_impl

    class FakeAuditService:
        async def export_bundle(self, review_id: str, session_id: str | None = None) -> None:
            raise AssertionError("resource must not materialize the full audit bundle")

        async def get_resource_summary(self, review_id: str) -> _Dumpable:
            assert review_id == "rev-1"
            return _Dumpable(
                {
                    "success": True,
                    "review_id": review_id,
                    "preparation_status": {"complete": 2},
                    "totals": {"source_count": 2, "passage_count": 10},
                    "search_runs": [{"query": "MEFV", "large": "x" * 10_000}],
                    "retrieval_runs": [{"queries": ["MEFV"], "passage_ids": ["p1"]}],
                }
            )

    result = await review_audit_resource_impl(service=FakeAuditService(), review_id="rev-1")

    assert result["review_id"] == "rev-1"
    assert result["totals"] == {"source_count": 2, "passage_count": 10}
    assert result["search_runs"] == [{"query": "MEFV"}]


@pytest.mark.asyncio
async def test_llm_context_resource_returns_latest_snapshot_or_empty_context() -> None:
    from pubtator_link.mcp.service_adapters import review_llm_context_resource_impl

    class FakeService:
        async def get_latest_context(
            self, review_id: str, *, session_id: str | None = None
        ) -> None:
            assert review_id == "rev-1"
            assert session_id == "sess-1"
            return None

    result = await review_llm_context_resource_impl(
        service=FakeService(),
        review_id="rev-1",
        latest=True,
        session_id="sess-1",
    )

    assert result["success"] is True
    assert result["latest"] is True
    assert result["context"]["review_id"] == "rev-1"
    assert result["context"]["context_id"] is None
    assert result["context"]["selected_passage_ids"] == []


@pytest.mark.asyncio
async def test_registered_llm_context_resource_reads_session_query_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pubtator_link.mcp.metadata as metadata
    from pubtator_link.mcp.facade import create_pubtator_mcp
    from pubtator_link.models.review_rerag import ReviewLlmContext

    class FakeService:
        async def get_latest_context(
            self, review_id: str, *, session_id: str | None = None
        ) -> ReviewLlmContext:
            assert review_id == "review 1"
            assert session_id == "session 1"
            return ReviewLlmContext(
                context_id="ctx-1",
                review_id=review_id,
                session_id=session_id,
                selected_passage_ids=["p/1"],
                created_at="2026-05-03T00:00:00Z",
                updated_at="2026-05-03T00:00:00Z",
            )

    async def fake_get_llm_review_context_service() -> FakeService:
        return FakeService()

    monkeypatch.setattr(
        metadata,
        "get_llm_review_context_service",
        fake_get_llm_review_context_service,
    )
    mcp = create_pubtator_mcp(profile="lean")

    result = await mcp.read_resource(
        "pubtator://reviews/review%201/llm-context/latest?session_id=session+1"
    )
    payload = json.loads(result.contents[0].content)

    assert payload["context"]["context_id"] == "ctx-1"
    assert payload["context"]["selected_passage_ids"] == ["p/1"]
