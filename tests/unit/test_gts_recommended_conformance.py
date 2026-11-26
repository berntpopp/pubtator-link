"""Pagination block, typed unsupported-identifier errors and complete not-found frames."""

from __future__ import annotations

from typing import Any

import pytest

from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.foreign_ids import reject_foreign_gene
from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.mcp.session_orientation import research_session_status_payload
from pubtator_link.mcp.tools.literature import with_next_page_command


def test_search_result_carries_meta_pagination() -> None:
    result = {
        "total_results": 42,
        "has_more": True,
        "next_page": 1,
        "next_offset": 5,
        "_meta": {},
    }
    paged = with_next_page_command(result, "search_literature", {"text": "x"})
    assert paged["_meta"]["pagination"] == {
        "total_count": 42,
        "has_more": True,
        "next_cursor": None,
        "next_page": 1,
        "next_offset": 5,
    }


@pytest.mark.parametrize(
    ("value", "tool"),
    [
        ("HGNC:1100", "hgnc_resolve_symbol"),
        ("ENSG00000012048", "hgnc_resolve_symbol"),
        ("NCBIGene:672", "hgnc_resolve_gene_by_xref"),
        ("672", "hgnc_resolve_gene_by_xref"),
    ],
)
@pytest.mark.asyncio
async def test_foreign_gene_identifier_is_typed_invalid_input(value: str, tool: str) -> None:
    async def call() -> dict[str, Any]:
        reject_foreign_gene(value, "gene")
        return {"success": True}

    frame = await run_mcp_tool("get_variant_evidence", call)
    assert frame["error_code"] == "invalid_input"
    assert frame["field"] == "gene"
    assert frame["allowed_values"]
    assert [c["tool"] for c in frame["_meta"]["next_commands"]] == [tool]


@pytest.mark.parametrize("symbol", ["BRCA1", "C9orf72", "HLA-DRB1"])
def test_gene_symbol_is_not_rejected(symbol: str) -> None:
    try:
        reject_foreign_gene(symbol, "gene")
    except InputNormalizationError:
        pytest.fail(f"{symbol} is a symbol")


@pytest.mark.asyncio
async def test_missing_research_session_frame_has_retryable() -> None:
    class Service:
        async def get_status_by_session_id(self, *, session_id: str) -> None:
            raise LookupError(session_id)

    frame = await research_session_status_payload(
        service=Service(), review_id=None, session_id="session-1"
    )
    assert frame["error_code"] == "not_found"
    assert frame["retryable"] is False


@pytest.mark.asyncio
async def test_text_annotation_not_ready_is_processing_and_text_is_parsed() -> None:
    from pubtator_link.api.client import PubTatorAPIError
    from pubtator_link.api.text_annotation_polling import retrieve_text_annotation_result

    async def not_ready() -> dict[str, Any]:
        raise PubTatorAPIError("PubTator3 API returned HTTP 400.", status_code=400)

    async def ready() -> dict[str, Any]:
        return {
            "content": "00000|t|The BRCA1 protein interacts with RAD51.\n00000|a|-NoAbstract-\n"
            "00000\t4\t9\tBRCA1\tGene\t672\n00000\t33\t38\tRAD51\tGene\t5888\n"
        }

    async def failed() -> dict[str, Any]:
        raise PubTatorAPIError("PubTator3 API returned HTTP 503.", status_code=503)

    assert await retrieve_text_annotation_result(not_ready) == {"status": "processing"}
    result = await retrieve_text_annotation_result(ready)
    assert result["status"] == "completed"
    assert result["original_text"] == "The BRCA1 protein interacts with RAD51."
    assert result["annotations"][0] == {
        "start": 4,
        "end": 9,
        "text": "BRCA1",
        "entity_type": "Gene",
        "entity_id": "672",
    }
    with pytest.raises(PubTatorAPIError):
        await retrieve_text_annotation_result(failed)


def test_results_tool_is_listed_only_with_the_submit_tool() -> None:
    from pubtator_link.mcp.profiles import tool_names_for_profile

    assert "get_text_annotation_results" not in tool_names_for_profile("readonly")
    assert {"submit_text_annotation", "get_text_annotation_results"} <= tool_names_for_profile(
        "full"
    )


def test_stored_passage_prose_is_fenced_once() -> None:
    from pubtator_link.mcp.untrusted_content import fence_passages

    payload = {
        "result": {
            "passages": [
                {
                    "passage_id": "PMID:1:abstract:0",
                    "source_kind": "pubtator_abstract",
                    "text": "Prose from an article.",
                    "tail_preview": None,
                    "quote": {"text": "Prose"},
                }
            ]
        },
        "message": "server text",
    }
    fence_passages(payload)
    fence_passages(payload)  # idempotent: a fenced object is left alone
    passage = payload["result"]["passages"][0]
    assert passage["text"]["kind"] == "untrusted_text"
    assert passage["text"]["text"] == "Prose from an article."
    assert passage["text"]["provenance"]["record_id"] == "PMID:1:abstract:0"
    assert passage["text"]["provenance"]["source"] == "pubtator_abstract"
    assert passage["quote"]["text"]["kind"] == "untrusted_text"
    assert passage["tail_preview"] is None
    assert payload["message"] == "server text"
