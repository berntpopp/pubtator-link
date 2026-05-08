from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InspectReviewIndexCursor:
    scope_hash: str
    source_offset: int
    failed_source_offset: int
    version: int = 1


def inspect_review_index_scope_hash(
    *,
    review_id: str,
    session_id: str | None,
    pmids: list[str],
) -> str:
    payload = {
        "review_id": review_id,
        "session_id": session_id,
        "pmids": sorted(pmids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def encode_inspect_review_index_cursor(cursor: InspectReviewIndexCursor) -> str:
    payload = {
        "v": cursor.version,
        "scope_hash": cursor.scope_hash,
        "source_offset": cursor.source_offset,
        "failed_source_offset": cursor.failed_source_offset,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_inspect_review_index_cursor(
    token: str,
    *,
    expected_scope_hash: str,
) -> InspectReviewIndexCursor:
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(f"{token}{padding}".encode("ascii"))
        payload: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        raise ValueError("invalid inspect_review_index cursor") from exc

    if payload.get("v") != 1:
        raise ValueError("invalid inspect_review_index cursor version")
    if payload.get("scope_hash") != expected_scope_hash:
        raise ValueError("cursor scope does not match request")

    source_offset = payload.get("source_offset")
    failed_source_offset = payload.get("failed_source_offset")
    if not isinstance(source_offset, int) or source_offset < 0:
        raise ValueError("invalid inspect_review_index source offset")
    if not isinstance(failed_source_offset, int) or failed_source_offset < 0:
        raise ValueError("invalid inspect_review_index failed source offset")

    return InspectReviewIndexCursor(
        scope_hash=expected_scope_hash,
        source_offset=source_offset,
        failed_source_offset=failed_source_offset,
    )
