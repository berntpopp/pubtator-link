from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from fastmcp import FastMCP


def install_inspection_managers(mcp: FastMCP) -> None:
    provider = cast(Any, mcp.providers[0])
    components = provider._components
    tools = {
        component.name: component
        for key, component in components.items()
        if key.startswith("tool:")
    }
    resources = {
        str(component.uri): component
        for key, component in components.items()
        if key.startswith("resource:")
    }
    prompts = {
        component.name: component
        for key, component in components.items()
        if key.startswith("prompt:")
    }

    inspectable_mcp = cast(Any, mcp)
    inspectable_mcp._tool_manager = SimpleNamespace(_tools=tools)
    inspectable_mcp._resource_manager = SimpleNamespace(_resources=resources)
    inspectable_mcp._prompt_manager = SimpleNamespace(_prompts=prompts)
