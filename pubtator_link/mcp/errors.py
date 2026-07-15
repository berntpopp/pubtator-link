from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import asyncpg
import httpx
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.tools.tool import ToolResult
from pydantic import ValidationError as PydanticValidationError

from pubtator_link.api.client import PubTatorAPIError
from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.mcp.untrusted_content import sanitize_message
from pubtator_link.mcp.validation_errors import extract_validation_details
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

# Response-Envelope Standard v1: ``error_code`` is a CLOSED enum, harmonized across the fleet.
# Anything else (however sensible it reads) is a violation, because a client branching on the
# code sees an unrecognized value. Internally we keep a finer-grained *reason* (used to pick the
# recovery text and metrics label); this table projects every reason onto the six canonical codes
# that reach the wire.
CANONICAL_ERROR_CODES: frozenset[str] = frozenset(
    {
        "invalid_input",
        "not_found",
        "ambiguous_query",
        "upstream_unavailable",
        "rate_limited",
        "internal",
    }
)

_REASON_TO_CANONICAL: dict[str, str] = {
    # bad argument the caller CAN fix -> invalid_input (never not_found: not_found tells the model
    # the *tool* does not exist, so it strikes it from its list and never calls it again).
    "validation_failed": "invalid_input",
    "curated_url_rejected": "invalid_input",
    # the review database (an upstream dependency of this server) is unreachable or its schema is
    # not current -> upstream_unavailable, so the model retries rather than treating it as a bug.
    "review_index_unavailable": "upstream_unavailable",
    "review_schema_not_current": "upstream_unavailable",
    # server-side faults -> internal.
    "output_validation_failed": "internal",
    "internal_error": "internal",
}


def canonical_error_code(reason: str) -> str:
    """Project an internal error *reason* onto the closed wire enum."""
    if reason in CANONICAL_ERROR_CODES:
        return reason
    return _REASON_TO_CANONICAL.get(reason, "internal")


def mcp_field_validation_error(
    *,
    field: str,
    reason: str,
    recovery_hint: str,
) -> dict[str, Any]:
    return {
        "code": "invalid_input",
        "field_errors": [{"field": field, "reason": reason}],
        "recovery_hint": recovery_hint,
    }


