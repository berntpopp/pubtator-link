"""MCP diagnostics payload helpers."""

from __future__ import annotations

import json
from typing import Any

MAX_DIAGNOSTICS_SNAPSHOT_CHARS = 2048


def bounded_diagnostics_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a compact diagnostics snapshot or None if it is too large."""
    if snapshot is None:
        return None
    safe = {
        key: value
        for key, value in snapshot.items()
        if key in {"database", "review_index", "recovery_hint"}
    }
    encoded = json.dumps(safe, separators=(",", ":"), sort_keys=True)
    return safe if len(encoded) <= MAX_DIAGNOSTICS_SNAPSHOT_CHARS else None
