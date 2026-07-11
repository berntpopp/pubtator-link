"""Typed structural fencing for externally sourced prose at the MCP boundary."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

FORBIDDEN_CODEPOINTS = frozenset(
    {
        *range(0x0000, 0x0009),
        *range(0x000B, 0x000D),
        *range(0x000E, 0x0020),
        *range(0x007F, 0x00A0),
        0x200B,
        0x200C,
        0x200D,
        0x2060,
        0xFEFF,
        *range(0x202A, 0x202F),
        *range(0x2066, 0x206A),
    }
)


class UntrustedTextProvenance(BaseModel):
    """Source identity for one fenced external text object."""

    source: str
    record_id: str
    retrieved_at: datetime


class UntrustedText(BaseModel):
    """External prose represented as typed data with digest and provenance."""

    kind: Literal["untrusted_text"] = "untrusted_text"
    text: str
    provenance: UntrustedTextProvenance
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def fence_untrusted_text(raw: str, *, source: str, record_id: str) -> UntrustedText:
    """Normalize external prose and remove only the ratified control characters."""
    normalized = unicodedata.normalize("NFC", raw)
    clean = "".join(char for char in normalized if ord(char) not in FORBIDDEN_CODEPOINTS)
    return UntrustedText(
        text=clean,
        provenance=UntrustedTextProvenance(
            source=source,
            record_id=record_id,
            retrieved_at=datetime.now(UTC),
        ),
        raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


MAX_MESSAGE_CHARS = 280


def sanitize_message(text: str) -> str:
    """Strip the fence's forbidden control/zero-width/bidi/NUL code points + length-cap.

    Applied to EVERY caller-visible message/error/diagnostics/warning string (the
    error envelope, the shaped per-item drop/provider-status rows, resource
    handlers, session-orientation payloads) so a hostile upstream -- or a
    caller-influenced 4xx/5xx body reflected into ``str(exc)`` -- can never smuggle
    control, zero-width, bidirectional, or NUL code points into a caller-visible
    field. These strings are server-/provider-authored guidance data; the raw
    upstream response body is additionally kept out of them at the source
    (Surface A, see ``pubtator_link/api/client.py``).
    """
    clean = "".join(char for char in text if ord(char) not in FORBIDDEN_CODEPOINTS)
    return clean[:MAX_MESSAGE_CHARS]
