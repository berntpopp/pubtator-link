"""Response-Envelope v1.2: tool results validate against the published JSON Schema.

The schema is vendored from https://github.com/berntpopp/genefoundry-envelope at tag v1.2.0.

Every registered tool is run through the real MCP egress. The tool body's service call
(``run_mcp_tool``) is replaced by a canned payload, so each tool's own argument handling
and post-processing run -- including every ``include_meta=false`` path, which must not
remove a required ``_meta`` field.

Scope: this checks the ``_meta`` contract (v1 section 4, v1.2) of every tool. The payload is
canned, so the frame rule (``result`` or ``results``) is checked for real payloads only where
a test below runs a real tool body (``search_literature``).
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import pkgutil
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastmcp import Client

import pubtator_link.mcp.tools as tools_package
from pubtator_link.mcp.egress_meta import OPS_TOOLS
from pubtator_link.mcp.facade import create_pubtator_mcp

SCHEMA_PATH = Path(__file__).with_name("envelope-v1.2.schema.json")
SCHEMA_SHA256 = "c3c47e20d7dd189aac2568fc963b5514d7a5ac2c3e5f21d126f42c96d1ad1ae3"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
REQUIRED_META = {"request_id", "elapsed_ms", "source", "data_version", "retrieved_at"}

CANNED = {
    "success": True,
    "results": [{"pmid": "33454820", "rrf_score": 0.5}],
    "provider_status": [{"provider": "lexical"}],
    "_meta": {"next_commands": [], "diagnostics": {"detail": "optional"}},
}


def _tool_modules() -> list[Any]:
    return [
        importlib.import_module(info.name)
        for info in pkgutil.walk_packages(tools_package.__path__, tools_package.__name__ + ".")
    ]


@pytest.fixture
def mcp(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def canned_run(tool_name: str, func: Any, **_: Any) -> dict[str, Any]:
        payload = copy.deepcopy(CANNED)
        payload["_meta"]["tool"] = tool_name
        return payload

    for module in _tool_modules():
        if hasattr(module, "run_mcp_tool"):
            monkeypatch.setattr(module, "run_mcp_tool", canned_run)
    return create_pubtator_mcp(profile="full")


def _example_arguments(tool: Any, **extra: Any) -> dict[str, Any]:
    """A valid call built from the tool's own schema examples, as the behaviour gate does."""
    properties = tool.parameters.get("properties", {})
    arguments = {
        name: properties[name]["examples"][0] for name in tool.parameters.get("required", [])
    }
    return arguments | {name: value for name, value in extra.items() if name in properties}


async def _call(mcp: Any, tool: str, arguments: dict[str, Any]) -> Any:
    async with Client(mcp) as client:
        return await client.call_tool(tool, arguments, raise_on_error=False)


def test_vendored_schema_is_the_v1_2_0_release() -> None:
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_SHA256


@pytest.mark.parametrize("include_meta", [True, False])
async def test_every_tool_leaves_with_the_required_meta(mcp: Any, include_meta: bool) -> None:
    tools = await mcp.list_tools()
    assert len(tools) > 40
    for tool in tools:
        result = await _call(mcp, tool.name, _example_arguments(tool, include_meta=include_meta))
        envelope = result.structured_content
        assert envelope["success"] is True, (tool.name, envelope)
        assert json.loads(result.content[0].text) == envelope, tool.name  # the text mirror
        if tool.name in OPS_TOOLS:
            assert {"request_id", "elapsed_ms"} <= set(envelope["_meta"]), tool.name
            continue
        jsonschema.validate(envelope, SCHEMA)
        meta = envelope["_meta"]
        assert set(meta) >= REQUIRED_META, tool.name
        assert all(meta[key] for key in REQUIRED_META - {"elapsed_ms"}), tool.name
        assert meta["retrieved_at"].endswith("Z")


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [("search_literature", {"wrong_argument": 1}), ("no_such_tool", {})],
)
async def test_error_validates(mcp: Any, tool: str, arguments: dict[str, Any]) -> None:
    result = await _call(mcp, tool, arguments)
    assert result.is_error is True
    jsonschema.validate(result.structured_content, SCHEMA)


