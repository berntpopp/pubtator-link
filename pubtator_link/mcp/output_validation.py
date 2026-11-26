from __future__ import annotations

import json
import re
import uuid
from typing import Any

import mcp.types

from pubtator_link.mcp.errors import record_mcp_error

OUTPUT_VALIDATION_PREFIX = "Output validation error:"
_REQUIRED_PROPERTY_RE = re.compile(r"'(?P<field>[^']+)' is a required property")


def actionable_output_validation_error(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Return and record an actionable MCP output-schema validation failure."""
    error_field = _output_validation_field(message)
    fallback_response_mode = _fallback_response_mode(tool_name, arguments)
    suggested_action = "Call diagnostics, then retry with corrected arguments."
    if fallback_response_mode is not None:
        suggested_action = (
            f"Retry {tool_name} with response_mode='{fallback_response_mode}' while "
            "the server output schema is being repaired."
        )
    payload: dict[str, Any] = {
        "success": False,
        "error_code": "internal",
        "message": "The tool response did not match its declared MCP output schema.",
        "error_field": error_field,
        "suggested_action": suggested_action,
        "fallback_response_mode": fallback_response_mode,
        "_meta": {
            "request_id": uuid.uuid4().hex[:12],
            "elapsed_ms": 0.0,  # built outside any tool run
            "next_commands": [
                {"tool": "diagnostics", "arguments": {}},
            ],
            "unsafe_for_clinical_use": True,
        },
    }
    if fallback_response_mode is not None:
        payload["_meta"]["next_commands"].insert(
            0,
            {
                "tool": tool_name,
                "arguments": {**arguments, "response_mode": fallback_response_mode},
            },
        )
    record_mcp_error(
        tool_name=tool_name,
        error_code="internal",
        message=payload["message"],
    )
    return payload


def install_output_validation_error_handler(mcp_server: Any) -> None:
    """Wrap the MCP call-tool handler so SDK output validation errors are observable."""
    lowlevel = mcp_server._mcp_server
    entry = lowlevel.get_request_handler("tools/call")
    if entry is None:
        return
    handler = entry.handler

    async def wrapped(ctx: Any, params: Any) -> Any:
        result = await handler(ctx, params)
        if not isinstance(result, mcp.types.CallToolResult):
            return result
        if not result.is_error or not result.content:
            return result
        first_content = result.content[0]
        message = getattr(first_content, "text", "")
        if not isinstance(message, str) or not message.startswith(OUTPUT_VALIDATION_PREFIX):
            return result
        payload = actionable_output_validation_error(
            tool_name=params.name,
            arguments=params.arguments or {},
            message=message,
        )
        return mcp.types.CallToolResult(
            content=[
                mcp.types.TextContent(
                    type="text",
                    text=json.dumps(payload, separators=(",", ":"), sort_keys=True),
                )
            ],
            is_error=True,
        )

    lowlevel.add_request_handler("tools/call", entry.params_type, wrapped)


def _output_validation_field(message: str) -> str | None:
    match = _REQUIRED_PROPERTY_RE.search(message)
    if match is not None:
        return match.group("field")
    return None


def _fallback_response_mode(tool_name: str, arguments: dict[str, Any]) -> str | None:
    if (
        tool_name == "get_review_context_batch"
        and str(arguments.get("response_mode", "compact")).lower() == "compact"
    ):
        return "quotes"
    return None
