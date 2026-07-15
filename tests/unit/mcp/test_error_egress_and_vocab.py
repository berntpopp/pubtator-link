"""Egress error-canonicalization + closed-vocabulary drift guards (Codex re-review round)."""

from __future__ import annotations

from typing import Any, get_args

from fastmcp import Client, FastMCP

from pubtator_link.api.search_filters import VALID_PUBLICATION_TYPES
from pubtator_link.mcp.errors import CANONICAL_ERROR_CODES, install_validation_error_handler
from pubtator_link.mcp.tools._vocab import PublicationType


def test_publication_type_enum_matches_advanced_filter_vocab() -> None:
    """The advertised `publication_types` enum and the advanced-`filters` type validator must
    enforce the SAME vocabulary, or `{"type":[...]}` could bypass the enum (P1-2)."""
    assert frozenset(get_args(PublicationType)) == VALID_PUBLICATION_TYPES


async def test_raised_tool_error_reaches_wire_as_structured_envelope() -> None:
    """A tool error RAISED outside run_mcp_tool must still reach the wire with isError:true AND a
    non-null structuredContent whose error_code is in the six-value enum (P1-3) -- never
    isError:true + structuredContent:null, and never a leaked exception message."""
    mcp = FastMCP(name="pubtator-link", version="test")

    @mcp.tool(output_schema=None)
    async def boom() -> dict[str, Any]:
        raise RuntimeError("kaboom postgres://user:secret@db/leak")

    install_validation_error_handler(mcp)

    async with Client(mcp) as client:
        result = await client.call_tool("boom", {}, raise_on_error=False)

    assert result.is_error is True
    assert result.structured_content is not None
    assert result.structured_content.get("error_code") in CANONICAL_ERROR_CODES
    serialized = str(result.structured_content)
    assert "kaboom" not in serialized
    assert "secret" not in serialized