def _sever_validation_frame(field_errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Rebuild a validation frame with every string value code-point-stripped.

    The rejected caller VALUE is already kept out of the message at the source
    (input normalization raises server-authored, value-free field errors); this
    boundary is a defensive backstop that also strips forbidden code points from
    any field/message string before it reaches either MCP mirror.
    """
    severed: list[dict[str, Any]] = []
    for entry in field_errors:
        if isinstance(entry, dict):
            severed.append(
                {
                    key: sanitize_message(value) if isinstance(value, str) else value
                    for key, value in entry.items()
                }
            )
    return severed


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


def _classify_error_message(message: str) -> str:
    """Map raw backend messages to safe, LLM-actionable summaries.

    Every branch returns a fixed, server-authored string; an unmapped message
    falls through to a generic sentence rather than echoing ``str(exc)``. The
    raw upstream response body is additionally severed at the API client
    (Surface A), so it never reaches this function.
    """
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


def sanitize_error_message(message: str) -> str:
    """Return a safe, code-point-stripped summary for a raw backend message.

    The semantic allowlist decides the surfaced sentence; the result is then run
    through ``sanitize_message`` (strip forbidden control/zero-width/bidi/NUL code
    points + length-cap) as a defensive backstop so no forbidden code point can
    ever reach a caller-visible error frame, whatever the fallthrough.
    """
    return sanitize_message(_classify_error_message(message))


def _is_pubtator_upstream_unavailable(exc: Exception) -> bool:
    if not isinstance(exc, PubTatorAPIError):
        return False
    message = str(exc).lower()
    terminal_reason = exc.terminal_reason or exc.retry_metadata.get("terminal_reason")
    return (
        exc.status_code in {502, 503, 504}
        or terminal_reason in {"request_error", "filtered_search_unavailable"}
        # Back-compat: the raw upstream body is now severed at the client
        # (Surface A) and its transient-outage meaning travels as the
        # ``filtered_search_unavailable`` terminal_reason above; these substring
        # checks still classify any exception constructed with the legacy body.
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
    # Retention sink (not caller-visible: ``get_recent_mcp_errors`` filters
    # ``_``-prefixed keys). Even so, no raw upstream body / PII is retained here:
    # callers no longer pass ``str(exc)`` as ``raw_message`` and any value that is
    # provided is code-point-stripped + capped, per the no-raw-sink policy.
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_name": tool_name,
        "error_code": error_code,
        "message": sanitize_error_message(message)[:500],
        "_raw_message": sanitize_message(raw_message)[:500] if raw_message else None,
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


def error_reason_for_exception(exc: Exception) -> str:
    """Return a fine-grained internal *reason* (drives recovery text + metrics).

    This is NOT the wire code. Project it with :func:`canonical_error_code` before it reaches a
    caller-visible envelope, so the wire ``error_code`` stays inside the closed fleet enum.
    """
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


def error_code_for_exception(exc: Exception) -> str:
    """Return the closed-enum wire ``error_code`` for an exception."""
    return canonical_error_code(error_reason_for_exception(exc))


def _fallback_for_context(context: McpErrorContext) -> tuple[str | None, dict[str, Any] | None]:
    if context.fallback_tool is not None:
        return context.fallback_tool, context.fallback_args or {}
    if context.tool_name == "preflight_review_sources" and context.pmids:
        return (
            "get_publication_passages",
            {"pmids": context.pmids, "mode": "full_abstract"},
        )
    if (
        context.tool_name
        in {
            "index_review_evidence",
            "stage_research_session",
        }
        and context.pmids
    ):
        return (
            "get_publication_passages",
            {"pmids": context.pmids, "mode": "compact_passages"},
        )
    return None, None


def _recovery_text_for_context(
    context: McpErrorContext,
    fallback_tool: str | None,
    reason: str = "internal_error",
) -> str:
    if reason == "review_schema_not_current":
        return (
            "Run diagnostics. If the review schema is stale, apply database migrations and retry."
        )
    if context.tool_name == "preflight_review_sources" and fallback_tool:
        return (
            "Call get_publication_passages with the same PMIDs. "
            "Use mode='full_abstract' for article-local answering; run diagnostics only if "
            "passage retrieval also fails."
        )
    if reason == "upstream_unavailable":
        if context.tool_name == "search_literature":
            return (
                "Retry later. If optional filters caused the upstream failure, retry without "
                "filters and post-filter the returned results client-side."
            )
        return "Retry later or run diagnostics if the upstream failure persists."
    if reason == "curated_url_rejected":
        return "Use curated URLs from the configured public literature source allowlist."
    if context.tool_name == "convert_article_ids":
        return (
            "Retry with one identifier at a time. If only DOI conversion fails, search "
            "the DOI or title with search_literature."
        )
    if context.tool_name == "submit_text_annotation":
        return (
            "Retry with a shorter text or fewer bioconcepts. If submission still fails, "
            "use search_biomedical_entities for entity lookup."
        )
    if context.tool_name == "export_review_audit_bundle":
        return (
            "Use fallback_inline=True or ask the operator to configure file export. Inspect "
            "get_review_audit_trail if bundle export still fails."
        )
    return (
        "Inspect recent_mcp_errors in diagnostics and retry with the documented "
        "fallback if available."
    )


def _pmids_for_exception(exc: Exception) -> list[str] | None:
    pmids = getattr(exc, "pmids", None)
    if not isinstance(pmids, list):
        return None
    normalized = [str(pmid).strip() for pmid in pmids if str(pmid).strip()]
    return normalized or None


def _pydantic_validation_details(exc: BaseException) -> list[dict[str, Any]]:
    """Return pydantic ``.errors()`` details for an argument-validation failure.

    FastMCP 3.4.3+ re-raises argument-validation ``pydantic.ValidationError`` as
    ``fastmcp.exceptions.ValidationError`` (see fastmcp #4128), chaining the
    original pydantic error via ``__cause__``. Walk the cause chain so callers
    keep the structured ``loc``/``type`` details needed for retry guidance,
    regardless of which layer surfaced the failure.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        errors = getattr(current, "errors", None)
        if isinstance(current, PydanticValidationError) and callable(errors):
            return list(errors())
        current = current.__cause__
    return []


def mcp_validation_tool_error(
    *,
    tool_name: str,
    parameters: dict[str, Any],
    exc: BaseException,
) -> dict[str, Any]:
    """Build a sanitized flat envelope for a validation failure raised before
    tool execution starts (never raised -- see ``install_validation_error_handler``)."""
    details = extract_validation_details(parameters, _pydantic_validation_details(exc))
    # ``unexpected_params`` echoes the caller-supplied (arbitrary) argument names;
    # strip forbidden code points before they reach either MCP mirror. The other
    # keys are schema-derived (server-authored) and safe.
    if isinstance(details.get("unexpected_params"), list):
        details["unexpected_params"] = [
            sanitize_message(name) if isinstance(name, str) else name
            for name in details["unexpected_params"]
        ]
    # The rejected value must produce a message the model can ACT on: a bare "Invalid MCP
    # arguments." names nothing. Name the accepted parameters (schema-derived, server-authored,
    # safe to surface) and carry a structured ``field_errors`` frame -- caller-invented argument
    # names are redacted to "unknown" rather than echoed. (Response-Envelope Standard v1;
    # MCP 2025-11-25 SEP-1303: "Tool Execution Errors contain actionable feedback".)
    valid_params = details.get("valid_params") or []
    message = "Invalid MCP arguments."
    if valid_params:
        message += " Accepted parameters: " + ", ".join(valid_params) + "."
    field_errors: list[dict[str, str]] = []
    for missing in details.get("missing_params") or []:
        field_errors.append({"field": missing, "reason": "required parameter is missing"})
    if details.get("unexpected_params"):
        field_errors.append({"field": "unknown", "reason": "argument is not accepted by this tool"})
    payload: dict[str, Any] = {
        "success": False,
        "error_code": "invalid_input",
        "message": message,
        "retryable": False,
        "fallback_tool": None,
        "fallback_args": None,
        "recovery_action": _recovery_text_for_context(
            McpErrorContext(tool_name=tool_name),
            fallback_tool=None,
            reason="validation_failed",
        ),
        "_meta": {
            "tool": tool_name,
            "next_commands": [{"tool": "diagnostics", "arguments": {}}],
            "unsafe_for_clinical_use": True,
        },
    }
    if field_errors:
        payload["field_errors"] = field_errors
    payload.update(details)
    record_mcp_error(
        tool_name=tool_name,
        error_code="invalid_input",
        message=payload["message"],
    )
    record_mcp_tool_call(
        tool_name=tool_name,
        outcome="failure",
        error_code="invalid_input",
        latency_seconds=0.0,
    )
    return payload


def _is_error_envelope(value: Any) -> bool:
    """Fingerprint a flat failure envelope built by this module.

    ``recovery_action`` is exclusive to :func:`mcp_tool_error` and
    :func:`mcp_validation_tool_error` -- no tool body in this codebase sets it
    on its own ``success: False`` business payloads (e.g.
    ``research_session_status_payload``), so this predicate cannot
    misclassify an unrelated non-error result as a protocol error.
    """
    return isinstance(value, dict) and value.get("success") is False and "recovery_action" in value


def install_validation_error_handler(mcp_server: Any) -> None:
    """Wrap registered tools so failures return the flat in-band envelope.

    Two responsibilities are centralised here rather than duplicated at each
    ``run_mcp_tool`` call site:

    * FastMCP argument-validation failures (``PydanticValidationError`` on
      fastmcp<3.4.3, or ``fastmcp.exceptions.ValidationError`` on fastmcp>=3.4.3,
      raised by ``Tool.run`` before the tool body executes) are converted to
      the same flat envelope shape ``run_mcp_tool`` uses for execution
      failures, and returned instead of raised.
    * Any tool result whose ``structured_content`` is one of our error
      envelopes (see ``_is_error_envelope``) is re-wrapped as
      ``ToolResult(is_error=True, ...)`` so the wire-level MCP ``isError``
      flag is set. Returning the envelope as a plain dict would otherwise be
      validated by the low-level MCP SDK against the tool's *success*
      ``outputSchema`` (e.g. ``SearchResponse``'s required fields) and get
      rejected, masking the real error behind a generic "Output validation
      error". Constructing ``ToolResult(is_error=True, ...)`` bypasses that
      check entirely: FastMCP round-trips an error result straight through
      ``CallToolResult``, skipping schema validation (verified against the
      installed fastmcp==3.4.3: ``ToolResult.to_mcp_result()`` returns a
      ``CallToolResult`` whenever ``is_error`` is set).
    """
    tool_manager = getattr(mcp_server, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", {})
    for tool in tools.values():
        if getattr(tool, "_pubtator_validation_wrapped", False):
            continue
        original_run = tool.run

        async def wrapped_run(
            arguments: dict[str, Any],
            *,
            _original_run: Callable[[dict[str, Any]], Awaitable[Any]] = original_run,
            _tool: Any = tool,
        ) -> Any:
            try:
                result = await _original_run(arguments)
            except (PydanticValidationError, FastMCPValidationError) as exc:
                # FastMCP 3.4.3+ re-raises argument-validation pydantic errors as
                # fastmcp.exceptions.ValidationError (see fastmcp #4128); older
                # releases raised the raw pydantic error. Catch both so failures
                # keep returning the flat envelope instead of propagating.
                payload = mcp_validation_tool_error(
                    tool_name=str(_tool.name),
                    parameters=dict(_tool.parameters),
                    exc=exc,
                )
                return ToolResult(structured_content=payload, is_error=True)
            structured = getattr(result, "structured_content", None)
            # Response-Envelope Standard v1: every ``success: false`` envelope MUST carry MCP
            # ``isError: true`` so a client branching on isError surfaces it to the model. This
            # covers both the flat error frame (recovery_action) and any business payload that sets
            # success=False on its own (e.g. a partial estimate or a not-found manifest).
            if isinstance(structured, dict) and structured.get("success") is False:
                return ToolResult(
                    structured_content=structured,
                    meta=result.meta,
                    is_error=True,
                )
            return result

        object.__setattr__(tool, "run", wrapped_run)
        object.__setattr__(tool, "_pubtator_validation_wrapped", True)


def mcp_tool_error(exc: Exception, context: McpErrorContext) -> dict[str, Any]:
    """Build a sanitized flat envelope for an MCP tool execution failure.

    Returned (never raised) so ``run_mcp_tool`` can hand the caller an
    in-band ``success: false`` result; ``install_validation_error_handler``
    is what upgrades it to a wire-level ``isError: true`` result.
    """
    # Log only sanitized structured fields. A raw ``exc_info`` here would render
    # the exception message and traceback (which can carry a Postgres DSN,
    # credentials, host/IP, or free-text PII) into logs despite the sanitized
    # envelope returned to the caller.
    reason = error_reason_for_exception(exc)
    error_code = canonical_error_code(reason)
    logger.warning(
        "MCP tool execution failed",
        extra={
            "tool_name": context.tool_name,
            "error_code": error_code,
            "exception_type": type(exc).__name__,
        },
    )
    fallback_tool, fallback_args = _fallback_for_context(context)
    exception_pmids = _pmids_for_exception(exc)
    if fallback_tool is None and context.tool_name == "ground_question" and exception_pmids:
        fallback_tool = "get_publication_passages"
        fallback_args = {"pmids": exception_pmids, "mode": "compact_passages"}
    next_commands: list[dict[str, Any]] = []
    if fallback_tool and fallback_args is not None:
        next_commands.append({"tool": fallback_tool, "arguments": fallback_args})
    next_commands.append({"tool": "diagnostics", "arguments": {}})
    payload: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        "message": "Invalid MCP arguments."
        if isinstance(exc, InputNormalizationError)
        else safe_message_for_exception(exc),
        "retryable": error_code == "upstream_unavailable",
        "fallback_tool": fallback_tool,
        "fallback_args": fallback_args,
        "recovery_action": _recovery_text_for_context(context, fallback_tool, reason),
        "_meta": {
            "tool": context.tool_name,
            "next_commands": next_commands,
            "unsafe_for_clinical_use": True,
        },
    }
    if isinstance(exc, InputNormalizationError):
        payload["field_errors"] = _sever_validation_frame(exc.field_errors)
        payload["recovery_hint"] = sanitize_message(exc.recovery_hint)
    if context.degraded_mode is not None:
        payload["degraded_mode"] = context.degraded_mode
    diagnostics_snapshot = bounded_diagnostics_snapshot(context.diagnostics_snapshot)
    if diagnostics_snapshot is not None:
        payload["diagnostics_snapshot"] = diagnostics_snapshot
    if context.fallback_preview is not None:
        payload["fallback_preview"] = context.fallback_preview
    return payload


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
    """Run one MCP tool body and return a flat envelope for success or failure.

    Never raises for execution failures: the caller always gets a ``dict``
    back, either the tool body's own payload (with ``success``/``_meta``
    filled in if absent) or the flat ``mcp_tool_error`` failure frame.
    ``install_validation_error_handler`` upgrades a returned failure frame to
    a wire-level ``isError: true`` result once it reaches ``Tool.run``.
    """
    started_at = perf_counter()
    pmid_count = len(pmids or [])
    logger.info("mcp_tool_started", extra={"tool_name": tool_name, "pmid_count": pmid_count})
    try:
        result = await func()
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
        # Do NOT retain ``str(exc)``: for an upstream failure it can carry the
        # (now client-severed) response body or free-text PII. Only the already
        # sanitized, body-free ``message`` is recorded.
        record_mcp_error(
            tool_name=tool_name,
            error_code=error_code,
            message=message,
        )
        record_mcp_tool_call(
            tool_name=tool_name,
            outcome="failure",
            error_code=error_code,
            latency_seconds=latency_seconds,
        )
        return mcp_tool_error(
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
        )
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
    if isinstance(result, dict):
        result.setdefault("success", True)
        existing_meta = result.get("_meta")
        merged_meta: dict[str, Any] = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        merged_meta["tool"] = tool_name
        merged_meta["unsafe_for_clinical_use"] = True
        result["_meta"] = merged_meta
    return result
