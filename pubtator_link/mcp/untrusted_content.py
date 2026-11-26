"""Typed structural fencing for externally sourced prose at the MCP boundary."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from typing import Any, Literal

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


def _fence_key(holder: Any, key: str, *, source: str, record_id: str) -> None:
    if isinstance(holder, dict) and isinstance(holder.get(key), str):
        holder[key] = fence_untrusted_text(
            holder[key], source=source, record_id=record_id
        ).model_dump(mode="json")


def fence_passages(node: Any, record_id: str | None = None) -> None:
    """Fence the prose (`text`, `tail_preview`, `quote`) of every passage in a payload, in place.

    A passage is any object with a `passage_id`; its quote inherits the id. Run at the shared
    MCP egress, so stored review-index passages leave fenced like live publication passages.
    """
    if isinstance(node, list):
        for item in node:
            fence_passages(item, record_id)
    if not isinstance(node, dict) or node.get("kind") == "untrusted_text":
        return
    own = node.get("passage_id")
    record_id = own if isinstance(own, str) else record_id
    if record_id is not None:
        source = node.get("source_kind")
        for key in ("text", "tail_preview", "quote"):  # `quote` is a string in the audit trail
            _fence_key(
                node,
                key,
                source=source if isinstance(source, str) else "review_index",
                record_id=record_id,
            )
    for value in node.values():
        fence_passages(value, record_id)


def fence_export_documents(dumped: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Fence the upstream prose of a dumped annotation export, in place (#293).

    Covers every export serialization: BioC JSON passage ``text`` and the publisher-authored
    ``infons.license`` / ``infons.xml``, the raw ``content`` of an unparsed or BioC XML document,
    a document-level ``text``, and the title/abstract ``sections`` of the PubTator format.
    Identifiers, offsets, types and entity annotations stay structured data.
    """
    export = dumped.get("export_data")
    documents = export.get("documents") if isinstance(export, dict) else None
    for document in documents if isinstance(documents, list) else []:
        if not isinstance(document, dict):
            continue
        doc_id = str(document.get("id") or document.get("pmid") or "unknown")
        for key in ("content", "text"):
            _fence_key(document, key, source=source, record_id=doc_id)
        sections = document.get("sections")
        for section in list(sections) if isinstance(sections, dict) else []:
            _fence_key(sections, section, source=source, record_id=f"{doc_id}#{section}")
        passages = document.get("passages")
        for passage in passages if isinstance(passages, list) else []:
            if not isinstance(passage, dict):
                continue
            record_id = f"{doc_id}#{passage.get('offset', 0)}"
            _fence_key(passage, "text", source=source, record_id=record_id)
            for key in ("license", "xml"):
                _fence_key(passage.get("infons"), key, source=source, record_id=record_id)
    return dumped


def fence_variant_snippets(dumped: dict[str, Any]) -> dict[str, Any]:
    """Fence each literature hit's ``snippet`` (upstream highlight or abstract), in place (#293)."""
    for hit in dumped.get("literature", []):
        _fence_key(hit, "snippet", source="pubtator_search", record_id=f"PMID:{hit.get('pmid')}")
    return dumped


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
