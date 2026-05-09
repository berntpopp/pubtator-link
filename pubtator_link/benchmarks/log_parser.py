from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ToolCallEvent(BaseModel):
    tool_name: str
    status: str | None = None
    coverage_summary: dict[str, int] = Field(default_factory=dict)


class EventAnalysis(BaseModel):
    tool_calls: list[ToolCallEvent] = Field(default_factory=list)
    mcp_tool_call_count: int = 0
    event_counts: dict[str, int] = Field(default_factory=dict)


def parse_cli_events(path: Path) -> EventAnalysis:
    events: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return analyze_events(events)


def analyze_events(events: list[dict[str, Any]]) -> EventAnalysis:
    tool_calls: list[ToolCallEvent] = []
    counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type:
            counts[event_type] = counts.get(event_type, 0) + 1
        tool_name = event.get("tool_name") or event.get("name")
        if (
            event_type in {"tool_call_completed", "tool_call_failed", "tool_call_started"}
            and tool_name
        ):
            tool_calls.append(
                ToolCallEvent(
                    tool_name=str(tool_name),
                    status=str(event.get("status")) if event.get("status") is not None else None,
                    coverage_summary={
                        str(key): int(value)
                        for key, value in dict(event.get("coverage_summary") or {}).items()
                    },
                )
            )
    return EventAnalysis(
        tool_calls=tool_calls,
        mcp_tool_call_count=len(tool_calls),
        event_counts=counts,
    )
