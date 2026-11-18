from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.asyncio
async def test_search_literature_paging_reaches_every_hit_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#265: limit < upstream page size must not skip hits; follow next_commands to the end."""
    from fastmcp import Client

    import pubtator_link.mcp.tools.literature as literature_tools
    from pubtator_link.mcp.facade import create_pubtator_mcp

    hits = [{"pmid": str(1000 + i), "title": f"Paper {i}"} for i in range(23)]

    class FakeClient:
        async def search_publications(self, *, page: int, **_: Any) -> dict[str, Any]:
            chunk = hits[(page - 1) * 10 : page * 10]
            return {"results": chunk, "count": 23, "page_size": 10, "total_pages": 3}

    async def fake_get_api_client() -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(literature_tools, "get_api_client", fake_get_api_client)
    mcp = create_pubtator_mcp(profile="full")

    seen: list[str] = []
    args: dict[str, Any] = {"text": "ovarian cancer", "limit": 5, "metadata": "none"}
    async with Client(mcp) as client:
        for _ in range(10):
            body = (await client.call_tool("search_literature", args)).structured_content
            assert body["returned"] == len(body["results"])
            seen += [hit["pmid"] for hit in body["results"]]
            if not body["has_more"]:
                break
            (command,) = body["_meta"]["next_commands"]
            assert command["tool"] == "search_literature"
            args = command["arguments"]

    assert seen == [hit["pmid"] for hit in hits]
    assert body["has_more"] is False
    assert "next_commands" not in body["_meta"]
