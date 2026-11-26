"""PMID tools accept a PMCID or DOI and echo the conversion (genefoundry-router #319)."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

import pubtator_link.mcp.argument_aliases as aliases
import pubtator_link.mcp.tools.publications as publication_tools
from pubtator_link.mcp.facade import create_pubtator_mcp
from pubtator_link.models.discovery import ArticleIdConversionRecord, ArticleIdConversionResponse


class FakeDiscovery:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.calls: list[list[str]] = []

    async def map_article_ids(self, ids: list[str]) -> ArticleIdConversionResponse:
        self.calls.append(list(ids))
        records = [
            ArticleIdConversionRecord(
                input_id=i,
                input_kind="auto",
                status="resolved" if i in self.mapping else "unresolved",
                pmid=self.mapping.get(i),
            )
            for i in ids
        ]
        return ArticleIdConversionResponse(records=records)


@pytest.fixture
def discovery(monkeypatch: pytest.MonkeyPatch) -> FakeDiscovery:
    fake = FakeDiscovery({"PMC3518823": "23248578", "10.1038/ng.2500": "23248578"})

    async def get_fake() -> FakeDiscovery:
        return fake

    monkeypatch.setattr(aliases, "get_discovery_service", get_fake)
    monkeypatch.setattr(aliases, "_resolved_pmids", {})
    return fake


@pytest.fixture
def passages_seen(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []

    async def fake_impl(*, pmids: list[str], **_: Any) -> dict[str, Any]:
        seen.append(pmids)
        return {"passages": [{"pmid": pmid, "text": "t"} for pmid in pmids]}

    async def fake_service() -> object:
        return object()

    monkeypatch.setattr(publication_tools, "get_publication_passages_impl", fake_impl)
    monkeypatch.setattr(publication_tools, "get_publication_passage_service", fake_service)
    return seen


async def _passages(pmids: list[str]) -> Any:
    async with Client(create_pubtator_mcp(profile="full")) as client:
        return await client.call_tool(
            "get_publication_passages", {"pmids": pmids}, raise_on_error=False
        )


async def test_pmcid_returns_passages_in_one_call(
    discovery: FakeDiscovery, passages_seen: list[list[str]]
) -> None:
    result = await _passages(["PMC3518823", "25741868"])

    payload = result.structured_content
    assert result.is_error is False
    assert passages_seen == [["23248578", "25741868"]]
    assert payload["resolved_from"] == [
        {"input": "PMC3518823", "form": "pmcid", "resolved_to": "23248578"}
    ]
    await _passages(["pmc3518823"])  # cached: no second converter call
    assert discovery.calls == [["PMC3518823"]]


async def test_doi_converts_and_plain_pmid_has_no_echo(
    discovery: FakeDiscovery, passages_seen: list[list[str]]
) -> None:
    doi = await _passages(["doi:10.1038/NG.2500"])
    plain = await _passages(["23248578"])

    assert doi.structured_content["resolved_from"][0]["form"] == "doi"
    assert passages_seen == [["23248578"], ["23248578"]]
    assert "resolved_from" not in plain.structured_content


async def test_single_pmid_tool_echoes_one_resolution(
    discovery: FakeDiscovery, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_impl(*, pmid: str, **_: Any) -> dict[str, Any]:
        return {"pmid": pmid}

    async def fake_service() -> object:
        return object()

    monkeypatch.setattr(publication_tools, "get_publication_citation_graph_impl", fake_impl)
    monkeypatch.setattr(publication_tools, "get_citation_graph_service", fake_service)
    async with Client(create_pubtator_mcp(profile="full")) as client:
        result = await client.call_tool("get_publication_citation_graph", {"pmid": "PMC3518823"})

    assert result.structured_content["result"]["pmid"] == "23248578"
    assert result.structured_content["resolved_from"]["resolved_to"] == "23248578"


@pytest.mark.parametrize("bad", ["PMC", "PMC12x", "10.12/x", "PMC\u0661\u0662"])
async def test_misshaped_ids_never_reach_the_converter(
    discovery: FakeDiscovery, passages_seen: list[list[str]], bad: str
) -> None:
    result = await _passages([bad])

    assert result.is_error is True
    assert discovery.calls == []
    assert passages_seen == []
