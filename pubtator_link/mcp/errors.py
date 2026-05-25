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

from pubtator_link.api.client import PubTatorAPIError
from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.observability.metrics import record_mcp_tool_call
from pubtator_link.services.degradation import DegradedMode
from pubtator_link.services.errors import (
    ReviewIndexUnavailableError,
    ReviewSchemaStaleError,
    UpstreamUnavailableError,
    ValidationFailureError,
)
from pubtator_link.services.mcp_diagnostics import bounded_diagnostics_snapshot
from pubtator_link.services.url_safety import UrlSafetyError

logger = logging.getLogger(__name__)

RECENT_MCP_ERROR_LIMIT = 50
_RECENT_MCP_ERRORS: list[dict[str, Any]] = []


def mcp_field_validation_error(
    *,
    field: str,
    reason: str,
    recovery_hint: str,
) -> dict[str, Any]:
    return {
        "code": "validation_failed",
        "field_errors": [{"field": field, "reason": reason}],
        "recovery_hint": recovery_hint,
    }


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
        "Invalid MCP arguments.",
        "The tool response did not match its declared MCP output schema.",
        "Review database schema is not current.",
        "Review database operation failed.",
        "Curated URL rejected by hostname allowlist.",
        "The upstream service is temporarily unavailable.",
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


def _is_pubtator_upstream_unavailable(exc: Exception) -> bool:
    if not isinstance(exc, PubTatorAPIError):
        return False
    message = str(exc).lower()
    terminal_reason = exc.terminal_reason or exc.retry_metadata.get("terminal_reason")
    return (
        exc.status_code in {502, 503, 504}
        or terminal_reason == "request_error"
        or "currently updating the database" in message
        or "please try again later" in message
    )


def safe_message_for_exception(exc: Exception) -> str:
    """Return a stable safe message for known typed exceptions."""
    if isinstance(exc, ReviewSchemaStaleError):
        return "Review database schema is not current."
    if isinstance(exc, ReviewIndexUnavailableError):
        return "Review database operation failed."
    if isinstance(exc, UpstreamUnavailableError):
        return "The upstream service is temporarily unavailable."
    if isinstance(exc, UrlSafetyError):
        return "Curated URL rejected by hostname allowlist."
    if _is_pubtator_upstream_unavailable(exc):
        return "The upstream service is temporarily unavailable."
    if isinstance(exc, ValidationFailureError):
        return "Invalid MCP arguments."
    return sanitize_error_message(str(exc))


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
        "_raw_message": raw_message[:500] if raw_message else None,
    }
    _RECENT_MCP_ERRORS.append(entry)
    del _RECENT_MCP_ERRORS[:-RECENT_MCP_ERROR_LIMIT]


def get_recent_mcp_errors(limit: int = 10) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in _RECENT_MCP_ERRORS[-limit:]
    ]


def clear_recent_mcp_errors() -> None:
    _RECENT_MCP_ERRORS.clear()


def error_code_for_exception(exc: Exception) -> str:
    """Return a stable code suitable for deterministic LLM branching."""
    if isinstance(exc, ReviewSchemaStaleError):
        return "review_schema_not_current"
    if isinstance(exc, ReviewIndexUnavailableError):
        return "review_index_unavailable"
    if isinstance(exc, UpstreamUnavailableError):
        return "upstream_unavailable"
    if isinstance(exc, UrlSafetyError):
        return "curated_url_rejected"
    if _is_pubtator_upstream_unavailable(exc):
        return "upstream_unavailable"
    if isinstance(exc, ValidationFailureError):
        return "validation_failed"
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
    if context.tool_name == "pubtator_preflight_review_sources" and context.pmids:
        return (
            "pubtator_get_publication_passages",
            {"pmids": context.pmids, "mode": "full_abstract"},
        )
    if (
        context.tool_name
        in {
            "pubtator_index_review_evidence",
            "pubtator_stage_research_session",
        }
        and context.pmids
    ):
        return (
            "pubtator_get_publication_passages",
            {"pmids": context.pmids, "mode": "compact_passages"},
        )
    return None, None


def _recovery_text_for_context(
    context: McpErrorContext,
    fallback_tool: str | None,
    error_code: str = "internal_error",
) -> str:
    if error_code == "review_schema_not_current":
        return (
            "Run pubtator_diagnostics. If the review schema is stale, apply database "
            "migrations and retry."
        )
    if context.tool_name == "pubtator_preflight_review_sources" and fallback_tool:
        return (
            "Call pubtator_get_publication_passages with the same PMIDs. "
            "Use mode='full_abstract' for article-local answering; run diagnostics only if "
            "passage retrieval also fails."
        )
    if error_code == "upstream_unavailable":
        if context.tool_name == "pubtator_search_literature":
            return (
                "Retry later. If optional filters caused the upstream failure, retry without "
                "filters and post-filter the returned results client-side."
            )
        return "Retry later or run pubtator_diagnostics if the upstream failure persists."
    if error_code == "curated_url_rejected":
        return "Use curated URLs from the configured public literature source allowlist."
    if context.tool_name == "pubtator_convert_article_ids":
        return (
            "Retry with one identifier at a time. If only DOI conversion fails, search "
            "the DOI or title with pubtator_search_literature."
        )
    if context.tool_name == "pubtator_submit_text_annotation":
        return (
            "Retry with a shorter text or fewer bioconcepts. If submission still fails, "
            "use pubtator_search_biomedical_entities for entity lookup."
        )
    if context.tool_name == "pubtator_export_review_audit_bundle":
        return (
            "Use fallback_inline=True or choose a writable export_path. Inspect "
            "pubtator_get_review_audit_trail if bundle export still fails."
        )
    return (
        "Inspect recent_mcp_errors in pubtator_diagnostics and retry with the documented "
        "fallback if available."
    )


def _pmids_for_exception(exc: Exception) -> list[str] | None:
    pmids = getattr(exc, "pmids", None)
    if not isinstance(pmids, list):
        return None
    normalized = [str(pmid).strip() for pmid in pmids if str(pmid).strip()]
    return normalized or None


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
    exception_pmids = _pmids_for_exception(exc)
    if (
        fallback_tool is None
        and context.tool_name == "pubtator_ground_question"
        and exception_pmids
    ):
        fallback_tool = "pubtator_get_publication_passages"
        fallback_args = {"pmids": exception_pmids, "mode": "compact_passages"}
    next_commands: list[dict[str, Any]] = []
    if fallback_tool and fallback_args is not None:
        next_commands.append({"tool": fallback_tool, "arguments": fallback_args})
    next_commands.append({"tool": "pubtator_diagnostics", "arguments": {}})
    error_code = error_code_for_exception(exc)
    payload = {
        "success": False,
        "error_code": error_code,
        "message": "Invalid MCP arguments."
        if isinstance(exc, InputNormalizationError)
        else safe_message_for_exception(exc),
        "retryable": error_code == "upstream_unavailable",
        "fallback_tool": fallback_tool,
        "fallback_args": fallback_args,
        "recovery": _recovery_text_for_context(context, fallback_tool, error_code),
        "_meta": {
            "next_commands": next_commands,
            "unsafe_for_clinical_use": True,
        },
    }
    if isinstance(exc, InputNormalizationError):
        payload["field_errors"] = exc.field_errors
        payload["recovery_hint"] = exc.recovery_hint
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
        message = safe_message_for_exception(exc)
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
