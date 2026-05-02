from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import asyncpg
import httpx
from fastmcp.exceptions import ToolError

from pubtator_link.observability.metrics import record_mcp_tool_call
from pubtator_link.services.degradation import DegradedMode
from pubtator_link.services.mcp_diagnostics import bounded_diagnostics_snapshot

logger = logging.getLogger(__name__)

RECENT_MCP_ERROR_LIMIT = 50
_RECENT_MCP_ERRORS: list[dict[str, Any]] = []


@dataclass(frozen=True)
class McpErrorContext:
    """Context used to build an MCP tool execution error."""

    tool_name: str
    pmids: list[str] | None = None
    fallback_tool: str | None = None
    fallback_args: dict[str, Any] | None = None
    diagnostics_snapshot: dict[str, Any] | None = None
    degraded_mode: DegradedMode | None = None
    fallback_preview: dict[str, Any] | None = None


def sanitize_error_message(message: str) -> str:
    """Map raw backend messages to safe, LLM-actionable summaries."""
    safe_messages = {
        "Review database schema is not current.",
        "Review database operation failed.",
        "The upstream service timed out.",
        "The tool could not complete the requested operation.",
    }
    if message in safe_messages:
        return message
    lowered = message.lower()
    if "updated_at" in lowered and "reviews" in lowered:
        return "Review database schema is not current."
    if (
        "database" in lowered
        or "postgres" in lowered
        or "asyncpg" in lowered
        or "relation" in lowered
    ):
        return "Review database operation failed."
    if "timeout" in lowered:
        return "The upstream service timed out."
    return "The tool could not complete the requested operation."


def record_mcp_error(
    *,
    tool_name: str,
    error_code: str,
    message: str,
    raw_message: str | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_name": tool_name,
        "error_code": error_code,
        "message": sanitize_error_message(message)[:500],
        "raw_message": raw_message[:500] if raw_message else None,
    }
    _RECENT_MCP_ERRORS.append(entry)
    del _RECENT_MCP_ERRORS[:-RECENT_MCP_ERROR_LIMIT]


def get_recent_mcp_errors(limit: int = 10) -> list[dict[str, Any]]:
    return [dict(item) for item in _RECENT_MCP_ERRORS[-limit:]]


def clear_recent_mcp_errors() -> None:
    _RECENT_MCP_ERRORS.clear()


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


def _tool_error_details(exc: ToolError) -> tuple[str, str]:
    try:
        payload = json.loads(str(exc))
    except json.JSONDecodeError:
        return "tool_error", sanitize_error_message(str(exc))
    if not isinstance(payload, dict):
        return "tool_error", sanitize_error_message(str(exc))
    error_code = payload.get("error_code")
    message = payload.get("message")
    return (
        error_code if isinstance(error_code, str) else "tool_error",
        message if isinstance(message, str) else sanitize_error_message(str(exc)),
    )


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
    if context.degraded_mode is not None:
        payload["degraded_mode"] = context.degraded_mode
    diagnostics_snapshot = bounded_diagnostics_snapshot(context.diagnostics_snapshot)
    if diagnostics_snapshot is not None:
        payload["diagnostics_snapshot"] = diagnostics_snapshot
    if context.fallback_preview is not None:
        payload["fallback_preview"] = context.fallback_preview
    return ToolError(json.dumps(payload, separators=(",", ":"), sort_keys=True))


async def run_mcp_tool(
    tool_name: str,
    func: Callable[[], Awaitable[dict[str, Any]]],
    *,
    pmids: list[str] | None = None,
    fallback_tool: str | None = None,
    fallback_args: dict[str, Any] | None = None,
    diagnostics_snapshot: dict[str, Any] | None = None,
    degraded_mode: DegradedMode | None = None,
    fallback_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one MCP tool body and convert execution failures to ToolError."""
    started_at = perf_counter()
    pmid_count = len(pmids or [])
    logger.info("mcp_tool_started", extra={"tool_name": tool_name, "pmid_count": pmid_count})
    try:
        result = await func()
    except ToolError as exc:
        latency_seconds = perf_counter() - started_at
        error_code, message = _tool_error_details(exc)
        logger.warning(
            "mcp_tool_failed",
            extra={
                "tool_name": tool_name,
                "pmid_count": pmid_count,
                "latency_ms": round(latency_seconds * 1000, 2),
                "error_code": error_code,
            },
        )
        record_mcp_error(
            tool_name=tool_name,
            error_code=error_code,
            message=message,
            raw_message=str(exc),
        )
        record_mcp_tool_call(
            tool_name=tool_name,
            outcome="failure",
            error_code=error_code,
            latency_seconds=latency_seconds,
        )
        raise
    except Exception as exc:
        latency_seconds = perf_counter() - started_at
        error_code = error_code_for_exception(exc)
        message = sanitize_error_message(str(exc))
        logger.warning(
            "mcp_tool_failed",
            extra={
                "tool_name": tool_name,
                "pmid_count": pmid_count,
                "latency_ms": round(latency_seconds * 1000, 2),
                "error_code": error_code,
            },
        )
        record_mcp_error(
            tool_name=tool_name,
            error_code=error_code,
            message=message,
            raw_message=str(exc),
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
                diagnostics_snapshot=diagnostics_snapshot,
                degraded_mode=degraded_mode,
                fallback_preview=fallback_preview,
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
