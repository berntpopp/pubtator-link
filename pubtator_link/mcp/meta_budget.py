from __future__ import annotations

from copy import deepcopy
from typing import Any

DIAGNOSTIC_FIELDS = frozenset(
    {
        "_meta",
        "rrf_score",
        "lexical_rank_position",
        "dense_rank_position",
        "rank_features",
        "provider_status",
    }
)


def strip_meta_for_repeated_call(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without workflow/debug metadata for repeated MCP calls."""
    stripped = deepcopy(payload)
    _strip_diagnostic_fields(stripped)
    return stripped


def _strip_diagnostic_fields(value: Any) -> None:
    if isinstance(value, dict):
        for field in DIAGNOSTIC_FIELDS:
            value.pop(field, None)
        for child in value.values():
            _strip_diagnostic_fields(child)
        return
    if isinstance(value, list):
        for item in value:
            _strip_diagnostic_fields(item)
