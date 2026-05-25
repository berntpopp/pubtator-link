from __future__ import annotations

from typing import Any


def text_annotation_degraded_payload(
    session_id: str,
    status: str,
    message: str | None,
) -> dict[str, Any]:
    return {
        "success": False,
        "session_id": session_id,
        "status": status,
        "original_text": "",
        "bioconcept": "",
        "annotations": [],
        "processing_time": None,
        "retryable": True,
        "message": message or "PubTator text annotation upstream is unavailable.",
        "next_tools": ["pubtator_get_text_annotation_results"],
    }
