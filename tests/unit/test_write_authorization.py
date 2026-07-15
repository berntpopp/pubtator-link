"""Write-scope authorization over the authoritative WRITE_TOOLS set."""

from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

import pubtator_link.authorization as az
from pubtator_link.authorization import WriteAuthorizationMiddleware
from pubtator_link.mcp.profiles import WRITE_TOOLS


class _Ctx:
    def __init__(self, name: str) -> None:
        self.message = SimpleNamespace(name=name)


async def _call_next(_ctx: object) -> str:
    return "ok"


def test_middleware_covers_every_authoritative_write_tool() -> None:
    # Regression guard: the gate uses the single source of truth, not a hand list.
    from pubtator_link.authorization import GATED_WRITE_TOOLS

    assert GATED_WRITE_TOOLS == WRITE_TOOLS


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS))
async def test_write_tool_denied_without_scope(monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    monkeypatch.setattr(az, "get_access_token", lambda: SimpleNamespace(scopes=["pubtator:read"]))
    with pytest.raises(ToolError, match="pubtator:write"):
        await WriteAuthorizationMiddleware().on_call_tool(_Ctx(tool), _call_next)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS))
async def test_write_tool_allowed_with_scope(monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    monkeypatch.setattr(az, "get_access_token", lambda: SimpleNamespace(scopes=["pubtator:write"]))
    result = await WriteAuthorizationMiddleware().on_call_tool(_Ctx(tool), _call_next)
    assert result == "ok"


@pytest.mark.asyncio
async def test_read_tool_never_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(az, "get_access_token", lambda: None)
    result = await WriteAuthorizationMiddleware().on_call_tool(_Ctx("search_literature"), _call_next)
    assert result == "ok"
