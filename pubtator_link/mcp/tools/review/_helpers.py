from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastmcp import Context, FastMCP

from pubtator_link.mcp.profiles import MCPToolProfile


async def _warn_if_degraded(ctx: Context | None, result: dict[str, Any]) -> None:
    degraded_mode = result.get("degraded_mode")
    if ctx is not None and degraded_mode:
        await ctx.warning(
            "Review evidence is degraded: "
            f"{degraded_mode}. Inspect coverage before relying on passage-level claims.",
        )


async def _report_index_progress(
    ctx: Context | None,
    *,
    progress: float,
    total: float = 100,
) -> None:
    if ctx is not None:
        await ctx.report_progress(progress=progress, total=total)


def make_mcp_tool_for(
    mcp: FastMCP,
    profile: MCPToolProfile,
) -> Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]]:
    def mcp_tool_for(
        *profiles: MCPToolProfile, **tool_kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if profile in profiles:
                return cast(Callable[..., Any], mcp.tool(**tool_kwargs)(fn))
            return fn

        return decorator

    return mcp_tool_for
