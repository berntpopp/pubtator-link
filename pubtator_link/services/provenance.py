from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from datetime import UTC, date, datetime
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


# Response-Envelope v1.2: when the values served to the current tool call were fetched from
# their upstream. One list per call, shared with child tasks through the ContextVar.
_FETCHES: ContextVar[list[str] | None] = ContextVar("upstream_fetches", default=None)


def utc_z(moment: datetime) -> str:
    """An RFC 3339 UTC timestamp with ``Z``."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> str:
    return utc_z(datetime.now(UTC))


def start_fetch_log() -> list[str]:
    """Begin collecting the fetch times behind one tool call."""
    log: list[str] = []
    _FETCHES.set(log)
    return log


def record_fetch(fetched_at: str) -> None:
    """Note the upstream fetch time of a value a cache just served."""
    log = _FETCHES.get()
    if log is not None:
        log.append(fetched_at)
