"""Locks the ratified GeneFoundry Response-Envelope Standard v1 (flat banner)
at this backend's MCP wrapper boundary (``pubtator_link.mcp.errors.run_mcp_tool``).
Adapted from clingen-link (the fleet reference, PR #20).

v1 shape (breaking change from the pre-v1 raise-based wrapper this test used
to lock):

* SUCCESS -- ``run_mcp_tool`` fills in the envelope the tool body did not
  already provide: ``success`` (via ``setdefault``, so a tool body's own
  explicit ``False`` survives) and a per-call ``_meta`` merged with ``tool``
  and ``unsafe_for_clinical_use``. It never replaces or drops keys the tool
  body already set (e.g. ``results``/``result``).

* FAILURE -- ``run_mcp_tool`` RETURNS (never raises) a flat dict:
  ``{success, error_code, message, retryable, fallback_tool, fallback_args,
  recovery_action, _meta{tool, next_commands, unsafe_for_clinical_use}}``.
  This is flat (never a nested ``"error": {}`` shape). ``recovery_action``
  replaces the pre-v1 ``recovery`` key name, and ``_meta.tool`` is new.
"""

from __future__ import annotations

import pytest

from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.services.errors import UpstreamUnavailableError


@pytest.mark.asyncio
async def test_success_envelope_fills_in_missing_meta_without_dropping_payload() -> None:
    """``run_mcp_tool`` does not construct the payload; it only backfills the
    envelope. This locks that the wrapper does not drop or overwrite whatever
    payload keys the tool body already produced."""

    async def call() -> dict[str, object]:
        return {"success": True, "results": [{"id": "x"}]}

    result = await run_mcp_tool("search_literature", call)

    assert result["success"] is True
    assert result["results"] == [{"id": "x"}]
    assert result["_meta"]["tool"] == "search_literature"
    assert result["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_single_item_result_key_is_preserved() -> None:
    """Same backfill contract for the singular ``result`` payload shape."""

    async def call() -> dict[str, object]:
        return {"success": True, "result": {"id": "x"}}

    result = await run_mcp_tool("search_literature", call)

    assert result["success"] is True
    assert result["result"] == {"id": "x"}
    assert result["_meta"]["tool"] == "search_literature"
    assert result["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_success_meta_merge_preserves_tool_body_meta_keys() -> None:
    """The wrapper MERGES into an existing ``_meta`` block (e.g.
    ``next_commands`` set by the tool body) rather than replacing it."""

    async def call() -> dict[str, object]:
        return {
            "success": True,
            "results": [],
            "_meta": {"next_commands": [{"tool": "diagnostics", "arguments": {}}]},
        }

    result = await run_mcp_tool("search_literature", call)

    assert result["_meta"]["next_commands"] == [{"tool": "diagnostics", "arguments": {}}]
    assert result["_meta"]["tool"] == "search_literature"
    assert result["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_error_envelope_is_flat_and_returned_not_raised() -> None:
    """FAILURE path: the wrapper RETURNS a flat dict payload (never raises,
    never a nested ``error: {}`` shape). Locks the two v1 changes from the
    pre-v1 shape: the key is ``recovery_action`` (not ``recovery``), and
    ``_meta.tool`` is present."""

    async def call() -> dict[str, object]:
        raise UpstreamUnavailableError("upstream timed out")

    payload = await run_mcp_tool("search_literature", call)

    assert payload["success"] is False
    assert isinstance(payload["error_code"], str) and payload["error_code"]
    assert payload["error_code"] == "upstream_unavailable"
    assert isinstance(payload["message"], str) and payload["message"]
    assert isinstance(payload["retryable"], bool)
    assert payload["retryable"] is True
    assert "error" not in payload  # flat, not nested

    # v1: recovery_action replaces recovery; _meta.tool is new.
    assert isinstance(payload["recovery_action"], str) and payload["recovery_action"]
    assert "recovery" not in payload
    assert payload["_meta"]["tool"] == "search_literature"
    assert payload["_meta"]["unsafe_for_clinical_use"] is True
