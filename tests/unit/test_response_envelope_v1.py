"""Locks the ratified GeneFoundry Response-Envelope Standard v1 (flat banner)
at this backend's MCP wrapper boundary (``pubtator_link.mcp.errors.run_mcp_tool``).
Adapted from clingen-link (the fleet reference, PR #20).

This test intentionally locks pubtator-link's ACTUAL shipped wrapper
behavior, not the idealized reference shape, because the two diverge:

* SUCCESS -- ``run_mcp_tool`` is a pure passthrough on success: it returns
  exactly what the tool body's ``call()`` returns, unchanged. Envelope
  construction (``success``, ``results``/``result``, and
  ``_meta.unsafe_for_clinical_use``) is the tool body's responsibility here,
  not the wrapper's -- unlike clingen, where the wrapper itself stamps
  ``_meta`` on success.

* FAILURE -- ``run_mcp_tool`` does not return a flat dict; it RAISES
  ``fastmcp.exceptions.ToolError`` whose ``str()`` is a JSON-encoded flat
  dict: ``{success, error_code, message, retryable, fallback_tool,
  fallback_args, recovery, _meta{next_commands, unsafe_for_clinical_use}}``.
  This is flat (never a nested ``"error": {}`` shape) but differs from the
  ratified contract in two confirmed ways: the recovery-text key is
  ``recovery``, not ``recovery_action``; and ``_meta`` carries no ``tool``
  key (it carries ``next_commands`` instead).
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.services.errors import UpstreamUnavailableError


@pytest.mark.asyncio
async def test_success_envelope_is_passed_through_unchanged() -> None:
    """``run_mcp_tool`` does not construct the success envelope; it is a
    passthrough. This locks that the wrapper does not mutate, drop, or wrap
    whatever envelope the tool body already produced."""

    async def call() -> dict[str, object]:
        return {
            "success": True,
            "results": [{"id": "x"}],
            "_meta": {"unsafe_for_clinical_use": True},
        }

    result = await run_mcp_tool("search_literature", call)

    assert result["success"] is True
    assert result["results"] == [{"id": "x"}]
    assert result["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_single_item_result_key_is_preserved() -> None:
    """Same passthrough contract for the singular ``result`` payload shape."""

    async def call() -> dict[str, object]:
        return {
            "success": True,
            "result": {"id": "x"},
            "_meta": {"unsafe_for_clinical_use": True},
        }

    result = await run_mcp_tool("search_literature", call)

    assert result["success"] is True
    assert result["result"] == {"id": "x"}
    assert result["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_error_envelope_is_flat_and_raised_as_tool_error() -> None:
    """FAILURE path: the wrapper raises ``ToolError`` carrying a flat JSON
    payload (never a bare exception, never a nested ``error: {}`` shape).
    Also locks the two confirmed drifts from the ratified contract: the key
    is ``recovery`` (not ``recovery_action``), and ``_meta`` has no ``tool``
    key."""

    async def call() -> dict[str, object]:
        raise UpstreamUnavailableError("upstream timed out")

    with pytest.raises(ToolError) as exc_info:
        await run_mcp_tool("search_literature", call)

    payload = json.loads(str(exc_info.value))

    assert payload["success"] is False
    assert isinstance(payload["error_code"], str) and payload["error_code"]
    assert payload["error_code"] == "upstream_unavailable"
    assert isinstance(payload["message"], str) and payload["message"]
    assert isinstance(payload["retryable"], bool)
    assert payload["retryable"] is True
    assert "error" not in payload  # flat, not nested
    assert payload["_meta"]["unsafe_for_clinical_use"] is True

    # Confirmed drift from the ratified flat-banner contract (documented in
    # the module docstring): this backend ships `recovery`, not
    # `recovery_action`, and `_meta` has no `tool` key.
    assert isinstance(payload["recovery"], str) and payload["recovery"]
    assert "recovery_action" not in payload
    assert "tool" not in payload["_meta"]
