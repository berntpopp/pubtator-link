"""Caller authorization for PubTator write tools (opt-in via require_write_scope).

The gated set is the authoritative ``WRITE_TOOLS`` from ``mcp.profiles`` — the same
inventory the profile system uses — so a new write tool cannot silently escape the
gate. Registered only when ``auth_mode == "oauth"`` and ``require_write_scope`` is on.
"""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from pubtator_link.mcp.profiles import WRITE_TOOLS

# Single source of truth — do NOT hand-maintain a parallel list.
GATED_WRITE_TOOLS = WRITE_TOOLS


class WriteAuthorizationMiddleware(Middleware):
    """Require the pubtator:write scope before any write tool runs."""

    async def on_call_tool(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        name = getattr(context.message, "name", "")
        if name in GATED_WRITE_TOOLS:
            token = get_access_token()
            scopes = set(token.scopes) if token is not None else set()
            if "pubtator:write" not in scopes:
                raise ToolError("This tool requires the pubtator:write scope")
        return await call_next(context)
