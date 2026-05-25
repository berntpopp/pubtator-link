from __future__ import annotations

import json
import re
from typing import Any, cast

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
    suggested_action = "Call pubtator_diagnostics, then retry with corrected arguments."
    if fallback_response_mode is not None:
        suggested_action = (
            f"Retry {tool_name} with response_mode='{fallback_response_mode}' while "
            "the server output schema is being repaired."
        )
    payload: dict[str, Any] = {
        "success": False,
        "error_code": "output_validation_failed",
        "message": "The tool response did not match its declared MCP output schema.",
        "error_field": error_field,
        "suggested_action": suggested_action,
        "fallback_response_mode": fallback_response_mode,
        "_meta": {
            "next_commands": [
                {"tool": "pubtator_diagnostics", "arguments": {}},
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
        error_code="output_validation_failed",
        message=payload["message"],
    )
    return payload


def install_output_validation_error_handler(mcp_server: Any) -> None:
    """Wrap the MCP call-tool handler so SDK output validation errors are observable."""
    handler = mcp_server._mcp_server.request_handlers.get(mcp.types.CallToolRequest)
    if handler is None:
        return

    async def wrapped(request: mcp.types.CallToolRequest) -> mcp.types.ServerResult:
        result = cast(mcp.types.ServerResult, await handler(request))
        call_result = getattr(result, "root", None)
        if not isinstance(call_result, mcp.types.CallToolResult):
            return result
        if not call_result.isError or not call_result.content:
            return result
        first_content = call_result.content[0]
        message = getattr(first_content, "text", "")
        if not isinstance(message, str) or not message.startswith(OUTPUT_VALIDATION_PREFIX):
            return result
        payload = actionable_output_validation_error(
            tool_name=request.params.name,
            arguments=request.params.arguments or {},
            message=message,
        )
        return mcp.types.ServerResult(
            mcp.types.CallToolResult(
                content=[
                    mcp.types.TextContent(
                        type="text",
                        text=json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    )
                ],
                isError=True,
            )
        )

    mcp_server._mcp_server.request_handlers[mcp.types.CallToolRequest] = wrapped


def _output_validation_field(message: str) -> str | None:
    match = _REQUIRED_PROPERTY_RE.search(message)
    if match is not None:
        return match.group("field")
    return None


def _fallback_response_mode(tool_name: str, arguments: dict[str, Any]) -> str | None:
    if (
        tool_name == "pubtator_retrieve_review_context_batch"
        and str(arguments.get("response_mode", "compact")).lower() == "compact"
    ):
        return "quotes"
    return None