async def test_include_meta_false_drops_only_the_optional_meta(mcp: Any) -> None:
    """The stripping paths still strip; the egress then restores what is required."""
    stripped = 0
    for tool in await mcp.list_tools():
        if "include_meta" not in tool.parameters.get("properties", {}):
            continue
        arguments = _example_arguments(tool, include_meta=False)
        envelope = (await _call(mcp, tool.name, arguments)).structured_content
        if "provider_status" not in envelope:  # this tool strips in its own body
            stripped += 1
            assert set(envelope["_meta"]) == REQUIRED_META, tool.name
            assert "rrf_score" not in envelope["results"][0], tool.name
    assert stripped >= 5


@pytest.mark.parametrize("include_meta", [True, False])
async def test_search_literature_real_path_validates(
    monkeypatch: pytest.MonkeyPatch, include_meta: bool
) -> None:
    """search_literature drops its ``_meta`` inside the service adapter, not the tool body."""
    import pubtator_link.mcp.tools.literature as literature_tools

    class FakeClient:
        async def search_publications(self, **_: Any) -> dict[str, Any]:
            hits = [{"pmid": "1001", "title": "Paper"}]
            return {"results": hits, "count": 1, "page_size": 10, "total_pages": 1}

    async def fake_get_api_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(literature_tools, "get_api_client", fake_get_api_client)
    arguments = {"text": "ovarian cancer", "metadata": "none", "include_meta": include_meta}
    result = await _call(create_pubtator_mcp(profile="full"), "search_literature", arguments)
    envelope = result.structured_content
    assert envelope["success"] is True
    jsonschema.validate(envelope, SCHEMA)
    assert set(envelope["_meta"]) >= REQUIRED_META
    assert ("next_commands" in envelope["_meta"] or "cache_key" in envelope) is include_meta


async def test_cache_hit_keeps_the_original_fetch_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from pubtator_link.mcp.egress_meta import EgressCall
    from pubtator_link.services import publication_service
    from pubtator_link.services.publication_service import PublicationService

    client = AsyncMock()
    client.search_publications.return_value = {"results": [], "count": 0, "total_pages": 0}
    service = PublicationService(client)
    monkeypatch.setattr(publication_service, "utc_now", lambda: "2026-01-01T00:00:00Z")

    async def retrieved_at() -> str:
        call = EgressCall()
        await service.search_publications("BRCA1", 1)
        stamped = await call.stamp({"success": True}, tool_name="search_literature", arguments={})
        return str(stamped["_meta"]["retrieved_at"])

    assert await retrieved_at() == "2026-01-01T00:00:00Z"  # the fetch that filled the cache
    assert await retrieved_at() == "2026-01-01T00:00:00Z"  # the hit keeps it
    assert client.search_publications.await_count == 1

    # Without a cached value the start of the call dates the result.
    fresh = await EgressCall().stamp({"success": True}, tool_name="get_mesh", arguments={})
    assert fresh["_meta"]["retrieved_at"] > "2026-01-01T00:00:00Z"
    # Ops tools and errors carry request_id and elapsed_ms only.
    ops = await EgressCall().stamp({"success": True}, tool_name="diagnostics", arguments={})
    assert set(ops["_meta"]) == {"request_id", "elapsed_ms"}


async def test_review_index_results_are_dated_by_their_stored_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from pubtator_link.api.routes.dependencies import review
    from pubtator_link.mcp.egress_meta import EgressCall

    class _Connection:
        async def fetchval(self, _sql: str, review_id: str) -> datetime | None:
            return datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC) if review_id == "rev_1" else None

        async def __aenter__(self) -> _Connection:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    class _Repository:
        def _acquire(self) -> _Connection:
            return _Connection()

    monkeypatch.setattr(review, "_review_repository", _Repository())

    async def retrieved_at(review_id: str) -> str:
        stamped = await EgressCall().stamp(
            {"success": True}, tool_name="get_review_context", arguments={"review_id": review_id}
        )
        return str(stamped["_meta"]["retrieved_at"])

    assert await retrieved_at("rev_1") == "2026-03-04T05:06:07Z"
    assert await retrieved_at("rev_empty") > "2026-03-04T05:06:07Z"  # nothing stored: call time
