from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST as _PROMETHEUS_CONTENT_TYPE_LATEST,
)
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
)

CONTENT_TYPE_LATEST = _PROMETHEUS_CONTENT_TYPE_LATEST

MCP_TOOL_CALLS = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls by tool, outcome, and error code.",
    ("tool_name", "outcome", "error_code"),
)

MCP_TOOL_LATENCY_SECONDS = Histogram(
    "mcp_tool_latency_seconds",
    "MCP tool call latency in seconds.",
    ("tool_name", "outcome"),
)


def record_mcp_tool_call(
    *,
    tool_name: str,
    outcome: str,
    latency_seconds: float,
    error_code: str = "",
) -> None:
    """Record one MCP tool lifecycle outcome."""
    MCP_TOOL_CALLS.labels(
        tool_name=tool_name,
        outcome=outcome,
        error_code=error_code,
    ).inc()
    MCP_TOOL_LATENCY_SECONDS.labels(tool_name=tool_name, outcome=outcome).observe(latency_seconds)


def metrics_payload() -> bytes:
    """Return the current Prometheus exposition payload."""
    return generate_latest()
