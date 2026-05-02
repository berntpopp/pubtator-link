from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import asyncpg
import httpx
from fastmcp.exceptions import ToolError

from pubtator_link.observability.metrics import record_mcp_tool_call

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpErrorContext:
    """Context used to build an MCP tool execution error."""

    tool_name: str
    pmids: list[str] | None = None
    fallback_tool: str | None = None
    fallback_args: dict[str, Any] | None = None


def sanitize_error_message(message: str) -> str:
    """Map raw backend messages to safe, LLM-actionable summaries."""
    lowered = message.lower()
    if "updated_at" in lowered and "reviews" in lowered:
        return "Review database schema is not current."
    if "database" in lowered or "postgres" in lowered or "asyncpg" in lowered:
        return "Review database operation failed."
    if "timeout" in lowered:
        return "The upstream service timed out."
    return "The tool could not complete the requested operation."


def error_code_for_exception(exc: Exception) -> str:
    """Return a stable code suitable for deterministic LLM branching."""
    message = str(exc).lower()
    if "updated_at" in message and "reviews" in message:
        return "review_schema_not_current"
    if isinstance(exc, asyncpg.PostgresError):
        return "review_index_unavailable"
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "upstream_unavailable"
    if isinstance(exc, ValueError):
        return "validation_failed"
    return "internal_error"


def _fallback_for_context(context: McpErrorContext) -> tuple[str | None, dict[str, Any] | None]:
    if context.fallback_tool is not None:
        return context.fallback_tool, context.fallback_args or {}
    if (
        context.tool_name
        in {
            "pubtator.index_review_evidence",
            "pubtator.stage_research_session",
        }
        and context.pmids
    ):
        return (
            "pubtator.get_publication_passages",
            {"pmids": context.pmids, "mode": "compact_passages"},
        )
    return None, None


def mcp_tool_error(exc: Exception, context: McpErrorContext) -> ToolError:
    """Build a sanitized FastMCP tool-execution error."""
    logger.warning(
        "MCP tool execution failed",
        extra={"tool_name": context.tool_name},
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    fallback_tool, fallback_args = _fallback_for_context(context)
    next_commands: list[dict[str, Any]] = []
    if fallback_tool and fallback_args is not None:
        next_commands.append({"tool": fallback_tool, "arguments": fallback_args})
    next_commands.append({"tool": "pubtator.diagnostics", "arguments": {}})
    payload = {
        "success": False,
        "error_code": error_code_for_exception(exc),
        "message": sanitize_error_message(str(exc)),
        "retryable": False,
        "fallback_tool": fallback_tool,
        "fallback_args": fallback_args,
        "recovery": "Run pubtator.diagnostics. If the review schema is stale, apply database migrations and retry.",
        "_meta": {
            "next_commands": next_commands,
            "unsafe_for_clinical_use": True,
        },
    }
    return ToolError(json.dumps(payload, separators=(",", ":"), sort_keys=True))


async def run_mcp_tool(
    tool_name: str,
    func: Callable[[], Awaitable[dict[str, Any]]],
    *,
    pmids: list[str] | None = None,
    fallback_tool: str | None = None,
    fallback_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one MCP tool body and convert execution failures to ToolError."""
    started_at = perf_counter()
    pmid_count = len(pmids or [])
    logger.info("mcp_tool_started", extra={"tool_name": tool_name, "pmid_count": pmid_count})
    try:
        result = await func()
    except ToolError:
        latency_seconds = perf_counter() - started_at
        logger.warning(
            "mcp_tool_failed",
            extra={
                "tool_name": tool_name,
                "pmid_count": pmid_count,
                "latency_ms": round(latency_seconds * 1000, 2),
                "error_code": "tool_error",
            },
        )
        record_mcp_tool_call(
            tool_name=tool_name,
            outcome="failure",
            error_code="tool_error",
            latency_seconds=latency_seconds,
        )
        raise
    except Exception as exc:
        latency_seconds = perf_counter() - started_at
        error_code = error_code_for_exception(exc)
        logger.warning(
            "mcp_tool_failed",
            extra={
                "tool_name": tool_name,
                "pmid_count": pmid_count,
                "latency_ms": round(latency_seconds * 1000, 2),
                "error_code": error_code,
            },
        )
        record_mcp_tool_call(
            tool_name=tool_name,
            outcome="failure",
            error_code=error_code,
            latency_seconds=latency_seconds,
        )
        raise mcp_tool_error(
            exc,
            McpErrorContext(
                tool_name=tool_name,
                pmids=pmids,
                fallback_tool=fallback_tool,
                fallback_args=fallback_args,
            ),
        ) from exc
    latency_seconds = perf_counter() - started_at
    logger.info(
        "mcp_tool_completed",
        extra={
            "tool_name": tool_name,
            "pmid_count": pmid_count,
            "latency_ms": round(latency_seconds * 1000, 2),
        },
    )
    record_mcp_tool_call(
        tool_name=tool_name,
        outcome="success",
        latency_seconds=latency_seconds,
    )
    return result
