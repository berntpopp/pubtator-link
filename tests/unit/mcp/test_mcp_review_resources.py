from __future__ import annotations

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
        async def get_passages_by_id(
            self,
            review_id: str,
            passage_ids: list[str],
            session_id: str | None,
            max_chars_per_passage: int,
        ) -> _Dumpable:
            assert review_id == "rev-1"
            assert passage_ids == ["p1"]
            assert session_id is None
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

    context_service = FakeContextService()

    passage = await review_passage_resource_impl(
        service=context_service,
        review_id="rev-1",
        passage_id="p1",
    )
    audit = await review_audit_resource_impl(service=context_service, review_id="rev-1")
    passage_audit = await review_passage_audit_resource_impl(
        service=context_service,
        review_id="rev-1",
        passage_id="p1",
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


def test_llm_context_resource_placeholder_is_empty_until_task_7() -> None:
    from pubtator_link.mcp.service_adapters import review_llm_context_resource_impl

    result = review_llm_context_resource_impl(review_id="rev-1", latest=True)

    assert result == {
        "success": True,
        "review_id": "rev-1",
        "latest": True,
        "context": [],
        "message": "LLM context resources are reserved for Task 7.",
    }
