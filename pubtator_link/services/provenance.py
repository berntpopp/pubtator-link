from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any


def corpus_snapshot_date() -> str:
    """Return the local date used for live upstream corpus snapshots."""
    return date.today().isoformat()


def index_snapshot_date() -> str:
    """Return the local date used for review-index snapshots."""
    return date.today().isoformat()


def stable_cache_key(namespace: str, payload: dict[str, Any]) -> str:
    """Return a compact deterministic key for request provenance."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{namespace}:{digest}"
