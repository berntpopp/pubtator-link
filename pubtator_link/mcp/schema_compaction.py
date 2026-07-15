"""Compact advertised INPUT schemas without changing runtime validation.

Tool-Surface Budget Standard v1 charges every client for the serialized `tools/list` entry on
every request. Pydantic renders an optional ``X | None`` parameter as
``{"anyOf": [{"type": "X"}, {"type": "null"}], "default": null}`` and stamps an auto-generated
``title`` on the schema and each property. None of that is load-bearing for a model choosing an
argument (descriptions and enums are), and it inflates the surface by roughly a fifth.

This pass rewrites each tool's *advertised* ``parameters`` schema in place to:

* collapse ``anyOf: [<branch>, {"type": "null"}]`` to ``<branch>`` (the parameter is still optional
  by virtue of not appearing in ``required``; the runtime keeps accepting ``None`` via its default),
* drop the redundant ``default: null`` that pairs with such optionals, and
* drop auto-generated ``title`` keys.

It NEVER touches ``description``, ``examples``, ``enum``, ``items``, or numeric/string constraints,
so the schema stays fully documented and every declared vocabulary stays declared.

Runtime argument validation is unaffected: FastMCP validates incoming calls against the pydantic
model derived from the function signature, not against this advertised dict, so a narrower
advertised type never rejects a value the runtime accepts (the harmless direction).
"""

from __future__ import annotations

from typing import Any

_MERGE_KEYS = ("type", "items", "enum", "format", "minimum", "maximum", "minLength", "maxLength")


def _collapse_nullable(prop: dict[str, Any]) -> None:
    branches = prop.get("anyOf")
    if not isinstance(branches, list):
        return
    non_null = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
    has_null = any(isinstance(b, dict) and b.get("type") == "null" for b in branches)
    if not has_null or len(non_null) != 1:
        return
    keep = non_null[0]
    del prop["anyOf"]
    for key, value in keep.items():
        prop.setdefault(key, value)
    if prop.get("default", "__sentinel__") is None:
        del prop["default"]


def _compact_property(prop: Any) -> None:
    if not isinstance(prop, dict):
        return
    prop.pop("title", None)
    _collapse_nullable(prop)


def compact_input_schemas(mcp: Any) -> None:
    """Rewrite every registered tool's advertised input schema in place."""
    tool_manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", {})
    for tool in tools.values():
        schema = getattr(tool, "parameters", None)
        if not isinstance(schema, dict):
            continue
        schema.pop("title", None)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for prop in properties.values():
                _compact_property(prop)
